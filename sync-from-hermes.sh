#!/usr/bin/env bash
# sync-from-hermes.sh — Hermes → 仓库（日常更新备份）
#
# 将 ~/.hermes/ 中最新的 config.yaml 和插件文件拷贝到本仓库。
# 幂等，可反复运行。不自动 commit（用户决定何时提交）。

set -euo pipefail

# ── 定位路径 ──────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# ── 检查 Hermes 目录 ─────────────────────────────────

if [[ ! -d "$HERMES_HOME" ]]; then
  echo "错误：Hermes 目录不存在：$HERMES_HOME" >&2
  echo "请确认 Hermes Agent 已安装，或设置 HERMES_HOME 环境变量。" >&2
  exit 1
fi

echo "源目录：$HERMES_HOME"
echo "目标仓库：$REPO_DIR"
echo ""

# ── 拷贝文件 ─────────────────────────────────────────

copied=0
skipped=0

copy_file() {
  local src="$1"
  local dst="$2"
  local label="$3"

  if [[ ! -f "$src" ]]; then
    echo "  [跳过] $label — 源文件不存在：$src"
    ((skipped++)) || true
    return
  fi

  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  echo "  [已拷] $label"
  ((copied++)) || true
}

echo "== 拷贝 config.yaml =="
copy_file \
  "$HERMES_HOME/config.yaml" \
  "$REPO_DIR/config.yaml" \
  "config.yaml"

echo ""
echo "== 拷贝插件 zai =="
copy_file \
  "$HERMES_HOME/plugins/model-providers/zai/__init__.py" \
  "$REPO_DIR/plugins/model-providers/zai/__init__.py" \
  "zai/__init__.py"
copy_file \
  "$HERMES_HOME/plugins/model-providers/zai/README.md" \
  "$REPO_DIR/plugins/model-providers/zai/README.md" \
  "zai/README.md"

echo ""
echo "== 拷贝插件 kimi-coding =="
copy_file \
  "$HERMES_HOME/plugins/model-providers/kimi-coding/__init__.py" \
  "$REPO_DIR/plugins/model-providers/kimi-coding/__init__.py" \
  "kimi-coding/__init__.py"
copy_file \
  "$HERMES_HOME/plugins/model-providers/kimi-coding/README.md" \
  "$REPO_DIR/plugins/model-providers/kimi-coding/README.md" \
  "kimi-coding/README.md"

# ── 摘要 ─────────────────────────────────────────────

echo ""
echo "完成：拷贝 $copied 个文件，跳过 $skipped 个。"

if [[ -d "$REPO_DIR/.git" ]]; then
  echo ""
  echo "== Git 变更摘要 =="
  git -C "$REPO_DIR" diff --stat || true
  echo ""
  echo "如需提交，请运行："
  echo "  cd $REPO_DIR && git add -A && git commit -m \"update ...\" && git push"
fi
