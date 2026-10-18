# E5 / T551M / M8 发送路径静态修复核对

2026-10-15。对照本地 MU300 仓库的 `149c9d2`，检查 E5 固定内核
`020b970e351e` 及三款设备准备树。此次只改公共源码和执行离线验证，没有访问
设备、开启采集、刷机或重新打包。

## 核对结果

| MU300 修复 | E5 系列实际情况 | 处理 |
| --- | --- | --- |
| SIPA BUSY 返回前恢复报文头、消费失败报文返回 OK | 公共 SIPA 补丁已经包含 | 保留，并继续测试 |
| SIPA BUSY 返回前恢复 TCP/UDP checksum seed | 同样会清零 seed 后返回 BUSY；旧测试没有启用 CHECKSUM_PARTIAL | 新增公共修复，原函数已通过测试复现丢失 seed |
| IRQ flags 局部化 | 两个 SIPA 回调共用静态 flags | 改为各自局部变量，不宣称这是已实测的断网根因 |
| WLAN 填描述符时释放旧 skb / 使用旧载荷地址 | E5 的描述符函数不重新分配 skb，入口已使用 skb_cow_head 保留所有权 | 不照搬不同版本的 filler 改动，已有所有权测试继续通过 |
| 命令描述符误读 transport prefix | E5 已用 skb->data + hif->dscr_rsvd，并在添加 SDIO flag 前设置 group BK | 无需重复修改 |
| PCIe EDMA pending ring 返回码、完成唤醒 | 三款实际使用 SDIO，发送和总线完成机制不同 | 不导入 PCIe 专用 EDMA 修复 |
| 普通组播占用 CMD_TX_DATA，无业务包背压 | E5 同样将 AP 的 IPv4/IPv6 组播绕过正常 IP 分类器、送到命令工作队列 | 取消该分流，交还 IP 分类器和现有 group BK 数据队列 |

E5 以前的现场记录也包含 IPv6 UDP 5353 命令被固件拒绝，见
[下载和首次接入分析](WIFI-DOWNLOAD-RECOVERY-20261013.zh-CN.md)。MU300 此次用
合法组播突发复现了相同错误；但不能把 MU300 的“每批前六个接受”的观测当作
E5 系列固件的固定队列深度，也未证明 E5 的每次历史错误都来自这一原因。

## SIPA 改动

新 `devices/common/sipa-tx-retry.patch` 接在已有公共 SIPA 补丁之后。
成功提交仍按原厂方式清零 TCP/UDP 校验和字段；返回 BUSY 时恢复原始 seed，
与已经恢复的 skb 头部/长度一起交回网络栈。没有修改成功发送格式、错误码对应
的未知硬件行为、射频设置、NV、AT/拨号/回放时序或 runtime PM 策略。

`sipa.py` 在临时目录逆序规范化、顺序检查并重新应用整组补丁，整体验证成功后
才更新源码；干净树、已打旧补丁的增量树、当前树得到相同结果。当前树重复执行
不会改写文件，源码不兼容时拒绝更新，不留下部分应用状态。

## SDIO 组播改动

新 `devices/common/wifi-tx.py` 删除只用于 AP 组播命令分流的三个 helper，
让原来的 IP 分类器处理 IPv4/IPv6。普通组播进入已有数据队列，沿用 group
LUT、BK/TID=1、firmware credit 及 SDIO 发送机制；认证、DHCPv4/v6、VoWiFi、
RTSP 仍有各自命令路径。保留 STA 的 DNS 分类、ARP/普通 DNS 已有优化、
IP 组播接收防重复转发，以及断言恢复机制。

没有屏蔽固件错误、过滤 mDNS、关闭 IPv6、增加固定延迟或常驻轮询。
对 E5 系列 SDIO 而言，这项是代码路径上的防御性修复，尚未通过新的实机测试。
早先曾尝试普通组播数据路径后仍发生高负载停顿，后来证据指向 TX 线程缺失调度点；
因此那次实验既不能证明这次改动有效，也不能替代后续吞吐/组播送达验证。

入口包括三款准备脚本经 `devices/wifi-common.py` 调用，以及 Docker/native
两个通用 mainline 构建入口。SIPA 原有三款及通用入口保持接通；下一次正常构建
会带上此次补丁，现存刷机包及运行中的设备不会因此自动更新。

## 离线验证

- 三款各自准备树完成两类新回归：实际 SIPA C 函数执行 IPv4/IPv6、TCP/UDP、
  Raw IP/Ethernet、部分校验和开关的 16 种组合，每种连续 50 次背压重试，
  检查 seed、报文几何和恢复工作；成功提交仍采用原清零语义。
- 旧 SIPA 函数在新测试的 checksum seed 断言处失败；修复后通过。补丁同时验证
  旧树升级、当前树幂等、错误源码拒绝且不产生部分更新。
- 提取实际 Wi-Fi IP/特殊报文分类函数和 UDP helper，用 ASan/UBSan 执行
  AP/GO/STA、IPv4/IPv6、组播/单播、普通 mDNS/DNS、DHCP、VoWiFi、EAPOL、
  RTSP、ICMPv6/扩展头场景；普通数据保持校验和及报文字节，控制报文路径保留。
- 三款原有 Wi-Fi skb 所有权、notifier 注销清理、IP 组播 RX 转发测试继续通过。
- 使用各自现有配置和 ARM64 Clang 工具链，三款 `sipa_eth.o` 与 Wi-Fi `tx.o`
  全部编译通过：E5 `6.18.54-e5-mobile4`、T551M `6.18.54-t551m-otg10`、
  M8 `6.18.54-m8-probe12`。日志位于本地 `work/tx-static-20261015/`。

对象编译和离线错误注入不是整包/BTF 加载或实机吞吐验证。此次未提交 commit。
