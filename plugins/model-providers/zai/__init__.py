"""ZAI / GLM provider profile — 用户插件覆盖版本。

此文件放在 $HERMES_HOME/plugins/model-providers/zai/__init__.py，
通过 Hermes 的 last-writer-wins 机制自动覆盖内置同名 profile。
hermes update 不会影响此文件（它在 git 仓库之外）。

=== 解决的问题 ===

Hermes 的 _supports_reasoning_extra_body() 不匹配 Z.AI（open.bigmodel.cn /
api.z.ai），导致 reasoning_effort、thinking、tool_stream 从未发送；
_needs_thinking_reasoning_pad() 不含 GLM 检测，导致 reasoning_content
在工具调用回合不被回传。

=== 功能 ===

综合以下 PR 方案：
  #51108  GLM-5.2 原生 reasoning_effort 控制
  #24915  tool_stream=true 防止 Z.AI 30 秒空闲超时
  #51195  reasoning_content 回传保持

=== thinking / reasoning_effort 行为（2026-06-29 官方文档+API实测验证）===

GLM-5.2（主模型）：
  - thinking 强制开启（thinking=disabled 被服务端忽略，实测确认）
  - reasoning_effort 是唯一的思考控制手段
  - none/minimal → 模型放弃思考（reasoning_tokens=0，3 难度 × 2 参数共 6 次实测确认）
  - low/medium → 服务端映射为 high（官方文档声明）
  - xhigh → 服务端映射为 max（官方文档声明）
  - 空值/未设置 → 服务端默认深度（max）
  - thinking + reasoning_effort 同时发送安全（实测无推理爆炸，与 Kimi 不同）

GLM-5-Turbo（辅助模型）：
  - thinking 强制开启（thinking=disabled 被忽略，实测确认）
  - reasoning_effort 被服务端完全忽略（max/xhigh/high/medium/minimal/none
    均无效，无单调关系，none 仍产生 rtok≈959）
  - 无法通过任何 API 参数关闭思考

=== reasoning_effort 映射（GLM-5.2 专属，插件内显式映射）===

  Hermes /reasoning   reasoning_config                    thinking   reasoning_effort
  ─────────────────────────────────────────────────────────────────────────────────────
  (空值)              None                                enabled    不发送（服务端默认）
  none                {"enabled": False}                  enabled    none（放弃思考）
  minimal             {"enabled":True,"effort":"minimal"} enabled    minimal（放弃思考）
  low                 {"enabled":True,"effort":"low"}     enabled    high（显式映射）
  medium              {"enabled":True,"effort":"medium"}  enabled    high（显式映射）
  high                {"enabled":True,"effort":"high"}    enabled    high
  xhigh               {"enabled":True,"effort":"xhigh"}   enabled    max（显式映射）

  注：_EFFORT_MAP 字典中还包含 "none"→"none" 和 "max"→"max" 条目作为防御性
  代码。经 Hermes parse_reasoning_effort() 转换后不可达（"none"→{"enabled":False}，
  "max"→不在 VALID_REASONING_EFFORTS 中），保留仅为防止非标准调用路径。

当官方 PR 合入后，删除此文件即可恢复使用内置版本。
"""

from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


# ── 模型识别 ──────────────────────────────────────────────────


def _is_glm_5_2(model: str | None) -> bool:
    """检测 GLM-5.2 的各种别名拼写。

    覆盖标准写法 glm-5.2 以及中转商使用的变体：
    glm-5-2、glm-5p2、z-ai/glm-5.2、accounts/fireworks/models/glm-5p2 等。
    """
    m = (model or "").strip().lower()
    if not m:
        return False
    return any(token in m for token in ("glm-5.2", "glm-5-2", "glm-5p2"))


def _is_glm_5_turbo(model: str | None) -> bool:
    """检测 GLM-5-Turbo 的各种别名拼写。"""
    m = (model or "").strip().lower()
    if not m:
        return False
    return "glm-5-turbo" in m


# ── GLM-5.2 reasoning_effort + thinking 映射 ──────────────────


def _glm_5_2_reasoning_extras(
    reasoning_config: dict | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """将 Hermes reasoning 配置映射到 GLM-5.2 原生参数。

    返回 (extra_body_additions, top_level_kwargs)：
      - extra_body: thinking 对象（始终 enabled，GLM-5.2 强制思考）
      - top_level: reasoning_effort 字符串（控制思考深度和开关）

    GLM-5.2 是强制思考模型，thinking=disabled 被服务端忽略（2026-06-29 实测：
    rtok=5907≈正常值）。唯一的思考控制手段是 reasoning_effort：
      none/minimal → 放弃思考（实测 reasoning_tokens=0，6 次确认）
      low/medium   → 服务端映射为 high（官方文档声明）
      xhigh        → 服务端映射为 max（官方文档声明）

    本插件显式完成映射（不依赖服务端），便于在 request dump 中直接确认结果。
    """
    extra_body: dict[str, Any] = {}
    top_level: dict[str, Any] = {}

    # thinking 始终 enabled（GLM-5.2 强制思考，disabled 被忽略）
    extra_body["thinking"] = {"type": "enabled"}

    # 无配置 → 只发 thinking，让服务端选默认深度
    if not isinstance(reasoning_config, dict):
        return extra_body, top_level

    # 显式禁用推理 → reasoning_effort=none（不是 thinking=disabled）
    if reasoning_config.get("enabled") is False:
        top_level["reasoning_effort"] = "none"
        return extra_body, top_level

    effort = (reasoning_config.get("effort") or "").strip().lower()

    # 启用但未指定 effort → 只发 thinking，服务端默认深度
    if not effort:
        return extra_body, top_level

    # 显式映射（便于在 dump 中确认，不依赖服务端映射）
    _EFFORT_MAP = {
        "none": "none",        # 放弃思考
        "minimal": "minimal",  # 放弃思考
        "low": "high",         # low→high
        "medium": "high",      # medium→high
        "high": "high",
        "xhigh": "max",        # xhigh→max
        "max": "max",
    }

    mapped = _EFFORT_MAP.get(effort)
    if mapped:
        top_level["reasoning_effort"] = mapped
    # 未知 effort → 不发 reasoning_effort，服务端默认深度

    return extra_body, top_level


# ── GLM-5-Turbo thinking 映射 ──────────────────────────────────


def _glm_5_turbo_thinking_extras(
    reasoning_config: dict | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """将 Hermes reasoning 配置映射到 GLM-5-Turbo thinking 参数。

    返回 (extra_body_additions, top_level_kwargs)：
      - extra_body: thinking 对象（始终 enabled）
      - top_level: 空

    GLM-5-Turbo 是强制思考模型（2026-06-29 实测确认）：
      - thinking=disabled 被忽略（Q2: rtok=1007≈enabled 1167）
      - reasoning_effort 被完全忽略（max/xhigh/high/medium/minimal/none
        均无效，无单调关系，none 仍产生 rtok≈959）
    无论 reasoning_config 如何设置，始终发送 thinking=enabled，
    所有请求都会产生 reasoning_content。
    """
    extra_body: dict[str, Any] = {}
    top_level: dict[str, Any] = {}

    # thinking 始终 enabled（GLM-5-Turbo 强制思考，无法关闭）
    extra_body["thinking"] = {"type": "enabled"}

    return extra_body, top_level


# ── ZaiProfile ────────────────────────────────────────────────


class ZaiProfile(ProviderProfile):
    """Z.AI / GLM — GLM-5.2 reasoning_effort + thinking + tool_stream。"""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """构建 Z.AI 专有的 API 参数。

        对 GLM-5.2：
          - 始终发送 thinking=enabled（强制思考，disabled 被忽略）
          - 发送顶层 reasoning_effort 控制思考深度和开关
        对 GLM-5-Turbo：
          - 始终发送 thinking=enabled（强制思考，无法关闭）
          - 不发送 reasoning_effort（被服务端完全忽略）
        对所有 Z.AI 模型：
          - 发送 tool_stream=true 防止 30 秒空闲超时
          （tool_stream 在无工具调用时被服务端忽略，始终发送是安全的）
        """
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        # 延迟应用 reasoning_pad monkey-patch（首次 API 请求时触发）。
        # 不能在模块级别调用，否则会通过 run_agent → model_tools →
        # tools.registry → tools.approval 导入链在 main() 之前冻结
        # _YOLO_MODE_FROZEN，导致 hermes --yolo 审批旁路失效。
        _apply_reasoning_pad_patch()

        if _is_glm_5_2(model):
            # GLM-5.2: thinking + reasoning_effort
            extra_body, top_level = _glm_5_2_reasoning_extras(reasoning_config)
        elif _is_glm_5_turbo(model):
            # GLM-5-Turbo: thinking only（不支持 reasoning_effort）
            extra_body, top_level = _glm_5_turbo_thinking_extras(reasoning_config)

        # 所有 Z.AI 模型：tool_stream 防止服务端 30 秒空闲超时 (#24915)
        # 无法从 profile API 获知请求中是否携带 tools，
        # 但 tool_stream=true 在无工具时是 no-op，始终发送安全。
        extra_body["tool_stream"] = True

        return extra_body, top_level


# ── 注册 ──────────────────────────────────────────────────────

zai = ZaiProfile(
    name="zai",
    aliases=("glm", "z-ai", "z.ai", "zhipu"),
    env_vars=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
    display_name="Z.AI (GLM)",
    description="Z.AI / GLM — Zhipu AI models（用户插件覆盖版）",
    signup_url="https://z.ai/",
    # 不设 fallback_models — 回退到 _PROVIDER_MODELS["zai"] 静态列表
    # （models.py:2443），随 hermes update 自动更新。
    base_url="https://api.z.ai/api/paas/v4",
    default_aux_model="glm-5-turbo",
)

register_provider(zai)


# ── reasoning_content 回传保持 (#51195 方案) ──────────────────
#
# _needs_thinking_reasoning_pad() 硬编码在 run_agent.py 中，无法通过
# ProviderProfile API 覆盖。在 build_api_kwargs_extras()（首次 API 请求）
# 中对 AIAgent 做 monkey-patch，为 Z.AI/GLM 添加 reasoning_content echo-back 检测。
# 不能在模块级别调用，否则会通过 run_agent → model_tools → tools.registry
# → tools.approval 导入链在 main() 之前冻结 _YOLO_MODE_FROZEN（#60328）。
#
# 原理：GLM 在工具调用回合要求 reasoning_content 被回传，缺失时可能
# 导致服务端不稳定（表现为限流类错误而非清晰的 schema 报错）。
#
# 安全性说明：
#   - 仅在原始检测结果为 False 时追加 GLM 检测，不修改既有行为
#   - GLM 检测仅基于 provider 名和 base_url，与 #51195 逻辑一致
#   - 等官方合入 #51195 后，此 monkey-patch 段可移除。
#     reasoning_effort 映射（#51108）和 tool_stream（#24915）通过
#     ProviderProfile API 实现，需单独评估是否已被官方覆盖。


_patch_applied = False


def _apply_reasoning_pad_patch() -> None:
    """为 AIAgent._needs_thinking_reasoning_pad 追加 GLM 检测。

    幂等：通过 _patch_applied 标志保证只执行一次，可在运行期安全重复调用。
    """
    global _patch_applied
    if _patch_applied:
        return
    try:
        from run_agent import AIAgent
        from utils import base_url_host_matches

        _original_method = AIAgent._needs_thinking_reasoning_pad

        def _patched_method(self) -> bool:
            # 先走原始逻辑（含缓存），命中则直接返回
            if _original_method(self):
                return True
            # 原始逻辑未命中 → 检查是否为 Z.AI/GLM 原生路由
            provider = (getattr(self, "provider", "") or "").lower()
            if provider in {"zai", "glm", "z-ai", "z.ai", "zhipu"}:
                return True
            base_url = getattr(self, "base_url", "") or ""
            if base_url_host_matches(base_url, "api.z.ai"):
                return True
            if base_url_host_matches(base_url, "open.bigmodel.cn"):
                return True
            return False

        AIAgent._needs_thinking_reasoning_pad = _patched_method
        _patch_applied = True
    except Exception:
        # 导入失败时静默跳过 —— provider profile 仍正常工作，
        # 仅缺少 reasoning_content 回传保持功能。
        import logging
        logging.getLogger("hermes.plugins.zai").debug(
            "reasoning_pad patch skipped", exc_info=True
        )
