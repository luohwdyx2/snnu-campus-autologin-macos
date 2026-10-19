# -*- coding: utf-8 -*-
"""
命令行入口
==========
  snnu-login setup        首次配置（输入账号、密码、运营商，并校验）
  snnu-login login        手动登录一次
  snnu-login status       查看当前在线状态
  snnu-login logout       主动下线
  snnu-login agent        静默模式（launchd 调用，无输出）
  snnu-login install      安装后台守护（连上校园网即自动登录）
  snnu-login uninstall    卸载后台守护
  snnu-login logs         查看运行日志
  snnu-login doctor       环境自检
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import time

from . import config, keychain, launchd
from .portal import PortalClient, Status, log

CARRIERS = {
    "1": ("mobile", "移动"),
    "2": ("unicom", "联通"),
    "3": ("telecom", "电信"),
}

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")


def ok(t):
    print(GREEN + "✓ " + t + RESET)


def bad(t):
    print(RED + "✗ " + t + RESET)


def warn(t):
    print(YELLOW + "! " + t + RESET)


def dim(t):
    print(DIM + t + RESET)


# ---------------------------------------------------------------------------
# 核心：执行一次登录
# ---------------------------------------------------------------------------
def do_login(cfg, cli, quiet=False, wait_network=True):
    """
    返回 (状态, 说明)。不抛异常。
    流程：等网络 → 查状态 → 需要时提交登录。
    """
    account = cfg.account
    if not account:
        return Status.UNKNOWN_ERROR, "尚未配置账号，请先运行：snnu-login setup"

    key = cfg.portal_account()
    password = keychain.get_password(key)
    if not password:
        return Status.UNKNOWN_ERROR, "钥匙串中没有该账号的密码，请重新运行：snnu-login setup"

    # 1) 网络就绪（不在校园网时快速失败，避免无谓请求）
    if wait_network and not cli.tcp_probe(cfg.network_probe_timeout):
        if cfg.wait_for_network:
            if not quiet:
                dim("等待校园网就绪（最多 %d 秒）…" % int(cfg.network_wait_timeout))
            if not cli.wait_for_network(quiet=quiet):
                return Status.UNREACHABLE, Status.message(Status.UNREACHABLE)
        else:
            return Status.UNREACHABLE, Status.message(Status.UNREACHABLE)

    # 2) 查状态：已在线且账号一致则直接结束
    try:
        st, info = cli.check_status(expect_account=account)
    except TimeoutError:
        st, info = Status.TIMEOUT, {}
    except ConnectionError:
        st, info = Status.UNREACHABLE, {}

    if st == Status.ALREADY_ONLINE:
        return Status.ALREADY_ONLINE, _session_text(info)

    # 3) 提交登录
    code = cli.login(account, password)
    if Status.is_good(code):
        try:
            _, info2 = cli.check_status(expect_account=account)
        except Exception:
            info2 = {}
        return code, _session_text(info2)
    detail = Status.message(code)
    if cli.last_message and cli.last_message not in detail:
        detail += "（门户提示：%s）" % cli.last_message
    return code, detail


def _mask(text):
    """日志脱敏：学号只留前 4 位，内网 IP 隐藏后两段。"""
    text = re.sub(r"\b(\d{4})\d{2,}(\d{2})(@(?:mobile|unicom|telecom))?",
                  lambda m: m.group(1) + "****" + m.group(2) + (m.group(3) or ""), text)
    text = re.sub(r"\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b",
                  lambda m: "%s.%s.*.*" % (m.group(1), m.group(2)), text)
    return text


def _session_text(info):
    if not info:
        return Status.message(Status.OK)
    parts = []
    if info.get("account"):
        parts.append("账号 " + info["account"])
    if info.get("ip"):
        parts.append("IP " + info["ip"])
    if info.get("login_time"):
        parts.append("登录时间 " + info["login_time"])
    return "  ".join(parts) if parts else Status.message(Status.OK)


# ---------------------------------------------------------------------------
# 失败退避：密码错误不反复重试，避免账号被锁
# ---------------------------------------------------------------------------
def in_cooldown(cfg, state):
    if state.get("last_status") not in (Status.BAD_CREDENTIAL,
                                        Status.NEED_CAPTCHA,
                                        Status.RATE_LIMITED,
                                        Status.PROXY_FAILED):
        return False
    if int(state.get("fail_count", 0)) < cfg.max_cred_failures:
        return False
    last = float(state.get("last_attempt", 0))
    return (time.time() - last) < cfg.cred_cooldown


def record_result(cfg, status):
    state = config.load_state()
    if Status.is_good(status):
        state.update({"fail_count": 0, "last_status": status,
                      "last_success": time.time()})
    else:
        state["fail_count"] = int(state.get("fail_count", 0)) + 1
        state["last_status"] = status
        state["last_attempt"] = time.time()
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    config.save_state(state)


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------
def cmd_setup(args):
    cfg = config.load()
    cli = PortalClient(cfg)
    print(BOLD + "\nSNNU 校园网自动登录 · 首次配置\n" + RESET)

    # 若当前已在线，直接把门户上的账号作为默认值（省去手输后缀的麻烦）
    detected = ""
    if cli.tcp_probe(cfg.network_probe_timeout):
        try:
            st, info = cli.check_status()
            if st == Status.ALREADY_ONLINE and info.get("account"):
                detected = info["account"]
        except Exception:
            pass

    dim("只需填学号，运营商单独选（门户要求两者分开，填「学号@移动」会报代理业务失败）\n")

    default_account = cfg.user_id() or (detected.split("@")[0] if detected else "")
    prompt = "学号"
    if default_account:
        prompt += " [%s]" % default_account
    account = input(prompt + "：").strip() or default_account
    if not account:
        bad("学号不能为空")
        return 1

    if "@" in account:
        account, carrier = account.split("@", 1)
        cfg.carrier = carrier
        dim("已识别运营商：%s" % carrier)
    else:
        print("\n请选择网络服务商：")
        print("  1) 移动 mobile")
        print("  2) 联通 unicom")
        print("  3) 电信 telecom")
        cur = cfg.carrier or "mobile"
        default_choice = {"mobile": "1", "unicom": "2", "telecom": "3"}.get(cur, "1")
        choice = input("选择 [1/2/3，默认 %s]：" % config.CARRIER_NAMES.get(cur, cur)
                       ).strip() or default_choice
        cfg.carrier = CARRIERS.get(choice, (cur, ""))[0]
        dim("运营商：%s" % config.CARRIER_NAMES.get(cfg.carrier, cfg.carrier))

    password = getpass.getpass("\n密码（输入时不显示）：")
    if not password:
        bad("密码不能为空")
        return 1

    cfg.account = account
    config.save()
    dim("将使用账号：%s" % cfg.portal_account())

    # 校验（不在校园网内则跳过，不阻塞配置）
    if cli.tcp_probe(cfg.network_probe_timeout):
        print("")
        dim("正在校验账号密码…")
        st = cli.verify_credentials(account, password)
        if st in (Status.OK, Status.SKIPPED):
            ok("校验通过（%s）" % Status.message(st))
        elif st in (Status.BAD_CREDENTIAL, Status.PROXY_FAILED):
            bad(Status.message(st))
            if cli.last_message:
                dim("  门户提示：%s" % cli.last_message)
            if not _confirm("仍要保存这份配置吗？[y/N] "):
                return 1
        else:
            warn("暂时无法校验：%s（不影响保存）" % Status.message(st))
    else:
        warn("当前不在 SNNU 校园网内，跳过密码校验，稍后连上校园网会自动登录")

    keychain.save_password(cfg.portal_account(), password)
    ok("密码已存入 macOS 钥匙串（仅本机、仅当前用户可读）")
    dim("  配置：%s" % config.config_file())

    if launchd.is_installed():
        ok("后台守护已安装")
    else:
        if _confirm("\n现在安装后台守护（连上校园网即自动登录，开机也自动）？[Y/n] ", True):
            cmd_install(argparse.Namespace(interval=0))

    print("")
    ok("配置完成。可随时运行：snnu-login login")
    return 0


def _confirm(prompt, default=False):
    try:
        ans = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("")
        return False
    if not ans:
        return default
    return ans in ("y", "yes", "是")


def cmd_login(args):
    cfg = config.load()
    cli = PortalClient(cfg)
    if not args.quiet:
        dim("正在登录…")
    status, text = do_login(cfg, cli, quiet=args.quiet)
    record_result(cfg, status)
    if Status.is_good(status):
        if not args.quiet:
            ok(Status.message(status) + "  " + text)
        log("手动登录 => %s %s" % (status, _mask(text)))
        return 0
    if not args.quiet:
        bad(text)
    log("手动登录失败 => %s %s" % (status, _mask(text)))
    return 1 if status != Status.UNREACHABLE else 2


def cmd_agent(args):
    """launchd 调用：静默、无输出、带退避。"""
    cfg = config.load()
    if not cfg.account:
        return 0
    if not keychain.get_password(cfg.portal_account()):
        log("跳过：钥匙串中没有密码，请运行 snnu-login setup")
        return 0
    state = config.load_state()
    if in_cooldown(cfg, state):
        log("跳过：凭据连续失败进入冷却期（%s）" % state.get("last_status"))
        return 0

    cli = PortalClient(cfg)
    if cfg.wait_for_network:
        cli.wait_for_network(quiet=True)
    if not cli.tcp_probe(cfg.network_probe_timeout):
        log("跳过：非校园网环境")
        return 0

    status, text = do_login(cfg, cli, quiet=True, wait_network=False)
    record_result(cfg, status)
    # 日志里不写密码；只在结果变化时记录，避免刷屏
    if Status.is_good(status):
        if state.get("last_status") != status:
            log("自动登录 => %s %s" % (status, _mask(text)))
    else:
        log("自动登录失败 => %s %s" % (status, _mask(text)))
    return 0


def cmd_status(args):
    cfg = config.load()
    cli = PortalClient(cfg)
    if not cli.tcp_probe(cfg.network_probe_timeout):
        warn("当前不在 SNNU 校园网内（门户 %s:%d 不可达）"
             % (cfg.portal_ip, cfg.portal_port))
        return 2
    try:
        st, info = cli.check_status(expect_account=cfg.portal_account())
    except TimeoutError:
        bad(Status.message(Status.TIMEOUT))
        return 1
    except ConnectionError as e:
        bad("连接失败：%s" % e)
        return 1

    if st == Status.ALREADY_ONLINE:
        ok("已在线")
        for key, label in (("account", "账号"), ("ip", "内网 IP"),
                           ("login_time", "登录时间")):
            if info.get(key):
                print("   %s：%s" % (label, info[key]))
        return 0
    if st == Status.UNKNOWN_ERROR:
        warn("未登录（门户可达，需要登录）")
        return 1
    bad("门户返回异常：%s" % Status.message(st))
    return 1


def cmd_logout(args):
    cfg = config.load()
    cli = PortalClient(cfg)
    if not cli.tcp_probe(cfg.network_probe_timeout):
        warn("当前不在 SNNU 校园网内")
        return 2
    if cli.logout():
        ok("已发送下线请求")
        return 0
    bad("下线失败")
    return 1


def cmd_install(args):
    cfg = config.load()
    interval = args.interval or cfg.agent_interval
    cfg.agent_interval = interval
    config.save()
    path, loaded, err = launchd.install(interval)
    dim("  任务描述文件：%s" % path)
    if not loaded:
        warn("任务描述已写入，但未能载入 launchd：%s" % (err or "未知原因"))
        dim("  请在「终端」里执行一次以完成载入（或双击 enable-agent.command）：")
        dim("    snnu-login install")
        return 1
    ok("后台守护已安装并开始运行")
    dim("  任务：%s" % launchd.AGENT_LABEL)
    dim("  触发：登录系统时 / 网络配置变化时 / 每 %d 秒兜底检查" % interval)
    dim("  日志：%s" % config.log_file())
    return 0


def cmd_uninstall(args):
    removed = launchd.uninstall()
    if removed:
        ok("后台守护已卸载")
    else:
        warn("未找到已安装的守护任务")
    return 0


def cmd_logs(args):
    path = config.log_file()
    if not os.path.exists(path):
        dim("暂无日志：%s" % path)
        return 0
    if args.follow:
        os.execvp("/usr/bin/tail", ["tail", "-f", "-n", "40", path])
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    sys.stdout.write("".join(lines[-args.lines:]))
    return 0


def cmd_doctor(args):
    cfg = config.load()
    cli = PortalClient(cfg)
    print(BOLD + "\n环境自检\n" + RESET)
    print("  程序版本 ：%s" % config.APP_VERSION)
    print("  Python   ：%s (%s)" % (sys.version.split()[0], sys.executable))
    print("  配置目录 ：%s" % config.data_dir())
    print("  日志文件 ：%s" % config.log_file())
    print("  门户地址 ：%s" % cfg.status_url)
    print("  学号     ：%s" % (_mask(cfg.user_id()) if cfg.account else "(未配置)"))
    print("  运营商   ：%s" % config.CARRIER_NAMES.get(cfg.carrier, cfg.carrier))
    print("  门户账号 ：%s" % (_mask(cfg.portal_account()) if cfg.account else "(未配置)"))
    if cfg.account:
        pwd = keychain.get_password(cfg.portal_account())
        print("  钥匙串   ：%s" % ("已保存密码" if pwd else RED + "未找到密码" + RESET))
    print("  守护任务 ：%s" % ("已安装" if launchd.is_installed() else "未安装"))
    if launchd.is_installed():
        st = launchd.status()
        if st.get("loaded"):
            print("  运行状态 ：%s%s" % (st.get("state", "?"),
                                        "  (exit %s)" % st.get("last_exit", "")
                                        if st.get("last_exit") else ""))
        else:
            print("  运行状态 ：%s未载入%s" % (RED, RESET))
    print("  校园网   ：%s" % ("可达" if cli.tcp_probe(2.0) else "不可达（当前不在校园网）"))
    print("")
    return 0


# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="snnu-login",
        description="SNNU 校园网自动登录（macOS）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="首次使用：snnu-login setup",
    )
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("setup", help="首次配置（账号 / 密码 / 运营商）")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("login", help="立即登录一次")
    s.add_argument("--quiet", action="store_true", help="不输出过程")
    s.set_defaults(func=cmd_login)

    s = sub.add_parser("agent", help="静默模式（后台守护内部使用）")
    s.set_defaults(func=cmd_agent)

    s = sub.add_parser("status", help="查看在线状态")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("logout", help="主动下线")
    s.set_defaults(func=cmd_logout)

    s = sub.add_parser("install", help="安装后台守护")
    s.add_argument("--interval", type=int, default=0, help="兜底检查间隔（秒），默认 600")
    s.set_defaults(func=cmd_install)

    s = sub.add_parser("uninstall", help="卸载后台守护")
    s.set_defaults(func=cmd_uninstall)

    s = sub.add_parser("logs", help="查看运行日志")
    s.add_argument("-n", "--lines", type=int, default=30)
    s.add_argument("-f", "--follow", action="store_true")
    s.set_defaults(func=cmd_logs)

    s = sub.add_parser("doctor", help="环境自检")
    s.set_defaults(func=cmd_doctor)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except Exception as e:  # 兜底，保证 agent 模式不会崩出日志噪音
        log("未捕获异常 %s: %s" % (type(e).__name__, e))
        bad("出错：%s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
