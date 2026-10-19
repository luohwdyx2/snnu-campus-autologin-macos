#!/bin/bash
# 双击本文件即可启用「连上校园网自动登录」的后台守护
# （macOS 只允许在真实终端中注册 launchd 任务，所以需要这一步）
cd "$(dirname "$0")" || exit 1

PY=/usr/bin/python3
[ -x "$PY" ] || PY=$(command -v python3)
APP="$HOME/Library/Application Support/SNNUAutoLogin/app"

echo "==============================================="
echo " SNNU 校园网自动登录 · 启用后台守护"
echo "==============================================="
echo ""

if [ ! -f "$APP/run.py" ]; then
  echo "✗ 未找到安装目录，请先双击 install.command 完成安装"
  echo ""
  echo "按回车关闭…"; read -r _; exit 1
fi

"$PY" "$APP/run.py" install
RC=$?

echo ""
if [ $RC -eq 0 ]; then
  echo "✓ 已启用：登录系统时、连上校园网时、以及每 10 分钟都会自动检查并登录。"
  echo ""
  echo "  现在就可以断开再连一次 WiFi 试试。"
else
  echo "✗ 未能启用，请附上上面的错误信息提 Issue。"
fi

echo ""
echo "当前任务状态："
launchctl print "gui/$(id -u)/com.snnu.campus-autologin" 2>/dev/null \
  | grep -E "state|program|last exit" | sed 's/^[[:space:]]*/  /'

echo ""
echo "本窗口 10 秒后自动关闭。"
sleep 10
