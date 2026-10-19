# -*- coding: utf-8 -*-
"""
钥匙串（Keychain）凭据存储 —— 替代 Windows 的 DPAPI
====================================================
密码存进「登录钥匙串」，条目：
    service = SNNU-Campus-Autologin
    account = 学号@运营商
仅当前用户可读；不上传、不落地明文。

说明：`security add-generic-password -w <密码>` 需要把密码作为参数传入，
进程列表中可见的窗口只有几毫秒；这是 macOS 命令行工具的限制（它不做非交互式
stdin 读取）。相比之下，把密码明文写进文件的风险高得多。
"""

from __future__ import annotations

import subprocess

from .config import KEYCHAIN_SERVICE

SECURITY = "/usr/bin/security"


def _run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def save_password(account: str, password: str) -> None:
    """写入或更新钥匙串条目（-U 表示已存在则更新）。"""
    res = _run([SECURITY, "add-generic-password",
                "-U", "-s", KEYCHAIN_SERVICE, "-a", account,
                "-w", password, "-T", ""])
    if res.returncode != 0:
        raise RuntimeError(
            "写入钥匙串失败：" + (res.stderr.strip() or "未知错误")
        )


def get_password(account: str) -> str:
    res = _run([SECURITY, "find-generic-password",
                "-s", KEYCHAIN_SERVICE, "-a", account, "-w"])
    if res.returncode != 0:
        return ""
    return res.stdout.rstrip("\n")


def delete_password(account: str) -> bool:
    res = _run([SECURITY, "delete-generic-password",
                "-s", KEYCHAIN_SERVICE, "-a", account])
    return res.returncode == 0


