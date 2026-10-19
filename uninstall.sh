#!/bin/bash
# SNNU 校园网自动登录 · 卸载脚本
# 默认只卸载后台守护；加 --purge 一并清除配置、钥匙串密码与程序文件

set -uo pipefail
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

APP_NAME="SNNUAutoLogin"
DEST="$HOME/Library/Application Support/$APP_NAME"
PY=/usr/bin/python3
[ -x "$PY" ] || PY="$(command -v python3)"

echo "→ 卸载后台守护"
if [ -f "$DEST/app/run.py" ]; then
  "$PY" "$DEST/app/run.py" uninstall || true
else
  launchctl bootout "gui/$(id -u)/local.snnu-autologin.agent" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/local.snnu-autologin.agent.plist"
fi

for L in /usr/local/bin/snnu-login "$HOME/.local/bin/snnu-login"; do
  [ -L "$L" ] && rm -f "$L"
done

if [ "$PURGE" -eq 1 ]; then
  echo ""
  echo "⚠️  将删除以下内容："
  echo "    - 配置与程序目录：$DEST"
  echo "    - 日志：$HOME/Library/Logs/$APP_NAME.log"
  echo "    - 钥匙串条目：SNNU-Campus-Autologin"
  printf "确认继续？[y/N] "
  read -r ans
  if [ "${ans:-}" = "y" ] || [ "${ans:-}" = "Y" ]; then
    # 钥匙串条目名是「学号@运营商」，必须用 Python 侧同样的规则计算，
    # 只拿纯学号去删会删不掉（历史 bug，已修）。
    if [ -f "$DEST/settings.json" ]; then
      "$PY" - "$DEST/settings.json" <<'EOPY'
import json, subprocess, sys
p = sys.argv[1]
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    sys.exit(0)
acc = str(d.get("account", "")).strip()
carrier = str(d.get("carrier", "")).strip()
key = acc if "@" in acc or not carrier else acc + "@" + carrier
if not key:
    sys.exit(0)
r = subprocess.run(["/usr/bin/security", "delete-generic-password",
                    "-s", "SNNU-Campus-Autologin", "-a", key],
                   capture_output=True, text=True)
if r.returncode == 0:
    print("  钥匙串条目 %s：已删除" % key)
elif "could not be found" in (r.stderr or ""):
    print("  钥匙串条目 %s：未找到（可能此前已删除）" % key)
else:
    print("  钥匙串条目 %s：删除失败，请手动执行：" % key)
    print("    security delete-generic-password -s SNNU-Campus-Autologin -a '%s'" % key)
    tail = (r.stderr or "").strip().splitlines()
    if tail:
        print("    原因：%s" % tail[-1][:120])
EOPY
    fi
    # 防呆：只允许删除固定的应用目录
    case "$DEST" in
      "$HOME/Library/Application Support/SNNUAutoLogin") rm -rf "$DEST" ;;
      *) echo "✗ 目录异常，拒绝删除：$DEST" ;;
    esac
    rm -f "$HOME/Library/Logs/$APP_NAME.log"
  else
    echo "已取消清除操作"
  fi
else
  echo "✓ 后台守护已卸载（配置与密码保留，如需彻底清除：bash uninstall.sh --purge）"
fi
