# 蜂窝移动过程中的地址更新与连接恢复

适用于公共 Unisoc ModemManager 拨号链路，E5、T551M、M8 共用。

## 原因与原厂依据

当前 ModemManager 的通用 `CGEV` 分支忽略 `NW MODIFY`，netifd 原协议只在
拨号成功时读取一次静态 IPv4 配置。因此 PDP 保持激活、网络在移动过程中更换
IP/DNS 时，Linux 仍可能使用旧地址。另一个独立问题是短暂失去注册状态后，
ModemManager 原来的 15 秒保护可能过早断开仍有效的数据承载。
这些是已确认的实现缺口，不能据此判定所有移动掉线或低速都由它们造成。

T551M 原厂 `libimpl-ril.so`（SHA256
`142e7467f86dd484b7e20e3bfc2780b5132821661e0980c38b4e478dacd67630`）
中，`processDataUnsolicited` 的 `0x430b8` 比较原因码 8，随后调度
`0x40d1c` 的回调。该回调通过 `0x5d8a0` 的 PLT 调用
`requestOrSendDataCallList`。配套 RIL 源码将这个原因码明确说明为 IP change。
这条通知路径本身没有发送 CFUN 或 CGACT 重置命令。
`SPPCODATA` 是 PCO 更新通知，也作为重新读取配置的提示处理。

## 本次实现

- Unisoc 插件观察 `CGEV` 和 `SPPCODATA`，非阻塞写入 netifd 监视器的 FIFO；
  ModemManager 保留原有 detach/deactivate 处理。
- SIPC 静态 IPv4 承载启动一个由 netifd 管理的监视器，事件合并后通过
  ModemManager 的 AT 命令队列读取 `CGACT`、`CGCONTRDP`，不另占 AT 端口。
- 地址变化时先加入新 IP，再更新 netifd 的地址、路由及 DNS，最后移除旧 IP。
  更新使用完整替换快照，避免 `keep=1` 累积旧地址/DNS；路由由 netifd 按
  metric、策略表、defaultroute 和 peerdns 配置处理，不强插主路由表默认路由。
  独立 DHCPv6 接口继续由原 IPv6 协议管理。地址配置失败时保留旧快照用于重试。
- 每 30 秒进行一次低频一致性检查，覆盖漏报事件；配置未变时不更新网络。
- AT 失败或空响应不等于上下文失活，保持现有连接；明确失活连续确认约
  6 秒后交回 netifd 的重连流程。
- Unisoc 的注册丢失保护调整为 45 秒，通用 modem 仍为 15 秒；真实
  CGEV 断开通知及现有 CGACT 监测仍有效。
- 兼容 `NW ACT 11,17`、`NW ACT 11,18` 缺少第三字段的通知，默认 event type 0。
- MU300 的既有续租监视器补上 ACT 与 SPPCODATA 触发，不替换其拨号架构。
- APK 同时应用公共网络 stager，升级不会再覆盖 APN 选择、开机回放、端口
  补报、初始 EPS 保留和 PDP 错误 28 重试；包清单记录这些输入文件。

`keep` 的含义可对照 netifd 的
[interface_update_start 实现](https://github.com/openwrt/netifd/blob/master/interface.c)：
它控制是否开始清理旧 IP 配置，不能把 `keep=1` 当成原地替换快照。

## 验证范围

行为测试覆盖双栈 CGCONTRDP 中选取 IPv4、完整事件触发的新 IP/路由/DNS
更新顺序、AT 失败不掉线、持续失活的恢复退出状态及 FIFO 清理。
构建时核对实际应用补丁的 ModemManager 源码，并保留既有短信、通话和
数据优先级检查。

T551M 部署前 CID 1/11 激活，WAN IP、DNS 与 CGCONTRDP 一致；固定 IP
探测 6/6 成功，约 57–164 ms。室内检查不能替代真实移动和跨基站测试。

## T551M 实机验证

最终 APK 为 `modemmanager-1.24.0-r927.apk`，已安装到 T551M，运行脚本与
包内文件校验一致。恢复 APN 自动解析后，CID 1 通过
`sipa_eth0` 拨号成功，IPv4 与 DNS 回读一致，独立 `wan_6` 获得公网 IPv6
及向 LAN 下发的 /64。模拟同配置的 MODIFY 事件及手动 renew 没有重拨、
没有重置 WAN uptime。监视器更新期间触发了 netifd 的正常重连，自动恢复
到新承载；最终版本续租验证再次保持 WAN 在线。两轮固定 IPv4 外网探测
均 8/8 成功，前一轮 47.6–86.2 ms，最终一轮 52.3–619.5 ms（首包尖峰）。
这不是严格的延迟前后对照，不能由此认定无线时延已改善。

另在隔离的虚拟网口、独立动态接口上运行正式续租脚本，AT 回复由测试工具
提供，其余使用实机真实 netifd 和 IP 命令。连续两次换 IP/DNS 后，netifd
状态和内核地址均只保留新地址，旧 DNS 消失；禁用默认路由的配置被遵守。
测试接口、网口和监视器已删除，实际蜂窝 WAN 保持在线。

公共 APN 回归 15 项、网络启动回归 8 项、MU300 对应检查通过。
真实跨小区/跨 RAT 移动仍需户外测试；室内手工写入 FIFO 验证了消费者路径，
不等于已实测所有固件的真实事件上报。

## 户外测试

沿原先容易掉线的路线测试，保留平时的双卡、网络模式与热点使用方式，
持续访问网页或播放网络音视频。重点观察跨小区、4G/5G 切换后是否还会
断网一分钟以上；发生异常时记录大概时间、是否仍有信号、能否打开本机
管理页，回来后可对照常规系统日志。

## 本轮户外反馈（19:27–19:45）

用户报告没有自主断网，Wi-Fi 离线和发现 n1 低速后锁定 n78 都是主动行为。
18 分钟记录只有约 19:35 的一次 modem 禁用/重新启用和承载重建，与手动
锁频相符；IPv4/默认路由约 6.73 秒恢复，IPv6/LAN 前缀随后恢复。
其余时段未见承载断开或 IP/路由重配，Wi-Fi 未发生固件断言或复位。

这一结果支持本轮实际移动体验稳定，但未捕获 active 承载期间改变 IPv4
的真实场景，原地续租路径仍以之前的 netifd 行为测试为验证依据。
抓取中的 daemon syslog 过滤存在漏采，已经修正；分析依据为本轮完整的
D-Bus、网络事件、内核记录和分钟快照。详见
[户外抓取结果与限制](FIELD-CAPTURE-20261013.zh-CN.md)。
