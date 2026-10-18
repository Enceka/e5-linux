# E5 issues 功能与缺陷评估

日期：2026-10-17。已读取 GitHub 当前全部 7 个公开 issue：#4、#6、#7、#8、#9、#10、#11；抓取时均为 open、无评论。公开列表缓存曾只显示 6 个，API 已包含新建的 #11。

初次评估对照本地 `main` 的 `0b292392` 及当时工作区，并核验 `20261017-band-led-171007` E5 包。用户随后批准修复，已在 `fix/e5-issues-20261017` 补入下列源码；旧发布包没有被覆盖，没有部署到设备或在 GitHub 发言。

## 实施结果（批准修复后更新）

后续[扩散验证记录](ISSUES-SIDE-EFFECTS-20261017.zh-CN.md)：修正旧密码套件被原生 select 自动切为 auto、连续唤醒丢失最新刷新，以及原生 TF 安装未提前检查新增工具依赖三处缺口；主回归、浏览器流程和三机型临时目录安装均通过。

| Issue | 已落实 | 验证与边界 |
| --- | --- | --- |
| #6 | TF 和内置分区共用 ext4 几何校验，接受 resize2fs 合法留下的小尾组，仍拒绝明显欠扩容和越界 | 真实稀疏文件 resize/fsck、64 GiB 文件保留测试通过；工具归档已加入校验清单，旧工具包禁止打包 |
| #9 | TF 电源状态转换去重、VMMC/VQMMC 顺序及 1.8V 寄存器回读检查，保留 UHS 能力 | 回调错误/重试/顺序及 eMMC 隔离测试通过；三款机型对象编译通过。尚未证明解决报告中的特定卡问题 |
| #11 | charger-manager 仅调用充电芯片声明可写的 PRESENT；无无线充电器时不设置无线类型 | 实际 C 函数模拟能力、引用释放、真实错误传播测试通过；不能据此声称 SIPA 阻塞或电量停滞已修复 |
| #8 | 公共网页充电管理和屏幕充电设置新增“插电直接启动 OpenWrt”，UCI 持久保存 | 默认关闭；普通启动不读取新策略、不增加等待。只改变 bootloader 已进入 charger boot 后的行为 |
| #10 | 唤醒/解锁后刷新当前设置分类；编辑器和离开页面后的迟到响应不覆盖；方向键、横滑和页面动画跟随自定义导航顺序 | Chromium 本地 API 回归通过；修复顺手发现的选择器/临时启动提示重复 DOM 写入，熄屏不新增绘制 |
| #10 | LuCI 密码套件按该 radio 的 nl80211 实际能力过滤，旧的无效选项明确校验错误；能力未知不冒充“不支持” | 测试实际打包版 LuCI 源码生成的控件，验证 CCMP/GCMP/另一无线芯片隔离；不改变 SAE 密钥通道，不降级加密 |
| #4 | 电脑安装、启动链检查、内置续装去掉固定 Magisk 工具路径；验证 Magisk 或 KSU/KSUNext BusyBox；原生 TF 模块入口传递所选工具 | root 探测、工具缺失中止、真实嵌套 shell/applet 探测、续装回归通过；尚无 KSU/KSUNext 实刷结果 |
| #7 | 保留已有修复 | 不重复修改 station 列表实现 |

本轮没有承诺实现：AP+STA 中继、完整 suspend 策略、真正电源旁路、GCMP 固件支持、SIPA 照片中缺失调用栈的卡死根因。没有增加 VPN 预装、NV 写入或基带复位。

### 修复来源与校验记录

- SD 时序参考：[Enceka/kernel_sprd_ums9158](https://github.com/Enceka/kernel_sprd_ums9158) 的 Android 5.15 BSP `sdhci-sprd.c`。本次下载文件 SHA-256 为 `a8892237f5f6c2674d8281ef280604b24506205b3da405044c457f3d29b0ac9a`。它是同平台厂商参考源码，并非已证明与群友原厂二进制逐字节一致；不能把软件寄存器回读等同于实测管脚电压。
- KSU 工具位置和 standalone ash 契约依据：[KernelSU 官方模块文档](https://github.com/tiann/KernelSU/blob/main/website/docs/guide/module.md)。不增加 OpenWrt 内核 KSU。
- radio→PHY 对应沿用 [rpcd iwinfo 的 phyname 接口](https://github.com/openwrt/rpcd/blob/master/iwinfo.c)，读取实际 `iw phy … info` 支持套件，不靠机型字符串猜测。
- SIPA 两个报告线程当前主循环使用 `wait_event_interruptible`，不是仅凭线程名便能认定的普通 D 状态等待；附图没有调用栈，无法在充电日志和阻塞之间建立因果。没有修改等待状态来隐藏 hung-task 警告。

通过的验证：

- `openwrt/tests/tf-single-root.py`：6 项，含真实 ext4 扩容。
- `devices/common/test_sd_power.py`、`test_charger_capabilities.py`、`test_power.py`：实际修改后的 C 回调编译/执行及幂等应用。
- E5/M8/T551M 分别编译 `sdhci-sprd.o`、`charger-manager.o`；不是整套内核发布编译。
- `devices/t551m/test_charge_mode.py`：11 项；`openwrt/tests/charge-control.py`：8 项；`luci-charge.cjs`：网页及三语言、旧客户端兼容。
- `openwrt/tests/android-root-tools.py`：3 项；`flash-diagnostics.py`：22 项；`part-two-stage.py`：9 项。
- `openwrt/tests/wifi-ciphers.py`：3 项，传入实际 pinned LuCI `wireless.js` 验证；原始文件仅复制到临时目录。
- `devices/t551m/test_screen_browser.py`：Chromium 导航、唤醒刷新、未保存编辑保护、手势、主题、实体键、电话及电源菜单回归，JS 异常为 0。
- 使用现有 ARM64 root 实际生成新的 `ext4-tools.tar` 并核验清单，未修改已有发布产物。

以下各节保留初次评估时的证据与判断，描述旧包的段落不表示新源码仍未修复。

## 建议执行顺序

| 优先级 | 项目 | 当前判断 |
| --- | --- | --- |
| P0 | #6 扩容成功却被断言拒绝 | 源码、最新包均仍存在；已用临时文件复现，应优先修 |
| P0 | #9 E5 TF 初始化后读写失败 | 最新包 boot 与报告的哈希前缀一致；优先对照原厂电压切换路径，根因尚未复现确认 |
| P0 | #11 充电异常及 SIPA 阻塞 | 需要拆开：不支持的属性调用已在代码定位，I²C 故障和线程锁死的因果尚未证实 |
| P1 | #10 唤醒后设置页刷新、方向键顺序 | 两项均有具体代码缺口，适合公共修复 |
| P1 | #10 不支持的 GCMP 配置使热点起不来 | 应按真实密码套件能力限制选择，并清楚报错；不把支持 GCMP 当成单纯 UI 功能 |
| P1 | #8 插电直接启动选项 | 共用关机充电入口可加持久策略，默认保留现有充电动画行为 |
| P2 | #4 KSU / KSUNext 授权兼容 | 通用 su 已有，Magisk 工具路径仍写死，适合拆除安装器对特定管理器的依赖 |
| P2 | #10 待机省电和无线中继 | 已有部分基础，但都需要继续做完整硬件/固件适配，不能宣称一并完成 |
| 可选 | #10 Tailscale | 内核 TUN 已有；遵守不预装 VPN 的要求，仅考虑用户按需安装的说明或入口 |
| 已覆盖 | #7 热点客户端始终为 0 | 公共驱动、构建入口和看板回退均已有；核验成包模块后不重复移植 |
| 待硬件证据 | #10 真正绕过电池直供 | 当前停充/充电阈值不是电源路径旁路；先确认原厂和板级能力 |

## #6：扩容校验的实际问题

来源：[issue #6](https://github.com/sprd-linux-devs/e5-linux/issues/6)。

- `openwrt/bundle/android-tf.sh:45` 要求文件系统块数与设备扇区数 / 8 严格相等。
- `openwrt/bundle/part-write.sh:60` 有同样断言。
- 最新 E5 ZIP 的 `files/android-tf.sh` 和 `files/part-write.sh` 哈希仍分别为 issue 给出的 `0153b317…`、`e723ed12…`，缺陷没有被刚才的打包修复。
- 原测试 `openwrt/tests/tf-single-root.py` 用整齐的 64 GiB 目标，没有覆盖尾部仅够少量块的情况。

在 WSL 用临时稀疏文件、4 KiB ext4、每组 32768 块和主机 e2fsprogs 1.46.5 实验，未接触任何设备或分区：

| 设备可容纳块数 | resize2fs 后实际块数 | 结果 |
| --- | --- | --- |
| 65787 | 65536 | 工具成功退出，但当前相等断言会拒绝 |
| 81920 | 81920 | 允许不完整的最后块组，并非所有不对齐容量都会向下取整 |

因此，issue 的失败现象成立，但“ext4 一律不能表达不完整块组”的解释过度泛化。修复应基于真实超级块几何、目标容量和 fsck 结果判断，不应把所有容量统一截成 128 MiB 倍数，更不能简单删除容量验证或接受明显欠扩容。

应补两条安装路径的边界回归：小尾组、合法部分组、整组、明显未扩容、超过设备边界和文件系统错误。它影响 TF 公共路径及使用相同脚本的内置分区安装，不应只改 GUI 显示。

## #9：TF 的 UHS / 电压切换

来源：[issue #9](https://github.com/sprd-linux-devs/e5-linux/issues/9)。报告有原厂 Android 同卡正常、OpenWrt 初始化后无法读取、禁用 UHS 后恢复的对照，值得最高优先级处理。

最新 E5 包 `files/BUILD.json` 记录的 boot SHA-256 是：

```text
fb81e9fbb2add3c94b5d7ab1068b0b99040c816be10163bb1c7f33afd931b54d
```

与 issue 的故障 boot 前缀一致。此次打包仅更新公共用户态修复，不能认为已解决这个内核问题。

不过，`sdhci_sprd_voltage_switch()` 已经调用 `mmc_regulator_set_vqmmc()`；“电压固定”的旧注释不能单独作为根因。下一步应对照原厂的实际 VQMMC provider、SD 电压约束、LDO 寄存器编码、切换时序及 pinctrl 状态，定位为什么软件切换与实测电压不一致。

优先保留原厂可用的 SDR50 能力。若先提供兼容开关，应只作用于指定 TF 控制器，明确性能影响；不要改全局属性字符串或连带降低 eMMC / Wi-Fi SDIO 能力。失败时回退也要遵守 SD 断电复位与重新枚举要求，不能假定一次错误返回就足够恢复。

## #11：不要把同屏日志直接判作 I²C 根因

来源：[issue #11](https://github.com/sprd-linux-devs/e5-linux/issues/11)，已查看附图。

照片同时包含：

- 约 242 秒：`sipa-free-1`、`sipa-fill-recv` 阻塞超过 120 秒。
- 约 275 秒：charger-manager 设置 wireless type、present 失败，返回 `-22`。

当前 AW32257 的 `set_property` 不支持 `POWER_SUPPLY_PROP_PRESENT` 和对应的无线类型 setter，默认分支直接返回 `-EINVAL`。charger-manager 却有这些调用。因此这两类错误可由属性能力不匹配直接产生，不足以证明 I²C 总线通信卡死。

应拆为三条调查：

1. 按原厂充电器能力修正有线 / 无线属性调用契约，不给 AW 虚构能力，也不全局吞掉所有 EINVAL。
2. 单独核对 SIPA 阻塞栈和等待条件，区分合法等待、资源状态问题和锁死；不能由充电错误反推 SIPA 根因。
3. 单独核对 FGU 原始电量、持久恢复值和状态采集；72% 停滞、切回 Android 满电仍未取得根因证据，不增加百分比硬修正。

现有电量修复不能作为“这个新报告已解决”的证明。

## #7：客户端列表已有公共修复

来源：[issue #7](https://github.com/sprd-linux-devs/e5-linux/issues/7)。

- `devices/common/wifi-stations.py` 已补 AP 的 `dump_station/get_channel`，且拒绝不存在的 MAC，避免把接口级速率伪装成每客户端速率。
- E5、M8、T551M 的 prepare-kernel 及 upstream 构建入口都调用这个适配。
- 看板在空 station dump 时已有 `wifi-hostapd-clients` 回退。
- 最新包所用 E5 `sprd_wlan_combo.ko` 中，已实际核验到 `sprd_cfg80211_dump_station` 和 `sprd_cfg80211_get_channel` 符号。

不应重复移植。旧固件应升级成套模块；新固件若仍异常，再对照 hostapd、peer 表和实际模块哈希。没有真实逐客户端指标时继续留空，不生成固定速率值。

## #8：插电开机

来源：[issue #8](https://github.com/sprd-linux-devs/e5-linux/issues/8)。

三款机器共用 `devices/t551m/charge-mode.py`，分别 stage 为 `/usr/libexec/e5-charge-mode`，由早期服务拦住 charger boot。当前没有用户可配的“充电动画 / 直接启动”策略。

可在此公共入口增加持久配置：只改变本次 LK 已启动后的等待策略，不增加轮询、不延长正常启动、不触碰基带顺序。对于彻底断电再恢复供电是否会进入 LK，仍由硬件和 bootloader 决定，不能把跳过动画宣传成所有断电场景均能自动恢复。

## #4：KSU / KSUNext

来源：[issue #4](https://github.com/sprd-linux-devs/e5-linux/issues/4)。请求是适配 Android 的 root 管理器，不是给 OpenWrt 内核装 KSU。

`flash.py:416` 已测试通用 `su -c id`；但 `android_checks():433` 强制存在 `/data/adb/magisk/busybox`，后续脚本也使用该路径。只改“缺少 root”的提示并不能解决问题。

合适的方向是：统一 root 授权探测、提供经过校验的独立安装工具路径，并保留 Magisk 模块入口。模块框架的生命周期和安装语义应分别验证，不能仅因同样提供 su 就声称所有 KSU/APatch 模式都支持。

## #10：七个请求分别评估

来源：[issue #10](https://github.com/sprd-linux-devs/e5-linux/issues/10)。

### 待机省电

已有 `devices/common/power/` 的 e5-sleep2 看门狗、DPU、GPU、电源域适配和公共 idle 配置。README 明确这些补丁不主动发起系统休眠，也未宣称三款机型均完成深睡验证。

剩余工作是完整的休眠与唤醒策略及功能保持验证：热点、USB、来电、短信和蜂窝连接不能靠“息屏就强制 suspend”牺牲掉。先区分电量计偏差与实际电流，不用百分比停滞推断续航。

### 直供电

当前充电上限、暂停充电与一次充满功能，不等于硬件 bypass。需要原厂电路 / 寄存器证据，确认芯片与主板是否能绕过电池给系统供电。不通过盲目停充或断开电池模拟此功能。

### 无线 AP 转发

当前驱动 `sprd_iface_limits` 把 STA 和 AP 放在同一条 `max=1` 限制里，尽管总接口上限为 3、信道数为 2，也不代表允许普通 STA+AP 同时运行。

因此值得支持，但需要先区分“单独 STA 连接失败”与“STA+AP 同时中继”，再对照原厂并发角色、固件能力和网络配置。不直接把接口数量改大，也不拿 P2P 限额当作已支持的 APSTA。

### Tailscale

最新 E5 内核 `CONFIG_TUN=y`，有基本运行条件。遵守用户“不打包 VPN”要求，不内置 tailscaled；如有需求，可提供按需安装、路由和启动配置说明。是否保留外网管理能力与安全边界另行设计。

### 唤醒刷新当前页面

`setBlank(false)` 会 render 最新总状态并 poll；但是充电等设置分类缓存于 `st`，`stLoadCat()` 主要在进入分类或操作后触发，唤醒不重取当前分类。因此是具体缺口。

应在真正亮屏/解锁事件后刷新可见动态分类，处理重复请求和迟到响应，保留尚未提交的编辑值；无需增加常驻轮询或刷新整个浏览器。

### WPA3 GCMP

当前驱动正常密码套件列表没有 GCMP-128；GCMP-256 仅在 `SUPPORT_WPA3_ENTERPRISE` 条件下声明，未找到启用该宏的定义。`sprd_parse_cipher()` 对未识别套件会返回 NONE。

应先按实际 nl80211 密码套件能力过滤选择，并对手写配置报清楚原因，避免保存后热点消失。不静默降级加密，不把“驱动有某个枚举”当作固件支持证明，不承诺启用 GCMP 必然提速。是否真正增加套件支持属于后续固件适配。

### 导航顺序与动画

底部入口已经能自定义 5 个，但 `base/app.js:884–885` 的左右键仍直接 `showPage(page±1)`；它没有使用 `mobile.js` 的 nav_slot 配置，所以顺序不一致属实。

适合统一触摸、方向键和页面导航的数据源；页面总顺序与前 N 个导航入口可以进一步统一。需定义重复入口、未显示页面、设置子页、通话和锁屏时的行为，再增加轻量过渡动画。不要让方向键跳出当前输入或弹窗。

## 初次评估结果与旧包影响

- 已完成全部 issue 的源码和最新包对照、#6 临时文件复现、#11 图片核验。
- 没有改动功能或重打包。刚才的五份包不会因为本报告自动获得新修复。
- E5 当前发布包的 #6 两个断言仍在，#9 使用相同 boot；建议先修安装可靠性与内核 TF 路径，再做新增功能。
- 公共用户态修复应覆盖 E5 / M8 / T551M；AW 充电器和板级 TF 电压修正按机型隔离。MU300 若复用对应安装校验，再核对移植，不照搬 E5 硬件补丁。
