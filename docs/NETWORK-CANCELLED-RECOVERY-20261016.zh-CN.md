# E5 注册变化后拨号取消，WAN 停止自动连接

2026-10-16。实机为 E5，内核
`6.18.54-e5-release20261016-g020b970e351e-dirty`，ModemManager r935。

## 实机证据

22:10:20～22:10:30，接入技术在 LTE / NR 之间变化，注册状态两次从 home
进入 registering / emergency-only。原连接断开后，现有 connection dispatcher
重启 WAN；第二次连接被 ModemManager 以 `Error.Core.Cancelled` 取消。

netifd 的重试分类没有包含这种取消，走 `MM_CONNECT_FAILED` 和
`proto_block_restart`，清除了 autostart，随后 teardown 禁用了模组。
检查时 WAN 为 up=false、available=true、autostart=false，模组为 disabled。
已有事件恢复服务正常运行，但按用户意图保护规则不会重新开启 autostart=false
的接口。界面显示未连接符合真实状态；不是本机缺少 WWAN 驱动。

日志证实注册丢失与取消的时序，尚不能解释网络侧最初为何进入 emergency-only。

## 修改

在已有 SIPC 拨号退避中处理 `Core.Cancelled`：读取 ModemManager 的缓存状态，
仅 enabled / searching / registered / connecting 允许继续原有退避。
随后按用户要求将暂时失败等待调整为 1 / 3 / 5 / 7 秒无限循环；无覆盖依旧等待
现有 PS 注册事件，不在无信号时启动新的循环搜网机制。
disabled、disabling、failed、locked、未知状态或读取失败不会自动重试。
手动 ifdown 仍由原 TERM/INT 处理退出并终止子进程，不因本次分类重新开启网络。

共用实现位于 `devices/t551m/network-startup.py`，E5 / T551M / M8 构建和 APK
安装钩子均使用它。包修订标识升为 E5REV=28。没有新增服务、轮询或正常启动等待，
没有修改 AT 顺序、开机回放、频段、工作模式、SIM 或 NV。

## 验证与部署

- 13 项 network-startup 回归通过，包含一次取消后重试成功、状态读取失败、禁止
  恢复的模组状态、三机共享、补丁幂等，以及手动终止命令/退避的子进程清理。
- 本机通过正常 `ifup wan` 恢复，注册 home、PS attached、模组 connected，
  已获取 IPv4 和运营商 DNS。绑定 sipa_eth0 的三次外网 ping 全部成功。
- 已校验并替换本机 netifd 协议脚本，后续 setup 使用新版；没有重启网络服务、
  模组服务或机器。原脚本保存在
  `/root/update-backups/network-cancelled-20261016/modemmanager.sh`。
- 热部署文件 SHA-256：
  `6fd32934849bfe14211b8c95f8bae97bae30898036bdcbcca183b410470529d5`。
  此值为首次取消错误修复；循环间隔调整后的部署校验值另记于本节末。
- 取消路径通过受控回归验证，没有主动制造实机注册丢失来复现。
  T551M / M8 尚未部署，本次未编译或更新产物包。

### 1 / 3 / 5 / 7 秒循环部署

用户最终确认保留无信号时的原厂对照事件恢复，只调整可重试失败的等待序列。
公共源码及 E5 热部署均已完成，文件 SHA-256：
`ccf07249c02ad32a5a089c95d788841c7f968d5beb7f393b4a30f5a88ce71ab7`。
前一版保存在 `/root/update-backups/network-backoff-1357-20261016/modemmanager.sh`。

13 项启动回归和 9 项注册事件恢复回归通过。测试包含三次完整间隔循环；
无覆盖等待注册事件、手动 ifdown、PIN / 鉴权等条件继续按既有规则处理。
热部署只原子替换协议脚本，未重启服务或断开当前连接；WAN 仍为 up=true，
蜂窝外网三次 ping 均成功。新版在后续 setup / 重连时加载。
等待间隔是上一次命令失败后的空闲时间，不代表每次拨号总耗时最多 7 秒。
本次未编译打包，也没有用实机连续失败测试来判断运营商是否限流。

### 按原始故障时序追加回归

进一步检查发现，取消错误返回后查询状态可能正好处于 `disconnecting`，而初版只
允许 enabled / searching / registered / connecting，会把这个承载回收中间态
当成不可重试。现将 enabling / disconnecting / connected 一并纳入取消后的可恢复
状态。`WrongState` 仅在 enabling / connecting / disconnecting 中间态允许重试，
正常 registered/attached 下的其他 WrongState 仍返回错误，避免扩大错误白名单。

取消时若已经 searching 或 PS detached，则交回既有注册事件等待，保留自动连接意图，
不在无信号时循环重新搜网。disabled / disabling / failed / locked / 状态读取失败
仍不被当成允许拨号；手动终止 setup 会停止命令与等待子进程。

新增测试提取真实 setup 里的 connect 失败出口，串联错误分类、等待、重试、
proto_block_restart / proto_set_available，覆盖原始 registered 取消和新增中间态。
14 项启动回归及 9 项事件恢复回归通过；取消后的退避等待也测试了 SIGTERM 清理。

E5 自身 BusyBox ash 另通过 6 组受控回放：Cancelled + registered、disconnecting、
connected 均继续重试成功；WrongState + disconnecting 继续重试；Cancelled +
searching/detached 仅等待注册；Cancelled + disabled 停止。回放将 mmcli 和 netifd
通知替换为测试函数，没有调用真实 AT、修改真实 WAN 状态或模拟真实射频失网。

已热部署最新版，SHA-256：
`468493d35a96d671cbf22216844638ac73cc5d6abbc41ed8bf853fd8b02b8888`。
前一版位于 `/root/update-backups/network-cancelled-states-20261016/modemmanager.sh`。
验证时 WAN up=true、autostart=true、模组 connected、PS attached，蜂窝外网三次
ping 全部成功。完整无线环境下同一时序尚未再次自然复现，不能写成已经验证所有
运营商／所有注册变化均不会掉线。
