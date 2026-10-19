# SNNU 校园网自动登录（非官方 macOS 版）

连上陕西师范大学校园网时，自动完成门户认证，无需打开浏览器点登录。

```
连上 SNNU 无线网 ──► launchd 感知网络变化 ──► 探测门户 ──► 已在线？──► 结束
                                                        └─ 未登录 ──► 提交认证
```

> **非官方声明**
>
> 本项目是个人开发的第三方工具，**与陕西师范大学及其网络信息中心、校园网服务提供方
> 没有任何隶属、合作或授权关系**，也未获得其背书。
>
> 项目中出现的「陕西师范大学」「SNNU」「snnuportal」「深澜」等名称，仅用于说明本工具
> 所适配的校园网认证系统；相关名称与商标归各自权利人所有。
>
> 本项目不包含、不修改、不分发学校的任何专有软件、页面资源或校徽标识。

## 特性

- **零第三方 Python 依赖**：只用标准库，不需要 `pip install`
- **无需打包成 App**：纯脚本 + launchd，不会有二进制被安全软件误报的问题
- **密码存 macOS 钥匙串**：不写进任何配置文件
- **连上就登录**：监听系统网络配置变化，每次连网都会触发
- **失败退避**：连续失败后进入冷却，不会反复试密码把账号试锁
- **单条命令自检**：`snnu-login doctor` 一次看清账号、钥匙串、守护、连通性

## 与 Windows 原版的关系

本项目的协议分析与登录判定逻辑移植自 [SNNU-campus-autologin（Windows 版）](https://github.com/mzh2077/SNNU-campus-autologin)，
并在此基础上做了 macOS 平台适配与协议修正。详细来源与衍生范围见文末
[致谢与来源说明](#致谢与来源说明attribution)。

保留的关键判定规则（都是踩坑换来的）：

- 门户对非浏览器 UA 返回 **403** → 请求统一伪装 UA。
- 已在线时**任何**登录请求都会显示「已在线」→ 必须核验页面上的账号是否等于目标账号，
  否则会把密码错误误判为登录成功。
- 状态页编码 GB2312 → 用 `gb18030` 解码。

### 实测修正的 4 个协议问题

上游版本在此门户上会误报「密码错误」，实测后确认是 4 个协议细节：

| # | 上游做法 | 实测真相 |
| --- | --- | --- |
| 1 | POST 到 `login.jsp` | 登录页 `<form action="login">`，必须 POST **`login`**；打 `login.jsp` 只会拿回登录页，看起来像密码错误 |
| 2 | 每次请求新建连接、无 Cookie | 必须先 **GET 状态页拿到 JSESSIONID**，再带会话 POST，否则门户拒登 |
| 3 | `account` 填 `学号@mobile` | `account` 只能填**纯学号**，运营商用 `yys=mobile` 单独传；两者都带会触发「登录失败:开通代理业务失败」 |
| 4 | 全站按 GB2312 解码 | 状态页是 GB2312，而 `login` 的失败提示是 **UTF-8**；统一按 GB2312 解会变成「鐧诲綍澶辫触」乱码 |

第 4 点改为「先严格 UTF-8，失败再 GB18030」；第 3 点新增 `PROXY_FAILED` 状态，
不再把它含糊地报成密码错误。

## 安装

需要 macOS + 系统自带 Python 3（`/usr/bin/python3`，无需 pip）。

```bash
git clone https://github.com/luohwdyx2/snnu-campus-autologin-macos.git
cd snnu-campus-autologin-macos
bash install.sh          # 或双击 install.command
```

安装脚本做三件事：

1. 复制程序到 `~/Library/Application Support/SNNUAutoLogin/app`
2. 创建命令 `~/.local/bin/snnu-login`（`/usr/local/bin` 可写时优先放那里）
3. 写入 LaunchAgent `local.snnu-autologin.agent.plist`

> **注意**：`launchctl bootstrap` 只允许在真实「终端」中执行。
> 如果安装时提示「任务描述已写入，但未能载入 launchd」，
> **双击 `enable-agent.command`** 即可完成启用（会打开一个终端窗口跑完自动关闭）；
> 也可以手动执行 `~/.local/bin/snnu-login install`。
>
> 即使不做这一步，任务也已写入 `~/Library/LaunchAgents`，下次登录 macOS 后自动生效。

## 配置账号

```bash
~/.local/bin/snnu-login setup
```

向导会询问：

- **学号**：只填学号，如 `2024XXXXXX`。当前已在线的话会自动检测出来作为默认值。
- **网络服务商**：1 移动 / 2 联通 / 3 电信 —— 对应门户的 `yys` 字段。
  > 学号和后缀必须分开填。填成 `2024XXXXXX@mobile` 会被门户判定为
  > 「开通代理业务失败」，那不是密码错误。
- **密码**：输入时不回显，直接存进钥匙串，**不写任何文件**。

若当前已在线，向导会跳过密码校验（能上网即说明凭据有效）；不在校园网时也会跳过，
等下次连上校园网自动登录。

> `snnu-login` 提示 command not found 时，用完整路径 `~/.local/bin/snnu-login`，
> 或加入 PATH：`echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc`

## 日常使用

```bash
snnu-login            # 帮助
snnu-login login      # 立刻登录一次
snnu-login status     # 是否在线 / 账号 / 内网 IP / 登录时间
snnu-login logout     # 主动下线
snnu-login logs -f    # 跟踪后台日志
snnu-login doctor     # 环境自检
```

平时**不需要**手动执行任何命令：连上校园网 → 几秒内自动完成登录。

## 自动触发是怎么实现的

`~/Library/LaunchAgents/local.snnu-autologin.agent.plist`：

| 键 | 作用 |
| --- | --- |
| `RunAtLoad` | 登录 macOS 后立刻试一次 |
| `WatchPaths` | 监听 `/Library/Preferences/SystemConfiguration` 与 `/var/run/resolv.conf`；**连 WiFi / 插网线 / DHCP 续约都会改动它**，从而触发一次登录 |
| `StartInterval = 600` | 每 10 分钟兜底一次，防止会话被校园网静默踢掉 |
| `ThrottleInterval = 30` | 两次触发至少间隔 30 秒，避免网络抖动刷屏 |
| `ProcessType = Background`、`Nice = 5` | 低优先级，不抢前台资源 |

每次触发的执行流程（`snnu-login agent`）：

1. **快速探测门户 IP 的 TCP 端口**（2 秒超时）——不在校园网就立刻退出；
2. 刚连上 WiFi 时网关可能未就绪，会**最多等 45 秒**（每 3 秒探测一次）；
3. 查状态页：已在线且账号一致 → 结束（只发 1 个请求）；
4. 未登录 → 提交认证 → 回查核验；
5. 全程静默，不弹窗、不闪窗口。

**失败退避**：连续 3 次「密码错误 / 验证码 / 限速 / 运营商出口失败」后进入 30 分钟
冷却，降低账号被锁定的概率。

## 文件位置

```
~/Library/Application Support/SNNUAutoLogin/
├── app/                     # 程序本体（覆盖升级不影响配置）
│   ├── run.py
│   ├── LICENSE / NOTICE
│   ├── bin/snnu-login
│   └── snnu_autologin/
│       ├── config.py        # 端点、字段、关键词、超时 —— 门户改版只改这里
│       ├── portal.py        # 认证逻辑
│       ├── keychain.py      # 钥匙串读写
│       ├── launchd.py       # LaunchAgent 生成/载入
│       └── cli.py           # 子命令
├── settings.json            # 学号、运营商等（不含密码，权限 600）
└── state.json               # 失败次数/时间，用于冷却（权限 600）

~/Library/Logs/SNNUAutoLogin.log                    # 日志（权限 600，超 1MB 自动轮转）
~/Library/LaunchAgents/local.snnu-autologin.agent.plist
```

## 卸载

```bash
bash uninstall.sh           # 只卸载后台守护，保留配置和密码
bash uninstall.sh --purge   # 连同配置、日志、钥匙串条目一起清除（会二次确认）
```

> 若你此前装过其他版本的同类工具，注意 `--purge` 只清理本版创建的
> `local.snnu-autologin.agent` 任务与对应目录；其他版本请用其自带的卸载脚本处理。
> 同一台机器**不要同时安装两个版本**，否则两个后台任务会互相竞争登录。

## 安全说明与已知限制

本工具确实处理你的账号密码，请先了解下面几点再决定是否使用：

1. **门户是 HTTP 明文**。学校门户目前是 `http://`，登录请求在网络链路上没有 TLS
   保护。这是门户本身的限制，客户端无法改变。请仅在可信的校园网内使用，
   公共 Wi-Fi 下不要运行。
2. **密码会短暂出现在进程列表**。写入钥匙串时，密码作为 `security` 命令的参数传入，
   同机进程在毫秒级窗口内可能看到。这是 macOS 命令行工具的限制；
   共享电脑上不建议使用。
3. **日志含账号与内网 IP**。程序已做掩码（学号 `2024****01`、内网 IP `10.138.*.*`），
   但分享日志前仍建议再检查一遍。
4. **不改系统网络设置**、不安装内核扩展、不代理流量，只发 HTTP 表单请求。
5. **不做验证码识别**。门户要求验证码时程序直接停止并提示手动登录。

## 合规与风险提示

本项目是一个**本地自动化脚本**，其行为仅限于：使用你本人提供的学号和密码，
向学校官方门户提交一次正常的登录表单，以及在已登录时查询在线状态。

- 本项目**不包含**任何漏洞利用、破解、抓包重放、验证码识别、限速绕过或计费规避功能。
- 本项目**不收集、不上传**任何数据；账号保存在本地 `settings.json`（不含密码），
  密码保存在 macOS 钥匙串。
- 请仅在你**本人已合法开通**的校园网账号上使用，不要用于代他人登录、账号共享、
  多设备绕过终端数限制等用途。
- 自动化登录**可能违反学校校园网使用协议或管理规定**。是否允许使用，
  请以学校网络管理部门的规定为准；如收到校方通知，请立即停止使用并卸载。
- 「每 10 分钟保活」会让会话在无人使用时也保持在线；按时长计费的套餐
  可能因此产生额外费用，请自行评估。
- 使用本工具可能带来的后果（包括但不限于账号被临时锁定、被暂停上网权限、
  产生的费用）由使用者自行承担。

> 本项目按 MIT 许可「按原样」提供，不对可用性、安全性或特定用途适用性作任何担保。
> 作者不是律师，以上内容不构成法律意见。

## 常见问题

**Q：日志显示「跳过：非校园网环境」**
A：门户 IP 不可达——还没连上 SNNU 校园网，或连的是其他网络。属正常跳过。

**Q：报「运营商出口开通失败」/「开通代理业务失败」？**
A：`account` 里混进了 `@运营商`。学号与运营商必须分开：`settings.json` 中 `account`
只放学号，`carrier` 放 `mobile`/`unicom`/`telecom`。另外要确认自己办的是哪家运营商的套餐。

**Q：已在线但打不开网页？**
A：可能是多设备/多账号会话。用 `snnu-login status` 看内网 IP 与账号，
必要时先在浏览器里退出该账号，再 `snnu-login login`。

**Q：改了密码？**
A：重跑 `snnu-login setup` 覆盖钥匙串里的旧密码。注意：若当时已在线，
向导会跳过密码校验，新密码会在下次真正登录时才被验证。

**Q：会泄露密码吗？**
A：密码只保存在本机钥匙串，不写入项目文件，也不会上传到任何第三方服务器。
但请了解两个客观限制：

1. 学校门户目前使用 **HTTP**，登录请求在网络链路上没有 TLS 保护（门户限制，无法改变）。
2. 写入钥匙串时，密码会作为 `security` 命令参数短暂出现在本机进程列表中（毫秒级）。

除此之外，本工具不与任何第三方通信。

**Q：门户地址变了 / 学校换系统了？**
A：改 `app/snnu_autologin/config.py` 里的 `status_url`、`alt_user_field`、
`alt_pass_field`、`alt_yys_field`、`online_markers`、`error_markers`。
其他学校复用建议 fork 后改这一个文件。

**Q：为什么不像 Windows 那样做成 exe？**
A：macOS 没有 exe 生态，也不需要打包——纯 Python 标准库 + launchd 才是原生做法，
还顺带避免了 PyInstaller 被杀毒软件误报的问题。

## 致谢与来源说明（Attribution）

本项目的协议分析与登录逻辑移植自以下开源项目：

- **上游项目**：SNNU 校园网自动登录（Windows 版）
- **仓库**：<https://github.com/mzh2077/SNNU-campus-autologin>
- **版权**：Copyright (c) 2026 校园网自动登录工具贡献者
- **许可**：MIT License

### 衍生自上游的部分

| 本仓库文件 | 上游对应文件 | 说明 |
| --- | --- | --- |
| `snnu_autologin/portal.py` | `portal_client.py` | 门户请求、状态判定、错误分类、账号一致性核验的整体结构与大部分判定逻辑 |
| `snnu_autologin/config.py` | `config.py` | 端点、字段名、运营商取值、超时、状态关键词表等配置项及默认值 |

具体包括：状态码常量与提示文案、`online_markers` / `error_markers` 关键词表、
状态页解析正则、账号一致性核验逻辑、浏览器 UA 伪装、备用端点字段定义。

### 本项目新增或修正的部分

- **macOS 平台集成**：`keychain.py`（钥匙串凭据存储）、`launchd.py`（LaunchAgent
  自启与网络变化触发）、`cli.py`（子命令与失败退避），以及全部安装/卸载脚本。
- **协议修正**（基于在陕西师范大学校园网上的实测）：
  1. 登录提交端点由 `login.jsp` 改为表单真实 action `login`；
  2. 增加 `JSESSIONID` 会话保持（`CookieJar`）；
  3. `account` 只提交纯学号，运营商改用 `yys` 单独提交；
  4. 响应解码改为「先严格 UTF-8，失败再 GB18030」，并新增 `PROXY_FAILED` 状态。
- **工程改动**：数据目录改为 `~/Library/Application Support`、日志轮转与掩码、
  失败冷却、`doctor` 自检等。

上游作者与本项目作者均**未对本项目作出任何背书**。

## 关于 AI 辅助开发

本项目在开发过程中使用了 AI 编程助手，主要用于：协议分析材料的整理、代码初稿与重构、
文档与注释撰写。

所有 AI 生成的代码在合并前均经过人工审阅，并在真实校园网环境中实际运行验证；
协议行为以实测结果为准，不以 AI 输出为准。项目的架构决策、实测结论与最终代码由
维护者负责。

## 许可

本项目以 **MIT License** 发布，完整文本见 [`LICENSE`](LICENSE)。

- 上游项目版权：Copyright (c) 2026 校园网自动登录工具贡献者
- 本项目修改部分版权：Copyright (c) 2026 luohwdyx2

你可以自由使用、修改、再分发本项目，但需在副本中保留上述版权声明与 MIT 许可全文。
第三方名称与商标的说明见 [`NOTICE`](NOTICE)。

## 贡献

欢迎 Issue 与 PR。提交前请确认：

1. 不要提交任何真实学号、密码、日志、`settings.json` 或 `state.json`；
2. 涉及认证逻辑的改动，请说明实测环境与依据；
3. 提交即表示你同意以 MIT License 授权你的贡献，并确认你有权提交该内容。

安全问题请按 [`SECURITY.md`](SECURITY.md) 的渠道私下报告，不要在公开 Issue 贴凭据。

## 运行环境

- macOS（使用系统自带 `/usr/bin/python3`，**无需 `pip install`**）
- 除 Python 标准库外无第三方依赖；本仓库不捆绑 Python 解释器
- 依赖系统自带命令：`security`、`launchctl`、`rsync`、`bash`
