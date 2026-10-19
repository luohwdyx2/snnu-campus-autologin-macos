# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# 衍生自 SNNU-campus-autologin（Windows 版）：
#   https://github.com/mzh2077/SNNU-campus-autologin
#   Copyright (c) 2026 校园网自动登录工具贡献者（MIT License）
# macOS 移植与协议修正部分：Copyright (c) 2026 luohwdyx2（MIT License）
# 完整许可文本见仓库根目录 LICENSE。
"""
配置中心（macOS 版）
====================
把「门户地址 / 接口路径 / 请求字段名 / 运营商取值 / 超时」集中在这里。
门户改版时只需要改本文件。

与 Windows 原版的差异
---------------------
* 数据目录从 %LOCALAPPDATA% 改为 ~/Library/Application Support
* 密码从 DPAPI 加密文件改为 macOS 钥匙串（Keychain）
* 开机自启从注册表 Run 项改为 launchd LaunchAgent
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

APP_NAME = "SNNUAutoLogin"
APP_VERSION = "1.0.0"

# launchd 任务标识（反向域名）
AGENT_LABEL = "local.snnu-autologin.agent"
# 钥匙串条目名
KEYCHAIN_SERVICE = "SNNU-Campus-Autologin"


# ---------------------------------------------------------------------------
# 1. 路径
# ---------------------------------------------------------------------------
def _home() -> str:
    return os.path.expanduser("~")


def data_dir() -> str:
    """配置与运行状态目录（不敏感）。"""
    return os.path.join(_home(), "Library", "Application Support", APP_NAME)


def config_file() -> str:
    return os.path.join(data_dir(), "settings.json")


def state_file() -> str:
    """运行状态：上次失败时间、失败次数，用于失败退避，避免密码错误被反复重试锁号。"""
    return os.path.join(data_dir(), "state.json")


def log_file() -> str:
    return os.path.join(_home(), "Library", "Logs", APP_NAME + ".log")


def plist_path() -> str:
    return os.path.join(_home(), "Library", "LaunchAgents", AGENT_LABEL + ".plist")


def app_dir() -> str:
    """程序本体安装目录（install.sh 会把代码复制到这里）。"""
    return os.path.join(data_dir(), "app")


# ---------------------------------------------------------------------------
# 2. 门户端点
# ---------------------------------------------------------------------------
# 实测（源自 Windows 原版）：该门户为深澜 snnuportal 认证系统（陕西师范大学）
#   http://202.117.144.205:8603/snnuportal/  → 302 → userstatus.jsp
#   userstatus.jsp：在线时显示「当前登录账号 / 登录时间 / 断开连接」，离线时为登录表单
#   门户页面编码为 GB2312（用 gb18030 兼容更全）
#   门户对 curl 默认 UA 返回 403，必须伪装浏览器 UA
# ---------------------------------------------------------------------------
@dataclass
class PortalConfig:
    # ---- 状态页：判断「是否已在线」的入口 ----
    portal_ip: str = "202.117.144.205"
    portal_port: int = 8603
    status_url: str = "http://202.117.144.205:8603/snnuportal/userstatus.jsp"
    status_encoding: str = "gb18030"

    # ---- 备用登录端点（校园宽带自助服务，字段不同）----
    login_url: str = "http://202.117.144.205:80/zili/index.php"
    login_mode_field: str = "mode"
    login_mode_value: str = "login"
    login_user_field: str = "login"
    login_pass_field: str = "passwd"
    # 备用端点属于另一套账号体系，默认关闭，避免把同一密码提交给第二个系统
    enable_zili_fallback: bool = False

    # ---- 账号 ----
    # account 存**纯学号**（如 2024010101），运营商单独用 carrier 表示。
    # 实测：把「学号@mobile」填进表单的 account 字段，门户会尝试再开通一次代理业务
    # 并返回「登录失败:开通代理业务失败」，所以两者必须分开。
    account: str = ""
    carrier: str = "mobile"

    # ---- snnuportal 登录表单字段 ----
    alt_user_field: str = "account"
    alt_pass_field: str = "password"
    alt_yys_field: str = "yys"

    # ---- 网络行为 ----
    request_timeout: float = 8.0
    max_retries: int = 2
    retry_delay: float = 1.5
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # ---- 等待校园网就绪 ----
    # 刚连上 WiFi 时 DHCP/网关可能还没就绪，直接请求会报「不可达」，故先探测再登录。
    wait_for_network: bool = True
    network_wait_timeout: float = 45.0
    network_poll_interval: float = 3.0
    network_probe_timeout: float = 2.0

    # ---- 触发方式 ----
    # launchd 定时兜底检查的间隔（秒）；同时还有「网络配置变化」事件触发
    agent_interval: int = 600
    # 连续密码错误达到该次数后进入冷却，避免把账号试锁
    max_cred_failures: int = 3
    cred_cooldown: int = 1800

    # ---- 状态页判定关键词 ----
    online_markers: list = field(default_factory=lambda: [
        "当前登录账号", "登录时间", "断开连接", "logoff",
    ])
    error_markers: dict = field(default_factory=lambda: {
        "bad_credential": ["帐号或密码错误", "账号或密码错误", "密码错误",
                           "用户不存在", "帐号不存在", "账号不存在", "登录失败"],
        "need_captcha":   ["验证码错误", "请输入验证码"],
        "rate_limited":   ["过于频繁", "稍后再试", "已锁定"],
        "not_open":       ["暂停", "未开放", "禁止"],
    })

    def to_dict(self) -> dict:
        return asdict(self)

    # ---- 账号形态转换 ----
    def user_id(self, account: str = "") -> str:
        """纯学号。传入「学号@mobile」也会被拆开。"""
        acc = (account or self.account or "").strip()
        return acc.split("@", 1)[0] if "@" in acc else acc

    def carrier_of(self, account: str = "") -> str:
        acc = (account or self.account or "").strip()
        if "@" in acc:
            return acc.split("@", 1)[1]
        return self.carrier

    def portal_account(self, account: str = "") -> str:
        """门户展示/核验用的完整账号：学号@运营商。"""
        uid = self.user_id(account)
        carrier = self.carrier_of(account)
        return "%s@%s" % (uid, carrier) if carrier else uid

    # ---- 端点 ----
    def portal_base(self) -> str:
        return self.status_url.rsplit("/", 1)[0]

    def login_action_url(self) -> str:
        """登录表单的真实 action（实测为 login，不是 login.jsp）。"""
        return self.portal_base() + "/login"

    def logoff_url(self) -> str:
        return self.portal_base() + "/logoff"


CARRIER_NAMES = {"mobile": "移动", "unicom": "联通", "telecom": "电信", "": "校园网"}


_CONFIG = PortalConfig()


def portal() -> PortalConfig:
    return _CONFIG


def load() -> PortalConfig:
    """读取 settings.json，覆盖默认值；缺失字段保持默认。"""
    path = config_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, value in data.items():
                if hasattr(_CONFIG, key):
                    setattr(_CONFIG, key, value)
        except (OSError, ValueError):
            pass
    return _CONFIG


def save() -> None:
    os.makedirs(data_dir(), exist_ok=True)
    tmp = config_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_CONFIG.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, config_file())
    try:
        os.chmod(config_file(), 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 3. 运行状态（失败退避）
# ---------------------------------------------------------------------------
def load_state() -> dict:
    try:
        with open(state_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(data: dict) -> None:
    os.makedirs(data_dir(), exist_ok=True)
    try:
        with open(state_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(state_file(), 0o600)
    except OSError:
        pass
