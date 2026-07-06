# Hermes Agent 配置备份

Hermes Agent (by [Nous Research](https://github.com/NousResearch)) 的个人配置备份与分享仓库。
包含完整的 config.yaml 和两个用户 provider 插件。

> 配置快照：Hermes Agent v0.18.0 (2026-07-01, upstream beaa1a08)

## 仓库内容

```
hermes-config/
├── config.yaml                — Hermes 完整配置快照（核心）
├── plugins/
│   └── model-providers/
│       ├── zai/               — Z.AI/GLM: reasoning_effort + tool_stream + reasoning_content echo-back
│       └── kimi-coding/       — Kimi: reasoning_effort 映射补全 (minimal/xhigh)
├── sync-from-hermes.sh        — Hermes → 仓库（日常更新备份）
└── restore-to-hermes.sh       — 仓库 → Hermes（灾难恢复 / 新机部署）
```

## 两个脚本的用途

| 脚本 | 方向 | 场景 |
|------|------|------|
| sync-from-hermes.sh | ~/.hermes/ → 仓库 | 日常修改配置或插件后，更新仓库备份 |
| restore-to-hermes.sh | 仓库 → ~/.hermes/ | 重装系统 / 新机部署后，恢复配置和插件 |

两个脚本都是纯拷贝，不修改 Hermes 运行时行为，不自动 commit/push。

## 快速开始（恢复部署）

```bash
# 1. 克隆仓库
git clone https://github.com/bytesnail/hermes-config.git
cd hermes-config

# 2. 确认 Hermes Agent 已安装并完成初始化（至少运行过一次 hermes）

# 3. 运行恢复脚本
bash restore-to-hermes.sh

# 4. 手动配置 ~/.hermes/.env（见下方）

# 5. 验证
hermes version
hermes config check
```

## 更新备份

```bash
# 修改 ~/.hermes/ 中的配置或插件后
bash sync-from-hermes.sh

# 检查变更
git diff --stat

# 满意后提交
git add -A
git commit -m "update config / plugins ..."
git push
```

## 手动配置 ~/.hermes/.env

此仓库不含任何 API key 或敏感信息。使用前需在 `~/.hermes/.env` 中手动配置：

```dotenv
# Z.AI / GLM（中国版 Coding Plan 端点；国际版可省略 GLM_BASE_URL）
GLM_API_KEY=sk-***
GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4

# Kimi Coding Plan（sk-kimi- 前缀的 key）
KIMI_CODING_API_KEY=sk-kimi-***
# kimi-coding 插件前置条件：覆盖默认路由，切换到 OpenAI 协议
KIMI_BASE_URL=https://api.kimi.com/coding/v1

# DeepSeek（fallback provider）
DEEPSEEK_API_KEY=sk-***
```

config.yaml 中对应的配置项（恢复时随 config.yaml 一起部署，无需手动设置）：

```yaml
model:
  api_mode: chat_completions    # kimi-coding 插件前置条件
  default: glm-5.2
  provider: zai
```

## 插件详情

- [ZAI / GLM 插件文档](plugins/model-providers/zai/README.md) — 解决 reasoning_effort / tool_stream / reasoning_content echo-back
- [Kimi / Moonshot 插件文档](plugins/model-providers/kimi-coding/README.md) — 补全 minimal/xhigh effort 映射

每个插件 README 内含：与内置 profile 的差异清单、API 实测数据、每次 `hermes update` 后的检查步骤。

## 前置条件

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.18.0+
- Z.AI / GLM API key（Coding Plan 或按量）
- Kimi Coding Plan API key（sk-kimi- 前缀）
- DeepSeek API key（fallback provider）

## 官方 PR 追踪

以下 PR 合入后，对应的用户插件可能不再需要（届时参考各插件 README 中的判定矩阵）：

- [#58884](https://github.com/NousResearch/hermes-agent/pull/58884) GLM-5.2 reasoning_effort controls (salvage #51108) — Open
- [#51108](https://github.com/NousResearch/hermes-agent/pull/51108) GLM-5.2 reasoning_effort (原始 PR，已被 #58884 salvage) — Open
- [#24915](https://github.com/NousResearch/hermes-agent/pull/24915) Z.AI 综合修复 (tool_stream + thinking) — Open
- [#51195](https://github.com/NousResearch/hermes-agent/pull/51195) GLM reasoning_content echo-back + max_tokens — Open

## License

MIT
