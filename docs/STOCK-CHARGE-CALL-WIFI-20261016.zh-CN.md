# 2026-10-16：公共充电、电量恢复、挂断及热点客户端修复

## 范围

E5、T551M、M8 共用充电管理、电量保存和通话修复。充电芯片编码、板级电压及
温度阈值仍由各自配置决定，没有把 T551M 电流参数复制到 M8/E5。
MU300 仓库补齐 U30 Air 电量恢复、无电池机型隔离及客户端列表回退。

后续 U30 Air 的省电与恢复已按其无屏硬件独立适配：实际原厂 boot 确认
NO_HZ_IDLE/HIGH_RES_TIMERS 后修正周期 tick；注册事件接入现有 mu300cell，
不移植 E5 的相机/显示电源域或 ModemManager。
两个仓库均新增 [原厂对照与新机型适配清单](NEW-DEVICE-STOCK-ADAPTATION.zh-CN.md)，
记录公共/板级边界、测试、配套模块部署以及尚待用户验证的项目。

本轮已部署 T551M、U30 Air。E5 的上一轮公共电量计修复已部署，
本轮新增挂断与热点驱动修复尚未部署到 E5。M8 未连接，本轮完成源码适配和驱动编译，
不能写成 M8 实机验证通过。

## 原厂充电与电量计

之前的公共分析见
[STOCK-POWER-RECOVERY-20261016.zh-CN.md](STOCK-POWER-RECOVERY-20261016.zh-CN.md)。
本轮从 T551M、U30 Air 的 super 只读提取 Android A 槽 vendor/vendor_dlkm，
在电脑离线解包，没有挂载或修改设备上的 Android 分区。

| 原厂模块 | SHA-256 |
| --- | --- |
| T551M sc27xx_fuel_gauge.ko | aed723dc196aac21373fdd91a972595ccb8c74e88f4ca89b6d8f0864083eb346 |
| T551M sprd-charger-manager.ko | bf2717c9ea32e8fe6b1c08e90f5c3cb74c96be9c383d77271291c27dbd157ae6 |
| T551M bq2560x-charger.ko | ff3b02bb523b250ddf38f03864bf49da6de90c8f9f60e84cb4235ec21e83c5ae |
| U30 Air sc27xx_fuel_gauge.ko | b677aef2019ac95da686bbf80ce72f2a3f12f22bc5a151e9f6bd187f1e13f074 |
| U30 Air sqc_bq2560x.ko | ce42c87c42f9ed7e5b5aba8277d4245c03c2c41a569e8ca24d749f07bc3a0efc |
| U30 Air charger_policy_service.ko | 808b23dce5aee9886df868cd796c8382105b9d99cc80bd2240f8a93fc7b2ac1e |

原厂 T551M 模块版本为 `5.15.123-android13-8-g2054f18da766-ab10`；
U30 Air 为 `5.4.254-android12-9-g9444efdc6885`。原厂二进制不进入安装包。

E5 公共充电管理恢复电气满电判断、原厂平滑和回充滞回，
移除 UI 达到 100% 就提前返回、97% 强制映射 100% 等覆盖行为。
FGU 保留编码校验、错误传播、读回检查和最终保存顺序修复，恢复原厂 masked RMW 锁存。
共享构建入口覆盖 E5、T551M、M8，不增加周期采集服务。
T551M 原厂 `is_full_charged 0x4d04` 同样读取实际电源属性、走电压电流判断，
没有移植源码中按显示百分比提前返回的覆盖。

U30 Air 原厂 FGU probe `0x1bd0` 使用低字节整数百分比、高 nibble 小数；
`save_last_cap` 位于 `0x4ba4`，采用 masked RMW、200 μs 级等待。
MU300 旧实现会把部分合法保存值当成旧版本残留，静置时按 OCV 重算。
现已删除该推测性迁移，仅无效保存值才走 OCV。
同时删除“OCV 达到 70% 即强制满电”的条件，改用原厂 battery 节点的
`fullbatt-voltage/current`，并继续要求真实充电器报告 Full。
连接机器对应 4.2 V、120 mA。本轮未修改 U30 Air 充电器电压、电流限制。

这不等于完整复刻 ZTE SQC/CAS、老化学习和全部 JEITA 策略；
本轮对齐有二进制/设备树依据的格式、寄存器操作及满电电气条件。
旧软件已经写成合法 100% 的值不能仅凭一次电压认定错误，因此未强制重设电池数据。

## F50/TR3000 USB 启动报告

已确认源码隔离缺口：原有保护只限制 0x1a 备用地址；若无电池板在主地址
0x6b 有响应，仍可能初始化 U30 Air 充电逻辑。FGU/PD 也缺少一致入口检查。
新增 `ump9620_has_battery_policy()`，要求原厂设备树存在且启用
`/charger_policy_service`，在 vendor BQ、UMP9620 FGU、PD 首次硬件操作前检查。
无电池 F50/V50 不进入这些电池路径，其他通用 BQ/SC27xx 芯片行为不变。

连接的 F50 只做只读检查，充电器原本未绑定，但 FGU 暴露虚假电池状态。
没有在 TR3000 上复现启动失败，不能断言此缺口是所有报告的唯一根因，
也不能据此认定用户电源有问题。

## 通话偶尔挂不断

E5 原厂 `libimpl-ril.so` 引用 `AT+CHLD=7%d`
（字符串 `0xe875`，格式化调用附近 `0x5fd3c`）。
T551M 原厂 RIL 对照源码的 `requestHangup()` 也使用此指定通话释放命令；
原有 ModemManager 使用通用 `CHLD=1<index>`。

新增 `modemmanager-17-unisoc-stock-hangup.patch`：

- 仅 Unisoc 使用原厂 `CHLD=7<index>`，仍由现有单一 AT owner 选择所属卡槽。
- AT 挂断失败时保留真实通话对象，传播错误，允许重试或等待 CLCC 更新。
- 不再在 AT 失败后提前标记已挂断，也不盲目退化为会影响同卡其他通话的全局释放。
- 其他 ModemManager 插件保留原指令、回退和完成行为。

没有修改拨号前回放、AT 初始化顺序、通话音频配置或 AT 超时。
APK 为 `modemmanager-1.24.0-r934.apk`，完整构建和 voice/sim/SMS/mobility 测试通过。
本轮没有主动拨打电话，偶发挂断仍需实际使用验证。

## issue #7：客户端列表及计数

对应 [e5-linux issue #7](https://github.com/sprd-linux-devs/e5-linux/issues/7)。

- 公共 `wifi-stations.py` 补 `dump_station/get_channel`，
  从本接口的固件 peer 表列关联 MAC，过滤自身、组播和其他接口。
- AP 的 `get_station` 不再返回 STA/整接口数据；不存在的 MAC 返回 ENOENT，
  避免固定 433.3 Mbit/s 被冒充客户端速率。非 MLO 链路编号检查避免越界。
- 两仓库看板对成功但为空的 dump 及失败结果增加 hostapd `get_clients` 回退，
  由已有 ucode JSON 解析器读取，只统计已关联的有效单播 MAC。
  DHCP 租约只补 IP/主机名，不作为在线证据。
- 未提供的速率、信号保持未知；没有新增 AT 请求或轮询。

MU300 主线驱动及 vendor 补丁也补 AP 指标隔离和链路编号检查。
LuCI 包 release 分别为 E5 r5、MU300 r14。

## 构建与实机结果

| 项目 | 结果 |
| --- | --- |
| E5/T551M/M8 充电、FGU、Wi-Fi 对象 | 全部编译通过 |
| E5 公共 FGU | 穷举 4096 编码，合法保存、错误、关机顺序通过 |
| E5 公共充电 | 电气满电、连续采样、回充、平滑通过 |
| MU300 6.18.54 / 7.2.8 | 充电/FGU/PD 对象通过；7.2 完整内核及配套模块通过 |
| MU300 电量恢复 | 4096 编码、合法值不迁移、电气边界、无电池入口通过 |
| Wi-Fi 实际回调 C | 地址过滤、断开、STA 隔离、链路范围通过 |
| hostapd 回退 | T551M/U30 Air 实际 ucode 和空 dump 集成测试通过 |
| ModemManager | r934 全量构建及原厂挂断/错误/通用回退兼容测试通过 |
| T551M | 新内核、配套模块、看板、r934 已部署并启动 |
| U30 Air | 新内核、配套模块、看板已部署并启动 |

T551M 内核 `6.18.54-t551m-stockpower1-g020b970e351e-dirty`，
WFI/core-sleep/cluster-pd 状态可用，相机域按原厂时序关闭。
U30 Air 内核 `7.2.8`。两台均有 WAN IP，热点和 USB 管理正常，
未见新的存储 I/O 错误、BTF 不匹配或内核异常。

U30 Air 启动检查另发现 SIPC probe 对多个 IPC 子设备重复创建全局调试类。
现移至模块初始化成功后只创建一次，保留退出清理，并测试注册失败的清理。
重新部署后重复节点堆栈消失，不改变 SIPC 协议。

部署逐台核对 profile、eMMC 身份、boot 槽和校验，备份 boot/模块，
保持其他 initramfs 内容、根分区选择和 misc，不修改 NV 或 Android 启动槽。
正常重启并保留各型号的持久日志区域。

待用户实测：不同充电器快插拔/PD 扩展坞、长时间充放电及续航、
偶发挂断、F50 在 TR3000 USB 口启动。静态测试不代替这些物理结果。
