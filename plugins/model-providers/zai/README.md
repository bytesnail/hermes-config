# ZAI / GLM Provider Plugin — 参考文档

## 1. 概述

此目录下的 `__init__.py` 是 Hermes 用户插件，通过 last-writer-wins 机制
覆盖内置 `zai` provider profile。解决 GLM-5.2 / GLM-5-Turbo 的 thinking /
reasoning_effort / tool_stream / reasoning_content 回传等参数未被正确发送的问题。

文件在 git 仓库之外（`$HERMES_HOME/plugins/`），`hermes update` 不受影响。

---

## 2. 问题背景

Hermes 的 `_supports_reasoning_extra_body()` 只对特定 provider/model
返回 True（Nous Portal、GitHub Models、LM Studio、OpenRouter 上的部分模型）。
Z.AI（`open.bigmodel.cn` / `api.z.ai`）不匹配任何条件。

v0.18.0（2026-07-01）起内置 zai profile 有简单的 thinking 开关。PR #58884
于 2026-07-05 合入（commit a6079dd35），内置新增了 reasoning_effort 映射，
但存在两个关键缺陷（实测确认）：

- `enabled=False`（`/reasoning none`）：内置发送 `thinking=disabled`，
  GLM-5.2 服务端忽略此参数（实测 rtok=5907≈正常值），思考无法关闭。
  本插件改发 `reasoning_effort=none`（实测 rtok=0，6 次确认）。
- `effort=minimal`：内置映射为 `reasoning_effort=high`（代码注释
  "all clamp to high"），但实测 `minimal` 是独立档位——发送后 rtok=0
  （放弃思考），`high` 则保持思考。映射方向完全错误。

此外仍完全缺失：

- `tool_stream` 参数 — 防止 Z.AI 30 秒空闲超时，内置不发送（#24915 仍 Open）
- `reasoning_content` echo-back — 工具调用回合回传，内置
  `_needs_thinking_reasoning_pad()` 不含 GLM 检测（#51195 仍 Open）

---

## 3. 与内置 profile 的差异清单

| 字段 | 内置 profile | 本插件 | 变更理由 |
|------|-------------|--------|----------|
| `build_api_kwargs_extras()` | thinking 开关 + reasoning_effort（#58884 合入），但 enabled=False/minimal 映射有缺陷，无 tool_stream | 正确的 reasoning_effort 映射 + thinking + tool_stream | 修正映射缺陷 + 补全缺失参数 |
| `fallback_models` | `("glm-5.2", "glm-5", "glm-4-9b")` | 不设置（回退 `_PROVIDER_MODELS["zai"]`，8 个模型） | 内置列表含过时 glm-4-9b 且不完整；回退到静态列表随 update 自动更新 |
| `default_aux_model` | `"glm-4.5-flash"` | `"glm-5-turbo"` | 更适合辅助任务 |
| `description` | `"Z.AI / GLM — Zhipu AI models"` | 加"（用户插件覆盖版）"后缀 | 标识 |
| monkey-patch | 无 | `_needs_thinking_reasoning_pad()` 追加 GLM 检测 | reasoning_content 回传保持 |
| `base_url` | `https://api.z.ai/api/paas/v4` | 同 | 不变 |
| `default_max_tokens` | None | None | 不变 |
| `fixed_temperature` | None | None | 不变 |
| `default_headers` | {} | {} | 不变 |
| `env_vars` / `aliases` / `display_name` | — | 同 | 不变 |

> **last-writer-wins 注意**：用户插件完全替换内置 profile，不是叠加。
> 省略某个字段不会回退到内置值，而是用 ProviderProfile 基类的默认值。
> 因此本插件显式设置了所有需要保留的字段。

---

## 4. 功能详解

综合三个 PR 的方案：

| 功能 | 来源 PR | 发送位置 | 适用模型 | 说明 |
|------|---------|----------|----------|------|
| reasoning_effort 映射 | #51108 | 顶层 api_kwargs | GLM-5.2 | 插件内显式映射，控制思考深度和开关 |
| thinking=enabled | #51108 | extra_body | GLM-5.2 + GLM-5-Turbo | 强制思考模型，disabled 被忽略 |
| tool_stream=true | #24915 | extra_body | 所有 Z.AI 模型 | 防 30 秒空闲超时，无工具时 no-op |
| reasoning_content echo-back | #51195 | monkey-patch | 所有 Z.AI/GLM 路由 | 工具调用回合回传 reasoning_content |

### 4.1 GLM-5.2（主模型）

GLM-5.2 是强制思考模型：`thinking=disabled` 被服务端忽略（2026-06-29 实测
rtok=5907≈正常值）。`reasoning_effort` 是唯一的思考控制手段。

| Hermes /reasoning | reasoning_config | thinking | reasoning_effort |
|-------------------|------------------|----------|-------------------|
| (空值/未设置) | None | enabled | 不发送（服务端默认深度） |
| none | {"enabled": False} | enabled | **none（放弃思考）** |
| minimal | {"enabled":true,"effort":"minimal"} | enabled | **minimal（放弃思考）** |
| low | {"enabled":true,"effort":"low"} | enabled | high（low→high 显式映射） |
| medium | {"enabled":true,"effort":"medium"} | enabled | high（medium→high 显式映射） |
| high | {"enabled":true,"effort":"high"} | enabled | high |
| xhigh | {"enabled":true,"effort":"xhigh"} | enabled | max（xhigh→max 显式映射） |

要点：

- **thinking 始终 enabled**：GLM-5.2 强制思考，disabled 被忽略。发送 enabled
  与官方文档示例一致，且 thinking + reasoning_effort 同时发送安全（实测无推理爆炸）。
- **关闭思考的唯一方式是 reasoning_effort=none 或 minimal**：
  实测确认 reasoning_tokens=0（3 难度 × 2 参数共 6 次）。thinking=disabled 无效。
- **插件内显式映射**：low→high、medium→high、xhigh→max 在插件代码中完成，
  而非依赖服务端映射。便于在 request dump 中直接确认最终发送的值。
  （官方文档声明服务端也会做相同映射，但显式映射更可观测。）
- Hermes 没有 "max" 档位（`VALID_REASONING_EFFORTS` 不含 max），
  通过 `/reasoning xhigh` 或 `agent.reasoning_effort: xhigh` 触发 GLM 的 max。
- **`_EFFORT_MAP` 中的 "none" 和 "max" 条目是防御性代码**：经 Hermes 的
  `parse_reasoning_effort()` 转换后不可达（"none"→{"enabled":False}，
  "max"→不在 `VALID_REASONING_EFFORTS` 中），保留仅为防止非标准调用路径。

### 4.2 GLM-5-Turbo（辅助模型）

GLM-5-Turbo 是强制思考模型（2026-06-29 实测确认）。`thinking=disabled`
被忽略，`reasoning_effort` 被完全忽略。无法通过任何 API 参数关闭思考。

| reasoning_config | thinking | reasoning_effort | 实际效果 |
|------------------|----------|-------------------|---------|
| 任何值 | enabled | 不发送 | 始终产生 reasoning_content |

要点：

- `thinking=disabled` 被服务端忽略（实测：Q2 rtok=1007 vs enabled rtok=1167，无差异）。
- `reasoning_effort` 被完全忽略（实测 max/xhigh/high/medium/minimal/none
  在 Q2 上 rtok 范围 810-1349，无单调关系，none 仍产生 rtok≈959）。
- 插件始终发送 `thinking=enabled`，忽略所有 reasoning_config 参数。
- 之前认为"thinking=disabled 可关闭思考"的结论是假阳性：
  极简问题（3+5=?）本身的 reasoning_tokens 仅 60-80，被误判为"已关闭"。

---

## 5. 各配置项说明

### fallback_models
- 未设置（默认空值），回退到 `_PROVIDER_MODELS["zai"]` 静态列表（8 个模型）
- 内置 profile 设为 `("glm-5.2", "glm-5", "glm-4-9b")`——含过时模型 glm-4-9b 且不完整
- 不设的好处：随 hermes update 自动同步 `_PROVIDER_MODELS` 更新

### default_max_tokens
- 未设置（None），由 Z.AI 服务端决定默认行为
- 当 profile.default_max_tokens=None 且 config.yaml 未设 max_tokens 时
  → 请求中不携带 max_tokens 参数 → 服务端用自己的默认值
- PR #51195 曾建议设 8192 防止推理 token 耗尽输出预算，但用户选择不设上限

### default_aux_model
- 设为 "glm-5-turbo"（内置为 "glm-4.5-flash"）
- 用于辅助任务（上下文压缩、视觉分析、会话搜索摘要）
- 未设置时回退到 `_API_KEY_PROVIDER_AUX_MODELS_FALLBACK["zai"]` = "glm-4.5-flash"

### base_url
- profile 中设为 `https://api.z.ai/api/paas/v4`（国际版默认）
- config.yaml 的 `model.base_url` 始终优先于 profile.base_url
- 用户的中国版 coding plan（`open.bigmodel.cn`）不受影响

### tool_stream
- Z.AI 服务端有 30 秒空闲超时
- 不设置时，工具调用参数一次性返回，思考期间无输出可能触发超时
- 设置为 true 后，参数增量流式返回，避免超时
- 无工具调用时被服务端忽略（no-op），始终发送安全

---

## 6. API 实测数据（2026-06-29）

### 6.1 GLM-5.2 thinking + reasoning_effort 对比测试

测试条件：
- 端点：`https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`
- model：glm-5.2，max_tokens=8192，stream=false
- 三种难度问题，同问题内并行发送

#### reasoning_content 长度对比（chars）

| 问题 | both_max | both_high | thinking_only | effort_max_only | effort_high_only | both_minimal | effort_minimal | effort_none | thinking_disabled |
|------|---------:|----------:|-------------:|----------------:|-----------------:|-------------:|---------------:|------------:|------------------:|
| Q1 组合计数 | 超时 | 10146 | 超时 | 16011 | 13373 | **0** | **0** | **0** | 13912 |
| Q2 逻辑推理 | 7138 | 4170 | 6574 | 10789 | 3721 | **0** | **0** | **0** | 6865 |
| Q3 约束优化 | 19660 | 8654 | 19302 | 超时 | 8696 | **0** | **0** | **0** | 17797 |

#### 关键发现

1. **thinking=disabled 被忽略**：Q1 rtok=6680、Q2 rtok=2143、Q3 rtok=5907，
   与正常思考模式无差异。GLM-5.2 强制思考。
2. **reasoning_effort=none/minimal 正确关闭思考**：6 次测试全部 rtok=0，
   覆盖三种难度。这是关闭思考的唯一方式。
3. **thinking + reasoning_effort 同时发送安全**：both_high vs effort_high_only
   在 Q2/Q3 上推理深度几乎一致，无 Kimi 那样的爆炸问题。
4. **effort_max 可能导致 max_tokens 耗尽**：Q1 effort_max_only rtok=8187/8192，
   content=0。thinking_only 和 both_max 在 Q1 上也超时（可能同样耗尽）。

### 6.2 GLM-5-Turbo 测试

#### thinking=disabled 无效性验证

| 问题 | combo | reasoning_tokens | 说明 |
|------|-------|----------------:|------|
| Q2 逻辑推理 | thinking_enabled | 1167 | 正常思考 |
| Q2 逻辑推理 | thinking_disabled | 1007 | disabled 被忽略 |
| 3+5=? | thinking_enabled | 62 | 正常思考 |
| 3+5=? | thinking_disabled | 65 | disabled 被忽略 |
| 3+5=? | effort_none | 68 | effort=none 也被忽略 |

#### reasoning_effort 各值对推理深度的影响（Q2 逻辑推理题）

| reasoning_effort | reasoning_tokens | 说明 |
|------------------|----------------:|------|
| max | 1349 | |
| xhigh | 810 | 比 high 还低 |
| high | 1131 | |
| medium | 1192 | 比 high 高 |
| minimal | 1298 | 比 high 高 |
| none | 959 | 应为 0，实际近千 |
| no_params(prior) | 3742 | 不带参数反而最高 |

结论：rtok 范围 810-1349（比率 1.7x），无单调关系，none!=0。
**reasoning_effort 对 GLM-5-Turbo 完全不生效**。
GLM-5-Turbo 是强制思考模型，无法通过任何 API 参数关闭思考。

---

## 7. 兼容性

### 中国版 vs 国际版 Coding Plan

| 路径 | 中国版 | 国际版 |
|------|--------|--------|
| base_url | open.bigmodel.cn/api/coding/paas/v4 | api.z.ai/api/paas/v4 |
| profile 加载 | ✓ provider=zai 命中 | ✓ provider=zai 命中 |
| reasoning_effort | ✓ _is_glm_5_2 检测模型名 | ✓ 同上 |
| thinking | ✓ GLM-5.2 + GLM-5-Turbo | ✓ 同上 |
| tool_stream | ✓ 所有 Z.AI 模型 | ✓ 同上 |
| reasoning_content echo-back | ✓ base_url 匹配 open.bigmodel.cn | ✓ base_url 匹配 api.z.ai |

两条路径完全兼容。

---

## 8. 验证方法

### 8.1 确认插件已加载

```bash
# 启动 hermes 后，检查 profile 类型
HERMES_DUMP_REQUESTS=1 hermes
```

### 8.2 检查 wire 参数

```bash
# 发一条消息后查看 dump
ls -t ~/.hermes/sessions/request_dump_*.json | head -1 | \
  xargs python3 -m json.tool | grep -A2 "reasoning_effort\|thinking\|tool_stream"
```

预期输出（GLM-5.2 + medium）：
```json
"reasoning_effort": "high"
"thinking": {"type": "enabled"}
"tool_stream": true
```

### 8.3 切换 effort 对比

```bash
# 在 hermes 会话中
/reasoning xhigh    # → dump 应显示 reasoning_effort: "max", thinking: {"type":"enabled"}
/reasoning medium   # → dump 应显示 reasoning_effort: "high", thinking: {"type":"enabled"}
/reasoning minimal  # → dump 应显示 reasoning_effort: "minimal", thinking: {"type":"enabled"}
/reasoning none     # → dump 应显示 reasoning_effort: "none", thinking: {"type":"enabled"}
```

注意：none 和 minimal 通过 reasoning_effort 关闭思考（不是 thinking=disabled）。
GLM-5.2 的 thinking=disabled 被服务端忽略，必须用 reasoning_effort=none。

---

## 9. 插件生命周期

### 现在为什么需要此插件

内置 `zai` profile（v0.18.0 + #58884）已发送 thinking 开关和 reasoning_effort，
但 enabled=False / minimal 两个映射有缺陷（见 §2），且不发送 tool_stream，
不做 reasoning_content 回传保持。在官方补全这些缺陷前，此插件仍是必要的。

### 每次 `hermes update` 后检查

**步骤 1：内置 profile 的 reasoning_effort 映射是否正确**

#58884 合入后内置已有 reasoning_effort（`grep -c "reasoning_effort"` 返回 6），
不能仅凭存在性判断。需检查两个关键映射是否已修正：

```bash
# 检查 enabled=False 的处理：
#   缺陷版 → thinking=disabled（GLM-5.2 忽略，思考无法关闭）
#   正确版 → reasoning_effort=none
grep -A5 'enabled.*is False' \
  ~/.hermes/hermes-agent/plugins/model-providers/zai/__init__.py

# 检查 minimal 映射：
#   缺陷版 → reasoning_effort=high（错误，minimal 应放弃思考）
#   正确版 → reasoning_effort=minimal
grep -B2 -A2 'minimal' \
  ~/.hermes/hermes-agent/plugins/model-providers/zai/__init__.py
```

两个映射均已修正 → 进入步骤 2。
仍有缺陷 → 此插件仍需要，无需修改。

**步骤 2：对比官方实现是否等价或更优**

```bash
cat ~/.hermes/hermes-agent/plugins/model-providers/zai/__init__.py
```

关注：
- reasoning_effort 映射是否覆盖 max 档位
- 是否发送 thinking 参数
- 是否发送 tool_stream
- 是否处理 reasoning_content echo-back

```bash
grep "_needs_glm_tool_reasoning\|glm.*reasoning_pad\|zai.*reasoning" \
  ~/.hermes/hermes-agent/run_agent.py
```

**步骤 3：查 PR 合并状态**

```bash
# #58884 已合并，#51108 已 Closed
for pr in 58884 51108 24915 51195; do
  curl -s "https://api.github.com/repos/NousResearch/hermes-agent/pulls/$pr" \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'#$pr',d['state'],d.get('merged'))"
done
```

### 判定矩阵

| 内置实现情况 | 操作 |
|-------------|------|
| reasoning_effort 映射有缺陷 或 缺 tool_stream / echo-back | 保持插件不变 |
| reasoning_effort 映射正确，但缺 tool_stream / echo-back | 精简插件，仅保留差异部分 |
| 完整等价或更优 | 删除插件（见附录 B） |

---

## 附录 A. PR / Issue 索引

### 本插件参考的 PR

| PR | 作者 | 方案切入点 | 本插件采用的部分 |
|----|------|-----------|-----------------|
| #58884 | teknium1 | #51108 的 salvage，合并 v0.18.0 thinking 开关 | 已合并 2026-07-05（a6079dd35），但 enabled=False/minimal 映射有缺陷 |
| #51108 | teknium1 | provider profile (port kilocode) | reasoning_effort + thinking（已 Closed，被 #58884 salvage 替代） |
| #24915 | nibzard | transport 层综合修复 | tool_stream=true |
| #51195 | punksterlabs | reasoning_content + max_tokens | reasoning_content echo-back |

### 其他竞争 PR（未采用）

| PR | 作者 | 方案 | 未采用原因 |
|----|------|------|-----------|
| #46446 | potatogim | thinking.effort（effort 放在 thinking 内部） | 参数结构与官方 SDK 不符 |
| #48004 | kivo360 | reasoning_effort（不处理 max） | 不支持 max 档位 |
| #49355 | leriou | 声明式 reasoning_effort_max 字段 | 过度设计 |
| #50694 | izumi0uu | opencode-go 路径 | 不覆盖 zai 直连路径 |
| #16592 | vominh1919 | transport 层 is_zai 分支 | 与 profile 架构方向相悖 |
| #51426 | AMEOBIUS | config 驱动通用方案 | 不处理 max 映射 |

### 相关 Issue

| Issue | 描述 |
|-------|------|
| #16533 | ZAI 从不返回 reasoning_content（发了错误字段） |
| #50696 | GLM-5 reasoning 在直连 ZAI 路径被忽略 |
| #49279 | GLM-5.x reasoning 在 opencode-go 路径被忽略 |
| #15511 | 按模型自动匹配 reasoning_effort（跨模型方案） |

---

## 附录 B. 清理方式

当判定矩阵指示可以删除时：

```bash
rm -rf ~/.hermes/plugins/model-providers/zai/
```

下次 hermes 启动时自动使用内置 profile。
