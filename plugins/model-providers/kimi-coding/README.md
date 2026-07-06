# Kimi / Moonshot Provider Plugin — 参考文档

## 1. 概述

此目录下的 `__init__.py` 是 Hermes 用户插件，通过 last-writer-wins 机制
覆盖内置 `kimi-coding` provider profile。补全内置 KimiProfile 的
reasoning_effort 映射缺口（minimal / xhigh）。

文件在 git 仓库之外（`$HERMES_HOME/plugins/`），`hermes update` 不受影响。

**此插件需要配合两处配置变更才能生效**（见第 4 节）。

---

## 2. 问题背景

### 2.1 默认路由问题

sk-kimi- 前缀的 API key 被 Hermes 自动路由到 `api.kimi.com/coding`（无 /v1），
该 URL 匹配 `_detect_api_mode_for_url()` 的 Kimi 规则，被判定为
`anthropic_messages` 传输模式。

在 Anthropic 传输模式下：

- `agent/anthropic_adapter.py` 中 `_is_kimi_coding_family_endpoint()` 判定为 True 时 `not _is_kimi_coding` 条件跳过 thinking 参数
- `KimiProfile.build_api_kwargs_extras()` 是死代码（只对 chat_completions 生效）
- 结果：请求中无 thinking、无 reasoning_effort，模型不开启思考

### 2.2 内置 KimiProfile 的映射缺口

即使切换到 chat_completions 模式，内置 KimiProfile 只映射了 3 个 effort 档位：

```python
# 内置代码（kimi-coding/__init__.py:49）
if effort in {"low", "medium", "high"}:
    top_level["reasoning_effort"] = effort
else:
    extra_body["thinking"] = {"type": "enabled"}
```

未映射的档位：
- `minimal` → 回退为 thinking=enabled（丢失 effort 意图）
- `xhigh` → 回退为 thinking=enabled（丢失 effort 意图）

但 API 实测确认 `minimal` 是支持的（HTTP 200），只是内置代码未覆盖。

### 2.3 Anthropic vs OpenAI 协议对比

选择 OpenAI 协议（chat_completions）而非 Anthropic 协议的核心原因：

| 测试 | Anthropic 端点 (/coding/v1/messages) | OpenAI 端点 (/coding/v1/chat/completions) |
|------|--------------------------------------|-------------------------------------------|
| 无参数 | thinking 默认**关闭** | thinking 默认**开启** |
| thinking=disabled | 关闭（同上） | 关闭 |
| thinking=enabled | 开启（需显式） | 开启（默认） |
| effort=high 单独发 | **无效**（无 thinking 块） | 有效（触发推理） |

Anthropic 端点的 thinking 默认关闭，且 reasoning_effort 单独发送不生效。
OpenAI 端点默认开启思考，且 reasoning_effort 可独立控制推理深度。

### 2.4 models 端点 404

`api.kimi.com/coding/models` 返回 404，正确路径是 `api.kimi.com/coding/v1/models`。
base_url 缺少 /v1 导致 /model 切换时产生 warning。

---

## 3. 与内置 profile 的差异清单

| 字段 | 内置 KimiProfile | 本插件 | 变更理由 |
|------|-----------------|--------|----------|
| `build_api_kwargs_extras()` | 映射 {low,medium,high}，其余回退 thinking | 映射 {minimal,low,medium,high} + xhigh→high | 补全 minimal/xhigh 缺口 |
| `default_max_tokens` | 32000 | None（不设置） | 不设上限，让服务端管理输出长度（见 §7） |
| `default_headers` | {"User-Agent": "hermes-agent/1.0"} | {}（不设置） | api.kimi.com 路径下被 hostname 匹配覆盖，设置无效（见 §7） |
| `default_aux_model` | "kimi-k2-turbo-preview" | "kimi-for-coding" | 统一入口别名，更稳定 |
| `fallback_models` | 未设置（回退 `_PROVIDER_MODELS`） | 同 | 不变 |
| `base_url` | `https://api.moonshot.ai/v1` | 同 | 不变（运行时被 `_resolve_kimi_base_url()` 覆盖） |
| `fixed_temperature` | OMIT_TEMPERATURE | 同 | 不变 |
| `env_vars` / `aliases` / `display_name` | — | 同 | 不变 |

> **last-writer-wins 注意**：用户插件完全替换内置 profile，不是叠加。
> 省略某个字段不会回退到内置值，而是用 ProviderProfile 基类的默认值。
> 本插件有意省略 `default_max_tokens` 和 `default_headers`（见 §7 说明）。

---

## 4. 配置要求（前置条件）

本插件需要配合以下配置变更，三者缺一不可：

### 4.1 ~/.hermes/.env

```
KIMI_BASE_URL=https://api.kimi.com/coding/v1
```

作用：覆盖 sk-kimi- key 默认路由到 `/coding`（无 /v1）的行为。
OpenAI SDK 会在 base_url 后追加 `/chat/completions`，所以必须是 `/coding/v1`
才能拼出正确的 URL。

### 4.2 ~/.hermes/config.yaml

```yaml
model:
  api_mode: chat_completions
```

作用：覆盖 Hermes 对 `api.kimi.com` + `/coding` 的自动 anthropic_messages 检测。
显式 api_mode 在 `_provider_supports_explicit_api_mode()` 检查通过时优先于自动检测。

### 4.3 本插件文件

```
~/.hermes/plugins/model-providers/kimi-coding/__init__.py
```

作用：补全 effort 映射缺口。

### 4.4 三者的关系

| 只改 | 结果 |
|------|------|
| 4.1 + 4.2（无插件） | thinking/reasoning_effort 能发，但 xhigh/minimal 回退到服务端默认深度 |
| 4.1 + 4.3（无 api_mode） | KimiProfile.build_api_kwargs_extras() 不被调用（走 Anthropic 传输） |
| 4.2 + 4.3（无 KIMI_BASE_URL） | api_mode 对了但 URL 缺 /v1 → inference 404 + models 404 |

---

## 5. reasoning_effort 映射 + XOR 设计

### 5.1 与内置 KimiProfile 的对比

| Hermes effort | 内置 KimiProfile | 本插件 | API 实测 |
|---------------|-----------------|--------|----------|
| minimal | thinking=enabled（回退） | **reasoning_effort=minimal** | 200 ✓ |
| low | reasoning_effort=low | reasoning_effort=low | 200 ✓ |
| medium | reasoning_effort=medium | reasoning_effort=medium | 200 ✓ |
| high | reasoning_effort=high | reasoning_effort=high | 200 ✓ |
| xhigh | thinking=enabled（回退） | **reasoning_effort=high** | 200 ✓（xhigh 本身 400） |
| (空值) | thinking=enabled | thinking=enabled | 200 ✓ |
| none | thinking=disabled | thinking=disabled | 200 ✓ |
| enabled=False | thinking=disabled | thinking=disabled | 200 ✓ |

### 5.2 XOR 设计

发送 reasoning_effort 时不发 thinking，反之亦然。与内置 KimiProfile 保持一致。

同时发不报 HTTP 400，但有严重的副作用——thinking=enabled 会在部分问题上
引发推理内容暴增，导致 max_tokens 耗尽、模型无法输出正文答案。
详见 §6.3 对比测试。

**与 zai/deepseek 的差异**：zai 插件（GLM-5.2）和 deepseek 内置 profile
都同时发 thinking + reasoning_effort，且测试确认安全（无推理爆炸）。
这是因为它们各自 API 的语义不同——GLM-5.2 强制思考且 thinking=disabled
被忽略，发送 enabled 只是无害的形式参数；DeepSeek V4 需要它避免
reasoning_content 回传陷阱。Kimi 则不同：thinking.type 是独立的深度旋钮，
与 reasoning_effort 叠加会导致不可预测的推理暴增。

---

## 6. API 实测数据

### 6.1 基础参数测试（2026-06-28）

- 端点：`https://api.kimi.com/coding/v1/chat/completions`（OpenAI 协议）
- Key：sk-kimi- 前缀（Kimi Coding Plan）

| 测试 | 参数 | HTTP | reasoning_content | completion_tokens |
|------|------|------|-------------------|-------------------|
| T1 不带参数 | (无) | 200 | 有（166 chars） | 77 |
| T2 thinking=disabled | thinking=disabled | 200 | **无** | **9** |
| T3 thinking=enabled | thinking=enabled | 200 | 有（100 chars） | 25 |
| T4 effort=high | reasoning_effort=high | 200 | 有（160 chars） | 89 |
| T5 effort=low | reasoning_effort=low | 200 | 有（45 chars） | 45 |
| T6 effort=minimal | reasoning_effort=minimal | 200 | 有（115 chars） | 115 |
| T7 effort=medium | reasoning_effort=medium | 200 | 有（100 chars） | 100 |
| T8 thinking+effort | 两者同时发 | 200 | 有（24 chars） | 24 |
| T9 effort=none | reasoning_effort=none | **400** | — | — |
| T10 effort=xhigh | reasoning_effort=xhigh | **400** | — | — |

> ⚠ T8 在简单算术题（"3+5=?"）上测得，thinking+effort 同时发时 reasoning
> 仅 24 chars。但此结论不可推广——§6.3 的多难度对比测试显示，在中高难度
> 问题上同时发会导致推理内容暴增到 18k-22k chars，远超单独发 reasoning_effort
> 的 11k-13k。T8 的低值是简单问题的特例，不代表通用行为。

T9/T10 报错信息：
```
Unsupported value: 'reasoning_effort' does not support 'none' with this model.
Supported values are: 'minimal', 'low', 'medium', and 'high'.
```

### 6.2 复杂问题推理深度对比

| 测试 | reasoning_chars | 说明 |
|------|----------------|------|
| thinking=disabled | 0 | 完全无推理 |
| effort=minimal | 1105 | 最简洁推理 |
| (无参数/默认) | 1233 | 服务端默认深度 |
| effort=medium | 1923 | 中等推理 |
| effort=high | 2042 | 最深度推理 |

### 6.3 XOR vs 同时发送：多难度对比测试（2026-06-29）

验证 thinking=enabled + reasoning_effort 同时发送是否优于 XOR（仅发 reasoning_effort）。

测试条件：
- 端点：`https://api.kimi.com/coding/v1/chat/completions`
- model：kimi-k2.7-code，max_tokens=8192，stream=false
- 三种难度问题 × 四种参数组合，同问题内并行发送

#### reasoning_content 长度对比（chars）

| 问题 | effort_only(high) | both(thinking+effort) | thinking_only | effort_low |
|------|------------------:|---------------------:|--------------:|-----------:|
| Q1 组合计数 | 11,702 | 18,827 | 22,087 | 9,581 |
| Q2 逻辑推理 | 13,122 | 10,405 | 5,552 | 10,426 |
| Q3 约束优化 | 超时(>120s) | 超时(>120s) | 超时(>120s) | 19,257 |

#### 完成状态（content_chars / completion_tokens）

| 问题 | effort_only(high) | both(thinking+effort) | thinking_only | effort_low |
|------|------------------:|---------------------:|--------------:|-----------:|
| Q1 组合计数 | 944 / 4541 | **0 / 8192** | **0 / 8192** | 962 / 3841 |
| Q2 逻辑推理 | 1376 / 4515 | 1722 / 4220 | 812 / 1847 | 1259 / 3540 |
| Q3 约束优化 | 超时 | 超时 | 超时 | 2135 / 6041 |

#### 结论

1. **thinking=enabled 引发推理爆炸**：Q1 中两个含 thinking 的组合
   （both 和 thinking_only）都把推理推到 18k-22k chars，耗尽
   max_tokens=8192 后无正文输出（content_chars=0）。
   不含 thinking 的组合（effort_only 和 effort_low）正常完成。

2. **行为不可预测**：Q1 中 thinking_only（22k）>> effort_only（11k），
   但 Q2 中 thinking_only（5.5k）<< effort_only（13k）。
   thinking 与 reasoning_effort 的交互跟问题类型强相关，无法预测。

3. **同时发送无收益**：both（thinking+effort）在 Q1 炸了 max_tokens，
   在 Q2 反而比 effort_only 少（10k vs 13k）。没有场景证明同时发送更优。

4. **effort_low 最稳定**：三个问题全部正常完成，推理深度适中（9k-19k），
   说明 reasoning_effort 单独使用时对推理深度有可靠调节作用。

XOR 设计（仅发 reasoning_effort，不发 thinking）是正确的。

---

## 7. 各配置项说明

### fallback_models
- 未设置（默认空值），回退到 `_PROVIDER_MODELS["kimi-coding"]` 静态列表（8 个模型）
- 不设的好处：随 hermes update 自动同步 `_PROVIDER_MODELS` 更新

### default_max_tokens
- 未设置（None），由 Kimi 服务端决定默认行为
- 内置 KimiProfile 设为 32000，本插件有意不设
- 不设时请求不携带 max_tokens → 服务端用自己的默认值
- profile 路径的 max_tokens 解析链无全局 fallback，不会回退到 4096 或其他硬编码值

### default_aux_model
- 设为 "kimi-for-coding"（内置为 "kimi-k2-turbo-preview"）
- 用于辅助任务（上下文压缩、视觉分析、会话标题生成等后台任务）
- switch model 切换到 kimi-coding 后，辅助模型也自动切换到同一 provider 的廉价模型
- 曾考虑 kimi-k2-turbo-preview，但该模型较旧且为 preview 版，可能随时下架
- kimi-for-coding 是统一入口别名，更稳定

### fixed_temperature
- 设为 OMIT_TEMPERATURE（不发送 temperature 参数）
- Kimi API 文档明确说 temperature "Cannot be modified"
- 如果删除（变为默认 None）→ Hermes 会在请求里带 temperature → Kimi 可能拒绝
- ★ 不能删除

### default_headers
- 未设置（默认空字典）
- 内置 KimiProfile 设为 {"User-Agent": "hermes-agent/1.0"}
- api.kimi.com 路径下运行时 hostname 匹配覆盖为 claude-code/0.1.0
  （`_apply_client_headers_for_base_url()` 中 `api.kimi.com` 分支优先级最高）
- 仅 legacy key 走 api.moonshot.ai/v1 路径时 else 分支会读取 profile.default_headers，
  但 OpenAI 端点实测不检查 UA
- 由于用户使用 Coding Plan（sk-kimi- key），始终走 api.kimi.com 路径，省略无害

### base_url
- profile 中设为 `https://api.moonshot.ai/v1`（与内置一致）
- 实际运行时被 `_resolve_kimi_base_url()` 覆盖：
  - sk-kimi- key + KIMI_BASE_URL → `https://api.kimi.com/coding/v1`
  - legacy key → `https://api.moonshot.ai/v1`

---

## 8. 验证方法

### 8.1 确认插件已加载

```bash
# 启动 hermes 后，切换到 kimi
/model kimi-coding kimi-k2.7-code
```

预期：切换成功，功能正常。但可能出现 warning：

```
⚠ Note: could not verify `kimi-k2.7-code` against this endpoint's
  model listing.  Many Anthropic-compatible proxies do not implement
  GET /v1/models.  The model name has been accepted without verification.
```

此 warning 是 Hermes 源码的已知行为，非配置错误——验证阶段（validate_requested_model）
在 config.yaml 的 provider 更新之前执行，此时旧 provider 与新 provider 不匹配，
导致 `_provider_supports_explicit_api_mode()` 返回 False，回退到
`_detect_api_mode_for_url("https://api.kimi.com/coding/v1")` → `anthropic_messages`，
走 Anthropic 验证分支后探测 /models 失败（端点只返回 `["kimi-for-coding"]`，
不含 kimi-k2.7-code）。

切换完成后运行时正常使用 chat_completions 传输，不影响推理请求。
根因在 Hermes 源码（runtime_provider.py:113 对 api.kimi.com/coding 的硬编码检测），
无法从插件/config 侧修复。

### 8.2 检查 wire 参数

```bash
# 发一条消息后查看 dump
ls -t ~/.hermes/sessions/request_dump_*.json | head -1 | \
  xargs python3 -c "
import json,sys
d=json.load(sys.stdin)
body=d.get('request',{}).get('body',{})
print('model:', body.get('model'))
print('reasoning_effort:', body.get('reasoning_effort'))
print('extra_body:', body.get('extra_body'))
"
```

预期输出（reasoning_effort=xhigh）：
```
model: kimi-k2.7-code
reasoning_effort: high
extra_body: {}
```

> extra_body 为空是正确的 XOR 行为（不是 bug）。
> 当 reasoning_effort 被映射成功时，插件不发送 thinking 对象。
> 参见 §6.3 的对比测试——同时发送 thinking 和 reasoning_effort
> 会在部分问题上导致推理内容暴增、max_tokens 耗尽。
> 模型仍然产生 reasoning_content（reasoning_effort 本身触发推理）。

### 8.3 切换 effort 对比

```
/reasoning xhigh    → dump 应显示 reasoning_effort: "high"
/reasoning medium   → dump 应显示 reasoning_effort: "medium"
/reasoning minimal  → dump 应显示 reasoning_effort: "minimal"
/reasoning none     → dump 应显示 extra_body: {"thinking": {"type": "disabled"}}
```

---

## 9. 插件生命周期

### 现在为什么需要此插件

内置 KimiProfile 只映射 {low, medium, high}，minimal 和 xhigh 回退到
thinking=enabled（丢失 effort 意图）。此外，不配合 .env + config.yaml
配置时，KimiProfile.build_api_kwargs_extras() 根本不会被调用（走 Anthropic 传输）。

### 每次 `hermes update` 后检查

**步骤 1：检查内置 KimiProfile 是否已补全 effort 映射**

```bash
grep -A5 "effort.*minimal\|effort.*xhigh\|_EFFORT_MAP" \
  ~/.hermes/hermes-agent/plugins/model-providers/kimi-coding/__init__.py
```

**步骤 2：检查内置 KimiProfile 的 effort 映射集合**

```bash
grep "effort.*in.*{" \
  ~/.hermes/hermes-agent/plugins/model-providers/kimi-coding/__init__.py
```

如果映射集合已包含 `minimal` 和 `xhigh`，说明官方已补全。

**步骤 3：检查 api_mode 自动检测是否已修复**

```bash
grep -n "api.kimi.com.*coding\|kimi.*anthropic_messages" \
  ~/.hermes/hermes-agent/hermes_cli/runtime_provider.py
```

如果 `_detect_api_mode_for_url` 不再对 api.kimi.com/coding 返回 anthropic_messages，
则 .env 的 KIMI_BASE_URL 和 config.yaml 的 api_mode 也可以移除。

### 判定矩阵

| 内置实现情况 | 操作 |
|-------------|------|
| 仍只有 {low, medium, high} | 保持插件不变 |
| 已补全 minimal + xhigh，但 api_mode 检测未修复 | 删除插件，保留 .env + config.yaml 配置 |
| 已补全 + api_mode 检测已修复 | 删除插件 + .env + config.yaml（见附录 C） |

---

## 附录 A. 与 zai 插件对比

| 方面 | zai 插件 | kimi-coding 插件 |
|------|---------|-----------------|
| 覆盖原因 | _supports_reasoning_extra_body() 不匹配 | Anthropic 模式跳过 thinking + effort 映射缺口 |
| 需要前置配置 | 否（直接覆盖 profile 即可） | 是（.env + config.yaml） |
| 需要 monkey-patch | 是（reasoning_content 回传） | 否（原生支持） |
| 需要 tool_stream | 是（Z.AI 30 秒超时） | 否（Kimi 无此问题） |
| effort 档位 | high / max（2 档） | minimal / low / medium / high（4 档） |
| xhigh 映射 | reasoning_effort=max | reasoning_effort=high（API 不支持 max/xhigh） |
| thinking + effort | 同时发送（安全） | XOR（同时发导致推理爆炸） |
| fallback_models | 不设（回退 _PROVIDER_MODELS） | 不设（回退 _PROVIDER_MODELS） |
| default_max_tokens | 不设（服务端决定） | 不设（服务端决定） |
| default_aux_model | glm-5-turbo | kimi-for-coding |

---

## 附录 B. 实现细节注释

### B.1 reasoning_content 回传保持

不需要 monkey-patch（与 zai 插件不同）。Hermes 原生 `_needs_kimi_tool_reasoning()`
已匹配以下条件（`_needs_kimi_tool_reasoning()` in `run_agent.py`）：

| 条件 | 说明 |
|------|------|
| provider in {"kimi-coding", "kimi-coding-cn"} | provider 名匹配 |
| base_url 含 api.kimi.com | Coding Plan 端点 |
| base_url 含 moonshot.ai | 国际版 legacy 端点 |
| base_url 含 moonshot.cn | 中国版端点 |

reasoning_content 解析由 `agent_runtime_helpers.py:extract_reasoning()` 处理，
已检查 `message.reasoning_content` 字段。

### B.2 UA（User-Agent）行为

| 传输模式 | UA 值 | 来源 |
|----------|-------|------|
| chat_completions（本方案） | claude-code/0.1.0 | run_agent.py URL hostname 匹配 api.kimi.com |
| anthropic_messages（默认） | claude-code/0.1.0 | anthropic_adapter.py _is_kimi_coding_endpoint |

两种模式下 UA 相同，切换不影响 UA。
OpenAI 端点实测不检查 UA（空 UA 也返回 200），但保持 claude-code/0.1.0 无害。

### B.3 model id 兼容性

| model id | HTTP | 说明 |
|----------|------|------|
| kimi-for-coding | 200 | 统一入口别名 |
| kimi-k2.7-code | 200 | |
| kimi-k2.7-code-highspeed | 200 | 高速变体 |
| kimi-k2.6 | 200 | |
| kimi-k2.5 | 200 | |
| k2p7 | 200 | |
| k2p6 | 200 | |
| kimi-k2-thinking | 200 | |
| kimi-k2-turbo-preview | 200 | |
| kimi-k2-0905-preview | 200 | |
| moonshot-v1-8k | 200 | |

/models 端点仅返回 `["kimi-for-coding"]`，但 inference 端点接受全部模型 ID。

### B.4 models 端点

| URL | HTTP |
|-----|------|
| /coding/v1/models | 200（返回 ["kimi-for-coding"]） |
| /coding/models | 404 |
| /v1/models | 404 |

### B.5 对其他 provider 的影响

config.yaml 的 `api_mode: chat_completions` 设置：

| provider | config 匹配？ | 实际 api_mode | 影响 |
|----------|-------------|-------------|------|
| kimi-coding | 是 | chat_completions | ✓ 切到 OpenAI 协议 |
| zai | 是 | chat_completions | 无变化（本来就是） |
| deepseek | 是 | chat_completions | 无变化（本来就是） |
| anthropic | 否（硬编码） | anthropic_messages | 无变化 |
| openrouter | 是 | chat_completions | 无变化（本来就是） |

`_provider_supports_explicit_api_mode()` 确保 api_mode 只在 config.provider
匹配 runtime provider 时生效，无交叉污染。

.env 的 KIMI_BASE_URL 设置仅影响 kimi-coding 和 kimi-coding-cn provider，
不影响其他 provider。

---

## 附录 C. 清理方式

当判定矩阵指示可以完全删除时：

```bash
# 1. 删除插件
rm -rf ~/.hermes/plugins/model-providers/kimi-coding/

# 2. 如果官方也修复了 api_mode 自动检测（步骤 3 确认），可移除配置
# 删除 .env 中的 KIMI_BASE_URL 行
# 删除 config.yaml 中的 api_mode 行
```

下次 hermes 启动时自动使用内置 profile。
