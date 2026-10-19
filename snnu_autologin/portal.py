# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# 衍生自 SNNU-campus-autologin（Windows 版）：
#   https://github.com/mzh2077/SNNU-campus-autologin
#   Copyright (c) 2026 校园网自动登录工具贡献者（MIT License）
# macOS 移植与协议修正部分：Copyright (c) 2026 luohwdyx2（MIT License）
# 完整许可文本见仓库根目录 LICENSE。
"""
门户网络层
==========
移植自 Windows 原版 portal_client.py，并按 macOS 实测结果修正了登录协议。

实测修正（2026-10-19，macOS + 真实账号验证）
--------------------------------------------
1. **登录提交地址是 `login`，不是 `login.jsp`**。登录页 `<form action="login" method="post">`，
   字段：`sourceurl`（隐藏，值 "null"）、`account`、`password`、`yys`（运营商）。
   向 `login.jsp` POST 只会拿回登录页本身，看起来像"密码错误"，实为提交地址错误。
2. **必须先 GET 一次状态页拿到 JSESSIONID**，再用同一会话 POST `login`；
   无 Cookie 的请求会被门户拒绝。
3. **`account` 必须填纯学号，运营商用 `yys` 单独传**（mobile / unicom / telecom）。
   若把 `学号@mobile` 塞进 account，门户会尝试再次"开通代理业务"并失败，
   返回「登录失败:开通代理业务失败」——这不是密码错误。
4. 状态页编码 GB2312；`login` 端点的失败提示是 **UTF-8**。
   因此解码策略改为「先严格 UTF-8，失败再 GB18030」（GB2312 文本无法通过严格 UTF-8 解码）。
5. 已在线时任何登录请求回查都显示「已在线」，必须核验页面账号是否为本账号。
6. 门户对非浏览器 UA 返回 403，必须伪装 UA。
"""

from __future__ import annotations

import http.cookiejar
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import PortalConfig, log_file


class Status:
    OK = "OK"
    ALREADY_ONLINE = "ONLINE"
    BAD_CREDENTIAL = "BADCRED"
    PROXY_FAILED = "PROXYFAIL"
    NEED_CAPTCHA = "CAPTCHA"
    RATE_LIMITED = "RATE"
    UNREACHABLE = "UNREACHABLE"
    TIMEOUT = "TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL"
    UNKNOWN_ERROR = "UNKNOWN"
    SKIPPED = "SKIPPED"

    MESSAGES = {
        OK: "登录成功",
        ALREADY_ONLINE: "已在线",
        BAD_CREDENTIAL: "账号或密码错误",
        PROXY_FAILED: "运营商出口开通失败（检查套餐状态/运营商选择）",
        NEED_CAPTCHA: "需要输入验证码",
        RATE_LIMITED: "尝试过于频繁或账号被锁定",
        UNREACHABLE: "校园网不可达（未连接 SNNU 校园网？）",
        TIMEOUT: "请求超时",
        PROTOCOL_ERROR: "门户返回内容异常",
        UNKNOWN_ERROR: "未知错误",
        SKIPPED: "已在线，跳过校验",
    }

    @classmethod
    def message(cls, status: str) -> str:
        return cls.MESSAGES.get(status, cls.MESSAGES[cls.UNKNOWN_ERROR])

    @classmethod
    def is_good(cls, status: str) -> bool:
        return status in (cls.OK, cls.ALREADY_ONLINE)


def log(msg: str) -> None:
    """写运行日志（自动截断，避免无限增长）。"""
    try:
        path = log_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read()[-400_000:]
            with open(path, "w", encoding="utf-8") as f:
                f.write("[日志已轮转]\n" + tail)
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
        os.chmod(path, 0o600)
    except OSError:
        pass


class PortalClient:
    def __init__(self, cfg: PortalConfig):
        self.cfg = cfg
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),                 # 不走系统代理，直连门户
            urllib.request.HTTPCookieProcessor(self._jar),   # 保持 JSESSIONID
        )
        self.last_message = ""      # 门户返回的原始提示，便于排查

    # ------------------------------------------------------------------
    # 底层 HTTP
    # ------------------------------------------------------------------
    def _open(self, url: str, data=None, timeout=None):
        """发起请求，返回 (状态码, 正文)。网络异常抛 TimeoutError / ConnectionError。"""
        headers = {
            "User-Agent": self.cfg.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Referer"] = self.cfg.status_url
            headers["Origin"] = "http://%s:%d" % (self.cfg.portal_ip, self.cfg.portal_port)

        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self._opener.open(req, timeout=timeout or self.cfg.request_timeout) as resp:
                return resp.status, self._decode(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, self._decode(e.read())
            except Exception:
                return e.code, ""
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise TimeoutError(str(reason))
            raise ConnectionError(str(reason))
        except (TimeoutError, socket.timeout):
            raise TimeoutError("timeout")
        except Exception as e:
            raise ConnectionError(str(e))

    def _decode(self, raw: bytes) -> str:
        """
        先严格 UTF-8，失败再 GB18030。
        状态页是 GB2312（严格 UTF-8 必然失败），而 login 的提示是 UTF-8；
        若统一按 GB2312 解，提示会变成「鐧诲綍澶辫触」这类乱码。
        """
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode(self.cfg.status_encoding, errors="replace")

    # ------------------------------------------------------------------
    # 网络就绪
    # ------------------------------------------------------------------
    def tcp_probe(self, timeout=2.0) -> bool:
        """对门户 IP 做 TCP 探测：能建连即说明已处于校园网内。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((self.cfg.portal_ip, self.cfg.portal_port)) == 0
        except OSError:
            return False
        finally:
            sock.close()

    def wait_for_network(self, quiet=True) -> bool:
        """等待校园网就绪（刚连上 WiFi 时 DHCP/网关可能还没通）。"""
        if not self.cfg.wait_for_network:
            return self.tcp_probe(self.cfg.network_probe_timeout)
        if self.tcp_probe(self.cfg.network_probe_timeout):
            return True
        deadline = time.time() + self.cfg.network_wait_timeout
        if not quiet:
            print("正在等待校园网就绪…")
        while time.time() < deadline:
            time.sleep(self.cfg.network_poll_interval)
            if self.tcp_probe(self.cfg.network_probe_timeout):
                return True
        return False

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def check_status(self, expect_account=""):
        """返回 (状态, 信息dict)。已在线但账号不是本账号时视为未登录。"""
        code, text = self._open(self.cfg.status_url)
        if code == 403:
            return Status.PROTOCOL_ERROR, {}
        info = self._parse_status_page(text)
        if self._looks_online(text):
            if expect_account and not self._account_matches(text, expect_account):
                return Status.UNKNOWN_ERROR, info
            return Status.ALREADY_ONLINE, info
        if self._has_login_form(text):
            return Status.UNKNOWN_ERROR, info      # 门户正常，只是需要登录
        return Status.PROTOCOL_ERROR, info

    def _looks_online(self, text: str) -> bool:
        return any(m in text for m in self.cfg.online_markers)

    def _has_login_form(self, text: str) -> bool:
        return bool(re.search(
            r'(?is)<input[^>]*name=["\']?' + re.escape(self.cfg.alt_pass_field) + r'["\']?',
            text))

    def _parse_status_page(self, text: str) -> dict:
        info = {}
        for key, pattern in (
            ("account", r'id=["\']account["\'][^>]*value=["\']([^"\']*)'),
            ("ip", r'id=["\']ipaddr["\'][^>]*value=["\']([^"\']*)'),
        ):
            m = re.search(pattern, text, re.I)
            if m:
                info[key] = m.group(1).strip()
        m = re.search(r'登录时间[：:]\s*([0-9:\-\s]+)', text)
        if m:
            info["login_time"] = m.group(1).strip()
        return info

    def _account_matches(self, text: str, account: str) -> bool:
        """核验页面在线账号是否为本次目标账号（学号或学号@运营商都可传入）。"""
        want = self.cfg.portal_account(account).lower()
        uid = self.cfg.user_id(account).lower()

        info = self._parse_status_page(text)
        online = (info.get("account") or "").lower()
        if not online:
            m = re.search(r'(?:vloginid|loginid|userid)["\']?\s*[:=]\s*["\']?([^"\'&\s,]+)',
                          text, re.I)
            online = m.group(1).lower() if m else ""
        if not online:
            return False
        return online == want or online.split("@")[0] == uid

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    def login(self, account: str, password: str) -> str:
        """
        提交登录：GET 状态页建立会话 → POST login（纯学号 + yys）。
        返回 Status 状态标识。
        """
        self.last_message = ""
        try:
            status = self._try_portal(account, password)
        except TimeoutError:
            log("portal: 超时")
            status = Status.TIMEOUT
        except ConnectionError as e:
            log("portal: 连接失败 %s" % e)
            status = Status.UNREACHABLE
        except Exception as e:
            log("portal: 异常 %s: %s" % (type(e).__name__, e))
            status = Status.UNKNOWN_ERROR

        # 仅当门户前端本身不可用时才尝试自助服务端点：
        # 它属于另一套账号体系，不能用来判断密码对错，否则会误报"密码错误"。
        if (self.cfg.enable_zili_fallback
                and status in (Status.UNREACHABLE, Status.TIMEOUT, Status.PROTOCOL_ERROR)):
            try:
                alt = self._try_zili(account, password)
                log("zili => %s" % alt)
                if Status.is_good(alt):
                    return alt
            except Exception as e:
                log("zili: 异常 %s" % type(e).__name__)
        return status

    def _try_portal(self, account: str, password: str) -> str:
        # 1) 建立会话：GET 状态页（未登录时会跳到 login.jsp 并下发 JSESSIONID）
        self._open(self.cfg.status_url)

        # 2) POST 到表单真实 action「login」
        payload = {
            "sourceurl": "null",
            self.cfg.alt_user_field: self.cfg.user_id(account),      # 纯学号
            self.cfg.alt_pass_field: password,
            self.cfg.alt_yys_field: self.cfg.carrier_of(account),    # 运营商
        }
        body = urllib.parse.urlencode(payload).encode("utf-8")
        code, text = self._open(self.cfg.login_action_url(), data=body)

        if code >= 400:
            log("login HTTP %s" % code)
            return Status.PROTOCOL_ERROR

        # 3) 响应里直接是成功页
        if self._looks_online(text) and self._account_matches(text, account):
            return Status.OK

        # 4) 门户给出了明确的失败原因
        failed = self._parse_failure(text)
        if failed:
            return failed

        # 5) 响应没结论：回查状态页，最多约 8 秒（会话生效有延迟）
        for _ in range(4):
            time.sleep(1.5)
            try:
                st, _ = self.check_status(expect_account=account)
            except (TimeoutError, ConnectionError):
                continue
            if st == Status.ALREADY_ONLINE:
                return Status.OK
        return Status.UNKNOWN_ERROR

    def _parse_failure(self, text: str) -> str:
        """从响应中抽取「登录失败:xxx」，映射为状态标识。"""
        m = re.search(r"登录失败[：:]\s*([^<\r\n]{0,80})", text)
        msg = (m.group(1).strip() if m else "")
        if msg:
            self.last_message = msg
            log("门户提示：登录失败:%s" % msg)
            if "代理业务" in msg:
                return Status.PROXY_FAILED
            if "验证码" in msg:
                return Status.NEED_CAPTCHA
            if "频繁" in msg or "锁定" in msg:
                return Status.RATE_LIMITED
            if "密码" in msg or "账号" in msg or "帐号" in msg:
                return Status.BAD_CREDENTIAL
            return Status.UNKNOWN_ERROR

        for key, markers in self.cfg.error_markers.items():
            for marker in markers:
                if marker in text:
                    if key == "bad_credential":
                        return Status.BAD_CREDENTIAL
                    if key == "need_captcha":
                        return Status.NEED_CAPTCHA
                    if key == "rate_limited":
                        return Status.RATE_LIMITED
        return ""

    def _try_zili(self, account: str, password: str) -> str:
        """备用：校园宽带自助服务系统（字段不同，与门户是两套账号）。"""
        payload = {
            self.cfg.login_mode_field: self.cfg.login_mode_value,
            self.cfg.login_user_field: self.cfg.user_id(account),
            self.cfg.login_pass_field: password,
        }
        body = urllib.parse.urlencode(payload).encode("utf-8")
        code, text = self._open(self.cfg.login_url, data=body)
        if code >= 400:
            return Status.PROTOCOL_ERROR
        if re.search(r'(已登录|我的状态|当前登录|退出登录|欢迎)', text):
            return Status.OK
        return Status.UNKNOWN_ERROR

    # ------------------------------------------------------------------
    # 校验密码 / 下线
    # ------------------------------------------------------------------
    def verify_credentials(self, account: str, password: str, skip_if_online=True) -> str:
        """
        校验账号密码。已在线且账号一致时直接 SKIPPED（能上网即证明密码有效），
        避免反复下线打断连接；未在线时才真正提交一次登录。
        """
        if skip_if_online:
            try:
                st, _ = self.check_status(expect_account=account)
                if st == Status.ALREADY_ONLINE:
                    return Status.SKIPPED
            except (TimeoutError, ConnectionError):
                return Status.UNREACHABLE
            except Exception:
                pass
        return self.login(account, password)

    def logout(self) -> bool:
        try:
            code, _ = self._open(self.cfg.logoff_url())
            return code < 400
        except Exception:
            return False
