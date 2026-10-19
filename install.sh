#!/bin/bash
# SNNU 校园网自动登录 · macOS 安装脚本
# 用法：bash install.sh [--interval 600]

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="SNNUAutoLogin"
DEST="$HOME/Library/Application Support/$APP_NAME/app"
INTERVAL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --interval) INTERVAL="$2"; shift 2 ;;
    *) echo "未知参数：$1"; exit 1 ;;
  esac
done

PY=/usr/bin/python3
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
  echo "✗ 未找到 python3，请先安装 Xcode 命令行工具：xcode-select --install"
  exit 1
fi

echo "→ 安装到：$DEST"
mkdir -p "$DEST" "$HOME/Library/Logs"

# 复制程序本体（覆盖式更新，不触碰配置与钥匙串）
# 防呆：目标必须是固定应用目录
case "$DEST" in
  "$HOME/Library/Application Support/SNNUAutoLogin/app") ;;
  *) echo "✗ 安装目录异常：$DEST"; exit 1 ;;
esac
rsync -a --delete "$SRC_DIR/snnu_autologin/" "$DEST/snnu_autologin/"
cp "$SRC_DIR/run.py" "$DEST/run.py"
mkdir -p "$DEST/bin"
cp "$SRC_DIR/bin/snnu-login" "$DEST/bin/snnu-login"
chmod +x "$DEST/bin/snnu-login"

# MIT 要求：许可与来源声明必须随每一份副本分发
for f in LICENSE NOTICE; do
  [ -f "$SRC_DIR/$f" ] && cp "$SRC_DIR/$f" "$DEST/$f"
done

# 命令软链：优先 /usr/local/bin，不可写则 ~/.local/bin
LINK_DIR=""
if [ -w /usr/local/bin ]; then
  LINK_DIR=/usr/local/bin
else
  LINK_DIR="$HOME/.local/bin"
  mkdir -p "$LINK_DIR"
fi
ln -sf "$DEST/bin/snnu-login" "$LINK_DIR/snnu-login"

# 安装 launchd 守护
if [ -n "$INTERVAL" ]; then
  "$PY" "$DEST/run.py" install --interval "$INTERVAL"
else
  "$PY" "$DEST/run.py" install
fi

echo ""
echo "✓ 安装完成"
echo "  命令：$LINK_DIR/snnu-login"
case ":$PATH:" in
  *":$LINK_DIR:"*) ;;
  *) echo "  ! $LINK_DIR 不在 PATH 中，可执行：echo 'export PATH=\"$LINK_DIR:\$PATH\"' >> ~/.zshrc" ;;
esac
echo ""
echo "下一步：配置账号密码"
echo "  $LINK_DIR/snnu-login setup"
