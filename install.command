#!/bin/bash
# 双击本文件即可安装（macOS 会打开「终端」执行）
cd "$(dirname "$0")" || exit 1
bash ./install.sh
echo ""
echo "-----------------------------------------------"
echo "可按回车关闭本窗口（安装已完成）"
read -r _
