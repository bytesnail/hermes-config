"""Kimi / Moonshot provider profile — 用户插件覆盖版本。

此文件放在 $HERMES_HOME/plugins/model-providers/kimi-coding/__init__.py，
通过 Hermes 的 last-writer-wins 机制自动覆盖内置同名 profile。
hermes update 不会影响此文件（它在 git 仓库之外）。

=== 背景 ===

sk-kimi- 前缀的 key 默认路由到 api.kimi.com/coding（Anthropic Messages 协议）。
Hermes 在 Anthropic 传输模式下对 Kimi 端点跳过 thinking 参数
（anthropic_adapter.py 的 not _is_kimi_coding 条件），导致：
  - thinking 从未启用
  - reasoning_effort 从未发送
  - 响应中无 reasoning_content

通过配合 .env 中 KIMI_BASE_URL=https://api.kimi.com/coding/v1 和
config.yaml 中 model.api_mode: chat_completions，切换到 OpenAI 协议。
本插件在此前提下为 chat_completions 传输注入 thinking / reasoning_effort 参数。

=== 前置条件（缺一不可）===

  1. ~/.hermes/.env:
       KIMI_BASE_URL=https://api.kimi.com/coding/v1

  2. ~/.hermes/config.yaml model 段:
       api_mode: chat_completions

  3. 本文件（覆盖内置 KimiProfile 的 effort 映射缺口）

=== thinking / reasoning_effort 行为（2026-06-28 API 实测验证）===

Kimi Coding Plan OpenAI 端点 (api.kimi.com/coding/v1/chat/completions)：
  - thinking 默认开启（不带参数时 reasoning_content 有值）
  - thinking=disabled 可关闭（reasoning_content 消失）
  - reasoning_effort 支持 4 档：minimal / low / medium / high
  - reasoning_effort=none → HTTP 400（不支持）
  - reasoning_effort=xhigh → HTTP 400（不支持）
  - reasoning_effort=minimal → HTTP 200（内置 KimiProfile 未映射，本插件补全）

=== reasoning_effort 映射 ===

  Hermes config      → API 实际发送
  ──────────────────────────────────────────────
  xhigh              → reasoning_effort=high   (API 最高档，不支持 xhigh)
  high               → reasoning_effort=high
  medium             → reasoning_effort=medium
  low                → reasoning_effort=low
  minimal            → reasoning_effort=minimal
  (空值/未设置)       → thinking=enabled        (服务端默认深度)
  none               → thinking=disabled       (关闭思考)
  enabled=False      → thinking=disabled       (关闭思考)

XOR 设计：发送 reasoning_effort 时不发 thinking（与内置 KimiProfile 一致），
反之亦然。虽然实测同时发不报错，但保持 XOR 更安全。

=== reasoning_content 回传保持 ===

不需要 monkey-patch。Hermes 原生 _needs_kimi_tool_reasoning() 已匹配
provider in {"kimi-coding", "kimi-coding-cn"} 和 base_url 含 api.kimi.com、
moonshot.ai、moonshot.cn。

=== 不需要 tool_stream ===

Kimi Coding Plan 端点没有 Z.AI 那样的 30 秒空闲超时问题，无需发送。

=== 与内置 KimiProfile 的字段差异 ===

  字段                 内置值                              本插件值
  ─────────────────────────────────────────────────────────────────────
  default_max_tokens   32000                               None（服务端决定）
  default_headers      {"User-Agent": "hermes-agent/1.0"}  {}（api.kimi.com 路径被覆盖）
  default_aux_model    "kimi-k2-turbo-preview"             "kimi-for-coding"

=== 防御性代码 ===

effort == "none" 检查在正常运行中不可达：Hermes parse_reasoning_effort("none")
返回 {"enabled": False}，在 enabled is False 分支提前返回。保留仅为防止
非标准调用路径。

当官方内置 KimiProfile 补全 effort 映射后，删除此文件即可恢复内置版本。
"""

from __future__ import annotations

from typing import Any

from providers import register_provider
from providers.base import OMIT_TEMPERATURE, ProviderProfile


# ── effort 映射 ────────────────────────────────────────────────

# Hermes effort → Kimi API reasoning_effort
# API 实测支持的档位：minimal, low, medium, high
# API 不支持：none (400), xhigh (400)
_EFFORT_MAP: dict[str, str] = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",  # API 最高档为 high，xhigh 降级映射
}


class KimiProfile(ProviderProfile):
    """Kimi / Moonshot — thinking + reasoning_effort（用户插件覆盖版）。

    与内置 KimiProfile 的区别：
      - 补全 minimal → reasoning_effort=minimal 映射
        （内置版本未映射 minimal，回退为 thinking=enabled，丢失 effort 意图）
      - 补全 xhigh → reasoning_effort=high 映射
        （内置版本未映射 xhigh，回退为 thinking=enabled，丢失 effort 意图）

    设计保持 XOR：reasoning_effort 和 thinking 不同时发送。
    """

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """构建 Kimi 专有的 API 参数。

        返回 (extra_body_additions, top_level_kwargs)：
          - extra_body: thinking 对象（控制思维链开关）
          - top_level: reasoning_effort 字符串（控制思考深度）

        映射逻辑：
          无配置 / enabled=True 但无 effort → thinking=enabled（服务端默认深度）
          enabled=False / effort=none        → thinking=disabled（关闭思考）
          effort ∈ {minimal,low,medium,high} → reasoning_effort=<对应档位>
          effort=xhigh                       → reasoning_effort=high（API 最高档）
          未知 effort                        → thinking=enabled（安全回退）
        """
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        # 无配置 → thinking enabled，让服务端选默认深度
        if not isinstance(reasoning_config, dict):
            extra_body["thinking"] = {"type": "enabled"}
            return extra_body, top_level

        # 显式禁用推理
        if reasoning_config.get("enabled") is False:
            extra_body["thinking"] = {"type": "disabled"}
            return extra_body, top_level

        effort = (reasoning_config.get("effort") or "").strip().lower()

        # effort=none → 关闭思考
        if effort == "none":
            extra_body["thinking"] = {"type": "disabled"}
            return extra_body, top_level

        # enabled=True 但无 effort → thinking enabled，服务端默认深度
        if not effort:
            extra_body["thinking"] = {"type": "enabled"}
            return extra_body, top_level

        # 映射 effort 到 API 支持的档位
        mapped = _EFFORT_MAP.get(effort)
        if mapped:
            # XOR 设计：发 reasoning_effort 时不发 thinking
            top_level["reasoning_effort"] = mapped
        else:
            # 未知 effort 值 → 安全回退到 thinking=enabled
            extra_body["thinking"] = {"type": "enabled"}

        return extra_body, top_level


# ── 注册 ──────────────────────────────────────────────────────

# 与内置 KimiProfile 的配置保持一致，仅覆盖 build_api_kwargs_extras 逻辑。
# base_url 会被 _resolve_kimi_base_url() 根据 key 前缀和 KIMI_BASE_URL 覆盖。
# default_headers 会被 _apply_client_headers_for_base_url() 根据 api.kimi.com
# hostname 匹配覆盖为 claude-code/0.1.0。

kimi = KimiProfile(
    name="kimi-coding",
    aliases=("kimi", "moonshot", "kimi-for-coding"),
    env_vars=("KIMI_API_KEY", "KIMI_CODING_API_KEY"),
    display_name="Kimi / Moonshot",
    description="Kimi / Moonshot — Coding Plan & Moonshot API（用户插件覆盖版）",
    signup_url="https://platform.kimi.ai/",
    # 不设 fallback_models — 回退到 _PROVIDER_MODELS["kimi-coding"] 静态列表
    # （models.py:2443），随 hermes update 自动更新。
    base_url="https://api.moonshot.ai/v1",
    fixed_temperature=OMIT_TEMPERATURE,
    default_aux_model="kimi-for-coding",
)

kimi_cn = KimiProfile(
    name="kimi-coding-cn",
    aliases=("kimi-cn", "moonshot-cn"),
    env_vars=("KIMI_CN_API_KEY",),
    display_name="Kimi / Moonshot (China)",
    description="Kimi / Moonshot China — Domestic direct API（用户插件覆盖版）",
    signup_url="https://platform.moonshot.cn/",
    # 不设 fallback_models — 回退到 _PROVIDER_MODELS["kimi-coding-cn"] 静态列表
    # （models.py:2443），随 hermes update 自动更新。
    base_url="https://api.moonshot.cn/v1",
    fixed_temperature=OMIT_TEMPERATURE,
    default_aux_model="kimi-for-coding",
)

register_provider(kimi)
register_provider(kimi_cn)
