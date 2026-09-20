# UFI-TOOLS for Linux

> UFI-TOOLS 的 **Linux 移植版**，面向 E5-LINUX 这类“Linux 手持终端 / 便携设备”架构：
> 把本软件安装在这台 Linux 设备上，同一局域网内的手机、平板、电脑打开 `http://<设备IP>:2333/`
> 就能用 UFI-TOOLS 的功能来**控制这台设备本身**——看状态、开关蜂窝数据、改 Wi-Fi 热点、
> 管理接入设备、执行 AT 指令、跑脚本、定时任务、插件与主题。

纯标准库 Python 3，无第三方依赖：镜像里只要有 `python3` 就能跑，一次 `apt upgrade` 不会把它跑坏。

## 与 Android 版的关系

Android 版的 UFI-TOOLS 是一个跑在设备本机的 Ktor 服务器，把宿主能力暴露成 REST API 再配一套静态
SPA。它的价值在**接口**，不在 Android。本移植保留接口，替换实现。

原版是给**中兴随身 WiFi** 写的，因此有两层东西必须分开看：

| | 处置 |
|---|---|
| **厂商协议层**：`goform` 反向代理、`AD` 防篡改签名、会话 Cookie、`zreq` 工具、厂商 `goformId` | **已删除**。E5 不是中兴设备，没有厂商后台可连；本移植不模拟它。 |
| **前端字段词表**：状态块轮询的 38 个字段名、Wi-Fi/客户端面板的数据形状 | **保留**，但值全部来自本机 `/proc`、`/sys`、systemd、hostapd、modem。这是一层命名翻译，不是厂商协议。 |

也就是说：`/api/goform/...` 这个路径名还在（前端硬编码了它），但它不再转发给任何厂商后台，
而是由本机的读取映射（`ufitools/uifields.py`）与动作路由（`ufitools/api/ui_compat.py`）直接作答，
写操作落到 `ufitools/control.py`。没有会话、没有签名、没有厂商服务。

## 架构

| Android | 本移植 | 模块 |
|---|---|---|
| `sendat`（`service call …IToolControl`） | `/opt/e5/e5-at`（E5 的 `e5-atd` 持有的 fifo） | `at.py` |
| `DeviceInfo`（`/proc`、`/sys`） | 同一批内核接口，逐字段同形 | `sysinfo.py` |
| `NetworkStatsManager` | 采样 `/sys/class/net/*/statistics/*_bytes`，按日累计并算速率 | `traffic.py` |
| 厂商 `goform` 控制 | systemd / hostapd / dnsmasq / sysfs | `control.py` |
| 厂商状态字段 | 本机真实数据的只读映射 | `uifields.py` |
| 厂商后台登录握手 | 仅登录用的本地兼容（无会话、无签名） | `api/ui_compat.py` |
| 厂商基带信号字段 | 只读 AT 命令的**缓存快照**（默认 60 秒一次） | `modem.py` |
| `ShellKano` / `RootShell`（socat socket） | `/bin/sh -c`（systemd 本身即 root） | `shell.py` |
| `SharedPreferences` | `<data_dir>/config.json` 与插件/主题/任务 JSON | `config.py`、`store.py` |
| Ktor `embeddedServer(CIO)` | `http.server.ThreadingHTTPServer` + 自研路由 | `httpd.py` |
| 前台 Service + `BootReceiver` | systemd unit | `systemd/ufi-tools.service` |
| APK 自更新、无线 ADB、APN、短信、NFC、锁频/锁小区 | 无对应物，明确报错而不是假装成功 | `api/ui_compat.py` |

### 为什么要给 AT 加缓存

信号、运营商、IMEI 这些字段只在 AT 之后，而 AT 是这台设备上**唯一不能被高频轮询**的资源：CP 会在
命令通道被高频使用后断言（`MN_AL Task PS CP assert ... queue was full`），这正是 E5-LINUX 让
`e5-atd` 独占并串行化 AT 通道（单持有者、一次一条）的原因。而 Web 界面每秒轮询一次状态块。

两者用 `ModemSnapshot` 调和：请求只读缓存，后台线程按 `at_poll_interval`（默认 60 秒）刷新一次，
因此界面保持 1 Hz，而 modem 每分钟最多看到一轮只读命令。把 `at_poll_interval` 设为 0 则完全不用 AT，
相关字段留空。

---

## 安装与运行

### 源码目录直接跑

```sh
cd UFI-TOOLS/linux
./bin/ufi-tools --data-dir /tmp/ufi-tools status     # 看每个桥接是否就绪
./bin/ufi-tools --data-dir /tmp/ufi-tools serve --port 2333
```

Web 前端是本仓库的 `linux/www/`（纯静态文件，无构建步骤：Android 那套 `npm build` 是为了把
产物打进 APK，Linux 端直接提供源文件即可）。
浏览器打开 `http://<设备IP>:2333/`，默认口令 `admin`（会被判为弱口令，请立即改）。

### 安装到设备

```sh
sudo ./install.sh                       # 安装 + 生成随机口令 + 注册并启动 systemd 服务
sudo ./install.sh --no-systemd          # 只复制文件
sudo ./install.sh --token 'MyPass123'   # 指定口令
```

安装位置：`/usr/lib/ufi-tools`（代码）、`/usr/bin/ufi-tools`、`/usr/bin/ufi_req`、
`/usr/share/ufi-tools/www`（前端）、`/usr/share/ufi-tools/www-linux`（内置 shim）、
`/var/lib/ufi-tools`（数据，0700）、`/etc/systemd/system/ufi-tools.service`。

```sh
systemctl status ufi-tools
journalctl -u ufi-tools -f
```

### 命令行工具

```sh
ufi-tools status                     # 各子系统状态（AT/热点/蜂窝/性能/指示灯）
ufi-tools clients                    # 当前接入的无线客户端
ufi-tools at AT+CSQ                  # 走已配置的 AT 通道发一条指令
ufi-tools set-token 'NewPass123'     # 运行中也能立即生效（2 秒内热加载）

ufi_req -e /api/linux/overview       # 自动用本机已存口令签名
ufi_req -X POST -e /api/linux/power -d '{"action":"reboot"}'
ufi_req -X POST -e /api/linux/hotspot -d '{"ssid":"E5-Lab","psk":"abcdefgh","channel":"36"}'
```

---

## 这台设备上能做什么

`说明` 一列写清每个功能背后的真实机制，避免“按钮能点但没作用”。

| 功能 | 状态 | 说明 |
|---|---|---|
| 设备总览：CPU/内存/温度/电量/存储/开机时长 | ✅ | `/proc`、`/sys`；`GET /api/linux/overview` 一次取全 |
| 连接数、USB 设备树、SELinux 状态 | ✅ | `/proc/net/*`、`/sys/bus/usb`、`/sys/fs/selinux` |
| 蜂窝信号 / 运营商 / 网络制式 / IMEI / IMSI / ICCID | ✅ | 只读 AT，60 秒缓存（`at_poll_interval`） |
| 日/月流量统计与实时速率 | ✅ | 网卡计数器按日累计，速率由相邻采样差算得 |
| 数据连接开关 | ✅ | `systemctl start/stop e5-mobile-data.service` |
| Wi-Fi 热点开关 | ✅ | `systemctl start/stop e5-hotspot.service` |
| 改热点 SSID / 密码 / 信道 / 最大接入数 / 隐藏 SSID | ✅ | 写入 `<data_dir>/hostapd-managed.conf` 并重启热点 |
| 接入设备列表（含主机名、IP、MAC） | ✅ | `iw station dump` + `ip neigh` + dnsmasq 租约合并 |
| 黑白名单（按 MAC） | ✅ | 写 hostapd MAC 列表并重启热点 |
| 重启 / 关机 | ✅ | `systemctl reboot` / `poweroff` |
| 定时重启 | ✅ | 后台调度线程按 `restart_time` 执行 |
| 性能模式 | ✅ | 写 cpufreq `scaling_governor` |
| 指示灯开关 | ✅ | 写 `/sys/class/leds/*/{trigger,brightness}`（本机没有可控 LED 时明确报错） |
| AT 指令终端 / 快捷指令 | ✅ | 原样可用，走 `e5-at`（由 `e5-atd` 转发） |
| 高级功能 / Root Shell / TTYD | ✅ | 开关高级功能即启停 `ttyd.service`；root shell 受该开关约束 |
| 内网测速、流量测速 | ✅ | 本地 8 MiB 随机块；蜂窝测速经 `/api/proxy` 拉取外部文件 |
| 定时任务 | ✅ | 动作为「执行命令」或「转发消息」；旧的 `goformId` 动作仍被路由到本机控制 |
| 短信/状态转发（SMTP、CURL、钉钉） | ✅ | 转发通道完整可用；占位符与 Android 版一致 |
| 流量管理（阈值、提醒、手动校准） | ✅ | 阈值与提醒持久化，校准直接改当日计数 |
| 插件、主题、多语言、上传图片 | ✅ | 与 Android 版同容量限制（5 MiB / 10 MiB） |
| 文件共享（SMB） | ⚠️ | 仅在配置了 `samba_unit` 时可用；未配置时界面隐藏该入口 |
| 内网地址 / DHCP 范围修改 | ⚠️ | 只读展示；地址归 `systemd-networkd`、地址池归 dnsmasq，请改 `/etc/systemd/network` 与 `dnsmasq.d` |
| 收发短信、短信列表 | ❌ | 本机没有短信栈（E5-LINUX 尚未接 RIL）；转发功能不受影响 |
| APN 编辑 | ❌ | 请用 `AT+CGDCONT`（界面隐藏该入口） |
| 锁频段 / 锁小区 / 网络模式强制 | ❌ | 需要厂商基带命令；用 AT 终端自行下发（界面隐藏该入口） |
| USB 调试 / 无线 ADB 自启 | ❌ | Android 专有（界面隐藏该入口） |
| 软件更新（APK） | ❌ | Linux 端请用 apt 或整包替换（界面隐藏该入口） |
| 改厂商后台密码 | ❌ | 不存在厂商密码；请用 `ufi-tools set-token`（界面隐藏该入口） |
| NFC、SIM 卡切换 | ❌ | 本机没有 NFC / 只有一张卡 |

---

## 前端适配（内置 shim）

上游 Web 界面是为中兴设备写的：登录要填厂商密码，功能列表里有一堆 Linux 上不存在的入口。
本移植**不改上游前端源码**，而是由后端在返回 `index.html` 时注入 `www-linux/ufi-linux-shim.js`
（同时作为静态覆盖层提供）。shim 做三件事：

1. **让登录只需 UFI-TOOLS 口令**：自动填好并隐藏“厂商后台密码”输入框。
2. **藏掉做不到的入口**：`ADB`、`ADB_NET`、`APNManagement`、`CHANGEPWD`、`LANManagement`、
   `NFC`、`OTA`、`SMS`（有 `samba_unit` 时保留 `SMB`）。
3. **加一个「E5 控制台」浮层按钮**：本机概览、蜂窝数据开关与速率、热点开关与 SSID/密码/信道表单、
   接入设备列表、性能模式、指示灯、重启/关机。它调用的是原生 `/api/linux/*`。

也可以关掉：`ui_shim = false`。此时前端原样提供（登录会因缺少厂商后台而不可用，只有原生 API 可用）。

### 热点配置为什么写进数据目录

E5-LINUX 的 initramfs overlay 每次启动都会覆盖 `/etc`，因此 `/etc/hostapd/e5.conf` 这种
**在 baked overlay 里**的文件改了等于没改。本移植把改动写到 `<data_dir>/hostapd-managed.conf`，
并（当 `/opt/e5/hotspot-start.sh` 存在时）写一个指过去的 `e5-hotspot.service.d` drop-in；
这两条路径都不在 overlay 里，所以能扛过重启。

---

## 配置速查

配置在 `<data_dir>/config.json`（`UFI_TOOLS_DATA` 决定目录，默认 root 下为 `/var/lib/ufi-tools`）。
外部修改会在 2 秒内被热加载。

| 键 | 默认值 | 说明 |
|---|---|---|
| `login_token` | `sha256("admin")` | 后台口令的哈希；`authorization` 头需与之一致 |
| `login_token_enabled` | `true` | 设为 false 则完全关闭鉴权（仅限受控环境） |
| `kano_max_skew_ms` | `0` | 0 表示不校验时间戳偏差（与 Android 版一致）；需要防重放时设为如 60000 |
| `bind` / `port` | `0.0.0.0` / `2333` | 监听地址与端口 |
| `at_socket` | 空 | 旧部署的 socket 通道；本镜像不用 |
| `at_device` | 空 | 直开 tty 的回退；默认不用（tty 只能有一个持有者） |
| `at_command` | `/opt/e5/e5-at {cmd}` | E5 的 AT 客户端（由 `e5-atd` 转发） |
| `at_poll_interval` | `60` | modem 派生态的刷新间隔（秒）；0 = 完全不用 AT |
| `mobile_data_unit` | `e5-mobile-data.service` | 蜂窝数据控制目标 |
| `hotspot_unit` | `e5-hotspot.service` | 热点控制目标 |
| `wlan_interface` | `wlan0` | 热点网卡（也用于客户端列表） |
| `hotspot_conf` / `hotspot_conf_2g` / `hotspot_conf_5g` | `/etc/hostapd/e5.conf` | 热点基线配置 |
| `dnsmasq_conf` | `/etc/dnsmasq.d/e5-hotspot.conf` | 只读，用于展示 DHCP 地址池 |
| `traffic_interfaces` | 空（自动取默认路由网卡） | 流量统计口径 |
| `led_names` | 空 | 逗号分隔的 `/sys/class/leds` 名字白名单；空表示自动 |
| `samba_unit` | 空 | 配置文件共享；留空则界面隐藏该入口 |
| `ttyd_unit` | `ttyd.service` | 高级功能对应的终端服务 |
| `ui_shim` | `true` | 是否注入前端 shim |

## 接口一览

除 UI 兼容层外，本移植提供一组**原生**端点（鉴权同 UFI-TOOLS 口令）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/linux/overview` | 本机概览：内存/温度/电量/流量/蜂窝/热点/客户端/性能/指示灯/modem |
| POST | `/api/linux/power` | `{"action":"reboot"｜"poweroff"}` |
| GET/POST | `/api/linux/mobile-data` | 查询或设置 `{"enabled":true/false}` |
| GET/POST | `/api/linux/hotspot` | 查询；或设置 `{"enabled":...}` / 配置 `{"ssid","psk","channel","max_clients","hidden","AuthMode"}` |
| GET | `/api/linux/hotspot/clients` | 接入设备列表 |
| POST | `/api/linux/hotspot/access` | `{"mode":"allow"｜"deny","macs":[...]}` |
| GET | `/api/linux/lan` | 内网地址、掩码、DHCP 地址池（只读） |
| GET/POST | `/api/linux/performance` | 查询或设置 `{"performance":true/false}` |
| GET/POST | `/api/linux/led` | 查询或设置 `{"enabled":true/false}` |
| POST | `/api/linux/samba` | `{"enabled":true/false}`（需配 `samba_unit`） |
| POST | `/api/linux/traffic/calibrate` | `{"bytes":<n>}` 校准当日计数 |
| GET | `/api/linux/ui_compat` | 列出兼容层支持与不支持的动作 |
| GET | `/api/platform` | 诊断：内核、AT 后端、modem 快照年龄、路径等 |

UI 兼容层（前端使用，`ui_shim=true` 时启用）：`/api/goform/goform_get_cmd_process`（`cmd=<字段>`）、
`/api/goform/goform_set_cmd_process`（`goformId=<动作>`）。它**不转发任何流量**，
字段来自 `uifields.py`，动作经 `control.py` 落到 systemd/hostapd/sysfs。

## 测试

```sh
cd UFI-TOOLS/linux
make test      # 148 个用例，仅用标准库 unittest
```

覆盖：签名向量（与 Android/JS/Go 四个实现逐位一致，向量由 Node 原生 `crypto` 独立生成）、
`/proc`/`/sys` fixture 上的设备信息、atd socket 与真实 pty 的 AT 通道、modem 解析与缓存节流、
hostapd 配置解析/渲染/加密模式映射与 MAC 名单、流量分桶与速率、配置热加载与口令轮换、
以及一个真起 HTTP 服务的端到端层（shim 注入、登录握手、字段映射、动作路由、
不支持动作的明确报错、已移除端点的 404、静态资源、上传、任务、限速与 SSRF 拦截）。

## 安全

* **服务以 root 运行**：它需要驱动 systemd、hostapd、sysfs 与基带设备。访问控制依赖 UFI-TOOLS 口令，
  请勿把 2333 端口直接暴露到公网（远程请用插件商店里的 EasyTier / Tailscale）。
* 默认口令会被标记为弱口令；`install.sh` 默认生成 16 位随机口令。
* `/api/proxy/--<url>` 保留 SSRF 拦截：环回、链路本地、RFC1918 一律拒绝，只有显式配置的目标可出网。
* 时间戳偏差校验默认关闭（与 Android 版一致），需要时可设 `kano_max_skew_ms`。

## 已知缺口

* `self` 形态之外没有别的形态：本版本只管理本机，不管理远端热点（那是被删掉的厂商反代）。
* 内网地址与 DHCP 地址池只读；改动请落到 `/etc/systemd/network/*.network` 与 `/etc/dnsmasq.d/*`。
* 热点二维码：厂商是服务端渲染 PNG，本移植返回一张透明占位图（`/api/linux/placeholder.svg`），
  面板不会显示破图，但也不能扫码入网。
* 锁频/锁小区、APN、网络模式强制没有做，因为需要厂商基带命令；这些入口在界面上被隐藏，
  API 上保留明确报错。若后续确认 E5 modem 的对应 AT 命令，可在 `ui_compat._dispatch` 里补上。

