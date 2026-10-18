# 原厂对照与新机型适配清单（2026-10-16）

本清单汇总本次电量、充电、功耗、失去覆盖恢复、通话挂断及热点客户端修复。
“源码覆盖”“编译通过”“已部署”和“用户实际验证”分别记录，不能互相替代。
新机型先确认硬件及原厂行为，再选择公共实现；不要按 SoC 相同整包复制板级策略。

## 先识别机器与原厂基线

1. 保存型号、板号、Android 内核版本、原厂 DT/DTBO、模块哈希、实际启动槽和根分区类型。
2. 多设备共用网关时使用明确的管理地址，并核对设备 profile、eMMC CID、boot 分区映射。
   本次 U30 Air 与 F50 同为 192.168.77.1，使用 U30 专属 IPv6 链路地址避免误写。
3. 原厂 boot/vendor/vendor_dlkm 只读提取到电脑分析；不挂载写入 Android/NV，
   不重置有效电池保存值，不假设 runtime NV 或校准数据可以清除。
4. 有无电池、屏幕、相机、独立听筒及充电芯片是独立能力。U30 Air 无屏、无相机，
   不接入 E5 的 DPU/GPU/相机电源域补丁；无电池 F50/V50 不进入 U30 电池管理。
5. 保存寄存器、库仑计、charger Full、真实电压电流和原厂函数的对应关系。
   显示 100% 不代表电气满电，USB 输入电流也不等于电池充电电流。

## 修复索引与适用范围

| 项目 | E5 仓库实现 | MU300 仓库实现 | 新机型要求 |
| --- | --- | --- | --- |
| 电量锁存、开机恢复 | `devices/common/fuel-gauge.py`；state、diagnostics、stock-latches 补丁 | `upstream/patches/0020-power-UMP9620-stock-retained-soc.patch` | 先核对 PMIC 格式、有效位、masked RMW 与等待时间，不把有效旧值按 OCV 重算 |
| 满电/回充 | `charger-stock-policy.patch` 恢复电气判断、平滑及滞回 | 0020 使用 charger Full + 原厂 DT 的 fullbatt-voltage/current | 不加 99% 上限，不因 UI 100% 直接退出管理，不搬其他板电流电压 |
| 电池板隔离 | 按设备 DT 的充电节点及实际驱动选择 | 0019 + `ump9620_has_battery_policy()`；BQ/FGU/PD 首次硬件访问前校验 | UMP9620 vendor 路径要求启用的 charger_policy_service，主、备用地址都覆盖 |
| 空闲省电 | 三机 CPU idle；watchdog/DPU/GPU/camera 补丁按 compatible 及设备配置应用 | `upstream/mu300-mainline.config` 启用 NO_HZ_IDLE/HIGH_RES_TIMERS | 对照原厂配置；HZ=250 不变，不降低看板/业务轮询频率；无屏板不带显示/相机修改 |
| 未满足的自动拨号恢复 | `e5-network-recovery` 订阅 MM D-Bus 与 netifd；检查 PS 附着/注册/RAT | `mu300-network-recovery` 订阅既有 owner 的 EPS 注册变化与 netifd | 手动断网不得复活；仅当前上网槽；不新增串口 owner、不重置射频 |
| 已连接期间的移动性 | Unisoc MM mobility 补丁 + renew helper | 原有 `mu300cell-v6.sh` 的 CGEV/SPPCODATA 与 netlink 更新 | 保留 IP/DNS 原地更新；读不到状态不等于明确脱网，不能直接判定需要重拨 |
| 通话挂不断 | `modemmanager-17-unisoc-stock-hangup.patch`：Unisoc 按原厂 CHLD=7index；错误保持可重试 | 无电话 UI，不搬入电话服务 | 先确认 RIL 的具体命令；不把单通话挂断失败变成挂断全部通话 |
| SIPC 调试类 | 检查对应分支初始化入口 | `sipc.c` 全局 class 只创建一次，驱动注册失败清理 | 不能每个 remote probe 重建同名 class |
| 热点客户端 | `devices/common/wifi-stations.py` + hostapd JSON 回退 | `cfg80211.c`、AP stats scope 补丁 + 同类回退 | AP 按 peer MAC，拒绝未知 MAC；空 dump 成功也回退；未知速率保持空，不编造 433.3 Mbps |
| 网页终端 | rootfs 包含 ttyd / luci-app-ttyd | 同左 | 仅本地管理使用，保留身份认证与现有防火墙，不开放外网端口 |

E5 公共充电修复覆盖 E5/T551M/M8 的构建入口；不表示三台已经完成全部实机验证。
MU 公共恢复逻辑适用于现有 mu300cell 框架；没有把 ModemManager 强行引入 MU300。
具体二进制证据与测试结果见各仓库的日期报告。

## U30 Air 本次增量

- 从本机 Android A 槽 boot 提取的原厂 `5.4.254-android12-9-g9444efdc6885` 配置确认：
  `NO_HZ_IDLE=y`、`HIGH_RES_TIMERS=y`、`HZ=250`、PSCI cpuidle/menu。
  原 OpenWrt 7.2.8 为 HZ_PERIODIC，空闲时仍有周期 tick。本次改为空闲停表，
  不启用 NO_HZ_FULL，不改变全系统挂起策略、充电/OTG/LED 和业务轮询频率。
- 不带 E5 相机、屏幕或其电源域修改。时钟停止只影响空闲 tick，
  CPU 有工作时和定时器截止时仍正常唤醒；没有宣称固定百分比的续航提升。
- EPS 注册缓存由现有 nr0/nr3 drainer 更新，只保存槽号、stat、AcT，
  不保存号码、短信正文或位置。相同状态/RAT 不重复发事件；owner 重新建立时清除旧缓存。
  原有拨号中的 CEREG? 结果也更新缓存，不增加查询。
- 失去覆盖等待结束与“无模块”“双卡射频需重启”“已注册但取不到 IP”分开处理。
  仅前者返回专用码 5，netifd 保存 autostart、等待注册事件。
- 仅 stat=1/5 且槽位匹配时恢复可用性；SMS-only、紧急状态及无效 RAT 不触发。
  随后的实际注册确认、APN、CGACT、CGCONTRDP、CGDATA 仍走原流程。
- native SIM 运行槽优先于网页下一次启动保存槽；切卡、native RF 尚未 ready 的 freeze、active unknown、
  手动 mobile-data down、netifd autostart=false 均阻止自动恢复。
  U30 的 freeze 在正常 native 双卡工作时会保留，ready 后不拦截 PDP 恢复，也不解除该射频保护。
- 事件服务空闲阻塞；50 ms 单次定时器只合并事件，非轮询。重复 netifd 事件不自激重拨。
  已有正常 watch 和已连接期间的 CGEV/netlink 更新机制保留。
- 本机读取的 CEREG reporting mode 为 2，nr0 已持续上报注册变化；
  没有为接入事件通知额外插入 AT 初始化指令。新机型必须核对实际 URC 模式及归属通道。
- 这不是宣称完整复刻厂商 RIL 的全部重试参数、SQC/CAS 电池学习或 JEITA。
  有明确原厂证据的路径对齐；外场无信号、完整充放电及续航由用户继续验证。

## 本次状态矩阵

| 设备 | 源码适配 | 本次实机状态 | 仍不能声称完成 |
| --- | --- | --- | --- |
| E5 | 公共 FGU/CM、省电、恢复、电话及热点修复 | 前一轮电量/省电修复已部署；后增的挂断、客户端修复本轮未再部署 | 新挂断的实际通话及完整充放电 |
| T551M | 同一公共入口，保留本机充电和双卡差异 | 完整 stockpower1 内核及配套模块、MM r934、客户端回退已部署 | 新挂断实际通话、长期续航及无覆盖外场 |
| M8 | 同一公共入口，保留共享喇叭等板级策略 | 公共驱动对象编译，本轮未连接/部署 | 本轮全部硬件效果 |
| U30 Air | 电量恢复、battery-policy 隔离、SIPC、热点、省电时钟、注册恢复 | 7.2.8 完整内核及配套模块已部署；WAN、AP、USB、服务和配置检查正常 | 电池完整周期、实际续航、长时间失去覆盖与充电/扩展坞物理插拔 |
| F50/V50 | 公共初始化、热点、注册恢复、空闲时钟适配；不启用 U30 电池路径 | 本轮未刷入；连接 F50 仅只读核对 | TR3000 启动报告的物理复现及新包实测 |

状态按 2026-10-16 本次工作记录，不覆盖此前用户已经完成的其他机型测试。

## 构建与部署规则

1. 公共修复放共享构建入口，板级能力放 profile/DT 判断，避免只热改实机。
2. 同时检查干净构建和缓存源码的补丁应用。对串口、短信、双卡和拨号顺序运行已有回归。
3. 内核、BTF、initramfs 模块、根文件系统模块必须来自同一构建。
   uname/vermagic 相同也可能 BTF 不同；只换内核而保留旧模块属于部署错误。
4. 重打内核 LK 包装，不能复用旧 `Image.lk`。保留现有 init、cmdline、
   vendor fallback 档案、根分区选择和启动日志区；本次 U30 boot 日志保留区从 48 MiB 开始，
   E5 系部署工具的其他机型可不同，不能套用固定偏移。
5. 刷入前核对型号、CID、分区别名、boot_id 和原 boot 头哈希；备份并验证新文件校验值。
   原子更新用户态文件，配套全部模块；sync 后正常重启，不硬复位，不改 misc/NV/Android。
6. 不在线重启 U30 的 persistent AT owner 来加载脚本，它会关闭 SIPC 通道。
   新脚本随计划内核重启生效。
7. 重启后核对实际内核配置、PSCI idle、initramfs/root 模块哈希、WAN IP、
   热点/USB/充电节点、服务日志、BTF/Oops/存储错误。保留可复查部署回执。
8. 本次没有把 eMMC 全局改成禁止休眠，也没有强制 HS200；这两项不能作为通用可靠性补丁。

## 回归命令

MU300：
```sh
python3 -m unittest discover -s tests -p 'test_registration*.py'
python3 -m unittest discover -s tests -p test_cellular_mobility.py
python3 -m unittest discover -s tests -p 'test_u30air*.py'
ucode tests/network_recovery.uc
# 隔离 OpenWrt 容器内，有 ubusd/fs/uci/uloop 模块，不要在正在工作的设备上起第二个 ubusd：
sh tests/network-recovery-runtime.sh
python3 tests/stock_power_driver.py KERNEL_TREE
```

E5：
```sh
python3 openwrt/tests/voice-hangup.py MODEMMANAGER_SRC_DIR
python3 openwrt/tests/wifi-hostapd-clients.py
```

具体脚本参数以各报告及脚本帮助为准。硬件听感、充电器握手、长时间移动恢复、
完整电池周期不能由离线策略测试替代。不要将“源码已修”写为“所有用户故障已确认解决”。

## 详细记录

- [SIM 事件、无卡等待与原厂对照](SIM-EVENTS-20261016.zh-CN.md)
- [E5 原厂电量、功耗与蜂窝恢复](STOCK-POWER-RECOVERY-20261016.zh-CN.md)
- [公共充电、电量恢复、挂断及热点客户端修复](STOCK-CHARGE-CALL-WIFI-20261016.zh-CN.md)
- [网页充电控制](WEB-CHARGING-20261016.zh-CN.md)
- [蜂窝移动性](CELLULAR-MOBILITY-20261013.zh-CN.md)
- [SIPA 数据路径](SIPA-DATA-PATH-20261015.zh-CN.md)

