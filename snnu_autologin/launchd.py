# -*- coding: utf-8 -*-
"""
launchd 集成 —— 替代 Windows 的注册表开机自启
==============================================
生成的 LaunchAgent 同时具备三种触发方式：

  RunAtLoad     : 登录 macOS 后立即跑一次
  WatchPaths    : /Library/Preferences/SystemConfiguration 变化时触发
                  （连上 / 断开 WiFi、切换网线、DHCP 续约都会改动它）
                  —— 这正是「一连上校园网就自动登录」的实现方式
  StartInterval : 定时兜底（默认 600 秒），应对校园网会话被静默踢掉

ThrottleInterval 限制最短触发间隔，避免频繁网络抖动导致重复执行。
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys

from .config import AGENT_LABEL, app_dir, log_file, plist_path

WATCH_PATHS = [
    "/Library/Preferences/SystemConfiguration",
    "/var/run/resolv.conf",
]


def _launchctl(*args):
    return subprocess.run(["/bin/launchctl"] + list(args),
                          capture_output=True, text=True)


def _entry_script() -> str:
    return os.path.join(app_dir(), "run.py")


def build_plist(interval: int = 600) -> dict:
    log = log_file()
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": [sys.executable, _entry_script(), "agent"],
        "RunAtLoad": True,
        "WatchPaths": list(WATCH_PATHS),
        "StartInterval": int(interval),
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 5,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
            "LANG": "zh_CN.UTF-8",
        },
    }


def install(interval: int = 600):
    """写入 plist 并载入，返回 (plist路径, 是否载入成功, 错误信息)。"""
    path = plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = build_plist(interval)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        plistlib.dump(data, f)
    os.replace(tmp, path)
    os.chmod(path, 0o644)
    loaded, msg = reload()
    return path, loaded, msg


def _is_loaded() -> bool:
    uid = str(os.getuid())
    return _launchctl("print", "gui/%s/%s" % (uid, AGENT_LABEL)).returncode == 0


def reload():
    """重新加载任务（先卸载再加载，保证改动生效）。返回 (是否成功, 错误信息)。"""
    uid = str(os.getuid())
    path = plist_path()
    _launchctl("bootout", "gui/%s/%s" % (uid, AGENT_LABEL))
    res = _launchctl("bootstrap", "gui/%s" % uid, path)
    if res.returncode != 0 or not _is_loaded():
        # 老系统 / 特殊环境的兜底
        res2 = _launchctl("load", "-w", path)
        if _is_loaded():
            return True, ""
        msg = (res.stderr or res2.stderr or "").strip()
        return False, msg
    return True, ""


def uninstall() -> bool:
    uid = str(os.getuid())
    path = plist_path()
    _launchctl("bootout", "gui/%s/%s" % (uid, AGENT_LABEL))
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except OSError:
        return False
    return False


def is_installed() -> bool:
    return os.path.exists(plist_path())


def status() -> dict:
    """读取 launchctl 中该任务的状态。"""
    uid = str(os.getuid())
    res = _launchctl("print", "gui/%s/%s" % (uid, AGENT_LABEL))
    info = {"loaded": res.returncode == 0, "raw": res.stdout}
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("state ="):
            info["state"] = line.split("=", 1)[1].strip()
        elif line.startswith("pid ="):
            info["pid"] = line.split("=", 1)[1].strip()
        elif line.startswith("last exit code ="):
            info["last_exit"] = line.split("=", 1)[1].strip()
    return info


def kickstart() -> None:
    """立刻手动触发一次。"""
    uid = str(os.getuid())
    _launchctl("kickstart", "-k", "gui/%s/%s" % (uid, AGENT_LABEL))
