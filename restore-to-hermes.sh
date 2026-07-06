#!/usr/bin/env bash
# restore-to-hermes.sh — 仓库 → Hermes（灾难恢复 / 新机部署）
#
# 将本仓库中的 config.yaml 和插件文件拷贝到 ~/.hermes/。
# 如目标文件已存在且内容不同，先备份为 *.bak.<timestamp>。
# 不自动覆盖，不碰 .env。

set -euo pipefail

# ── 定位路径 ──────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

FORCE=false
if [[ "${1:-}" == "--force" ]]; then
  FORCE=true
fi

# ── 前置检查 ─────────────────────────────────────────

if [[ ! -d "$HERMES_HOME" ]]; then
  echo "错误：Hermes 目录不存在：$HERMES_HOME" >&2
  echo "请先安装 Hermes Agent 并完成初始化（hermes 命令至少运行一次）。" >&2
  exit 1
fi

if [[ ! -d "$HERMES_HOME/plugins/model-providers" ]]; then
  mkdir -p "$HERMES_HOME/plugins/model-providers"
  echo "已创建：$HERMES_HOME/plugins/model-providers/"
fi

echo "源仓库：$REPO_DIR"
echo "目标目录：$HERMES_HOME"
if $FORCE; then
  echo "模式：--force（直接覆盖，不备份）"
else
  echo "模式：安全（不同内容先备份）"
fi
echo ""

# ── 拷贝文件 ─────────────────────────────────────────

timestamp="$(date +%Y%m%d_%H%M%S)"
copied=0
backed_up=0
skipped=0

restore_file() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -f "$src" ]]; then
    echo "  [跳过] $label — 仓库中不存在：$src"
    ((skipped++)) || true
    return
  fi

  mkdir -p "$(dirname "$dst")"

  # 目标不存在 → 直接拷贝
  if [[ ! -f "$dst" ]]; then
    cp "$src" "$dst"
    echo "  [新建] $label"
    ((copied++)) || true
    return
  fi

  # 目标存在 → 比较内容
  if cmp -s "$src" "$dst"; then
    echo "  [相同] $label — 无需更新"
    ((skipped++)) || true
    return
  fi

  # 内容不同
  if $FORCE; then
    cp "$src" "$dst"
    echo "  [覆盖] $label"
    ((copied++)) || true
  else
    cp "$dst" "${dst}.bak.${timestamp}"
    cp "$src" "$dst"
    echo "  [备份+覆盖] $label → ${dst}.bak.${timestamp}"
    ((backed_up++)) || true
    ((copied++)) || true
  fi
}

echo "== 恢复 config.yaml =="
restore_file \
  "$REPO_DIR/config.yaml" \
  "$HERMES_HOME/config.yaml" \
  "config.yaml"

echo ""
echo "== 恢复插件 zai =="
restore_file \
  "$REPO_DIR/plugins/model-providers/zai/__init__.py" \
  "$HERMES_HOME/plugins/model-providers/zai/__init__.py" \
  "zai/__init__.py"
restore_file \
  "$REPO_DIR/plugins/model-providers/zai/README.md" \
  "$HERMES_HOME/plugins/model-providers/zai/README.md" \
  "zai/README.md"

echo ""
echo "== 恢复插件 kimi-coding =="
restore_file \
  "$REPO_DIR/plugins/model-providers/kimi-coding/__init__.py" \
  "$HERMES_HOME/plugins/model-providers/kimi-coding/__init__.py" \
  "kimi-coding/__init__.py"
restore_file \
  "$REPO_DIR/plugins/model-providers/kimi-coding/README.md" \
  "$HERMES_HOME/plugins/model-providers/kimi-coding/README.md" \
  "kimi-coding/README.md"

# ── 摘要 ─────────────────────────────────────────────

echo ""
echo "完成：拷贝 $copied，备份 $backed_up，跳过 $skipped。"

echo ""
echo "========================================"
echo "手动配置提醒（本脚本不碰 .env）"
echo "========================================"
echo ""
echo "请在 ~/.hermes/.env 中配置以下变量："
echo "  GLM_API_KEY=***               （Z.AI / GLM Coding Plan）"
echo "  GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4"
echo "                                （中国版端点；国际版可省略）"
echo "  KIMI_CODING_API_KEY=***  （Kimi Coding Plan，sk-kimi- 前缀）"
echo "  KIMI_BASE_URL=https://api.kimi.com/coding/v1"
echo "                                （kimi-coding 插件前置条件）"
echo "  DEEPSEEK_API_KEY=***          （DeepSeek，fallback provider）"
echo ""
echo "验证命令："
echo "  hermes version"
echo "  hermes config check"
