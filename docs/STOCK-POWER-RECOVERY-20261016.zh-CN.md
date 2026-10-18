# E5 原厂对照：电量、功耗与蜂窝恢复（2026-10-16）

## 修复依据

实机为荣悦 E5，Android 13 原厂版本：
`UNISOC/ums9158_1h10_cmcc/ums9158_1h10:13/TP1A.220624.014/2024112822:user/release-keys`。
从原厂 super 分区只读提取 vendor、vendor_dlkm、system、system_ext，分析原厂模块、
RIL 与 telephony DEX。没有修改 Android、NV、分区布局或电池校准数据。

原厂证据摘要：

| 文件 | SHA-256 | 已核对内容 |
| --- | --- | --- |
| sc27xx_fuel_gauge.ko | fb3b2f07b16087c658eb97d1709d60224dc4a9020adc8caf3f4617e659250111 | 电量编码、开机恢复、保存时的 masked RMW |
| sprd-charger-manager.ko | 45dd82b92ff16626ccac77fe802c06fccdd3eda68ba0175b17a41c9a0f828d07 | 电气满充判定、SOC 平滑、校准与补电滞回 |
| aw322xx-charger.ko | 76a7ce1d9eb999e0d575ba63a6907a283cc124275f8fac46c8ff8f84bb62dc10 | 原厂充电芯片控制，不能用相似 AW 驱动代替 |
| libimpl-ril.so | c0e86a5a6d7402a3d126e411fdb956deb8a6454763d55505c3ba64f839d0c14b | 数据呼叫列表刷新与 setup-data-call 路径 |

主机分析资料保存在忽略的 `work/e5-audit-20261016/` 和
WSL `/home/kano/e5-stock-review-20261016/`，不把大体积原厂镜像加入 Git。
DEX 反汇编工具过旧，另建仅供分析的副本去掉 hidden-API 限制表的 map 入口；
原始 DEX 和所有指令内容保留，记录两份 SHA-256，不回写设备。

## 电量与充电

原移植 CM 存在 UI 达 100% 就提前返回“已满”的路径，真正的电压／电流和连续确认
代码不可达；另外禁用了原厂 SOC 平滑，加入 97%→100% 映射。
原厂实际 CM 二进制保留电气判定、连续触发、校准、平滑与补电滞回。
公共补丁恢复这些路径，阈值继续来自本机设备树，没有新增 99% 上限、强制校准或
统一改写充电芯片 TE。T551M/M8 共用的相同 CM 源码修正已编译；原厂二进制逐项对照
目前完成的是 E5，不能写成三机原厂充电策略全部实测一致。

更关键的是此前强制写入 FGU SET/CLEAR 寄存器的修改。原厂使用 masked RMW。
同一台 E5、同一显示 SOC、不改库仑计校准，使用既有 CAPACITY 保存接口进行对照：

- 强制写入版：10 次中 1 次回读失败，日志明确为 `requested=960 read=0 ret=-5`。
- 恢复原厂 masked RMW：先 10 次，再连续 100 次，同值保存全部通过。
- 两轮正常重启显示均维持 96%，未再出现该保存错误。

这说明“保存后变为 0”有实际复现，不能仅归咎于网页显示或关闭太快。新补丁恢复原厂
访问方式，保留编码范围检查、失败回读传播和关机停止更新后再保存的顺序。
这仍不等于已覆盖长期冷关机、所有电池老化状态和三机硬件；完整充满—放电周期尚未验证。
USB 电流包括系统负载，不能仅凭 USB 侧有电流就判断电池仍被过充。

E5 已部署 CM 与 FGU 修正版，备份位于 `/root/update-backups/stock-charge-*`。
最后部署的 FGU 模块 SHA-256：
`575acdb45529dc52915c6401428a64939f2d9cd6c99f2bc00cacc8a8cec2296a`。

## 功耗与参考 fork

现机 CPU 多数时间空闲，但当前运行内核没有启用 CPU_IDLE。
实际 E5、T551M、M8 原厂内核配置均启用 ARM PSCI idle；共享配置已补入 menu 与 PSCI
idle，利用本机 DT 的核心／簇空闲状态。它不会冻结用户态，也不改变网页／AT 轮询率。

参考 [CharlesGool/e5-sleep-kernel e5-sleep2](https://github.com/CharlesGool/e5-sleep-kernel/releases/tag/e5-sleep2)，
固定源码提交 `52ad641fb43764086b0e7d45f0a58098ff89cb04`：

| 改动 | 本仓库处理 |
| --- | --- |
| 0001 PMIC watchdog system-suspend 停表／恢复 | 保留署名导入公共补丁；只在系统实际挂起时处理 |
| 0002 DPU writeback work 未初始化就 cancel | 保留署名导入公共补丁；不更改显示时序 |
| 0003 CPU idle | 与原厂配置证据一致，合入共享配置；未直接复制该配置补丁 |
| 0004 GPU 挂起断电 | 已纳入，并补上 core gate、PMU 状态等待、DVFS 写入失败时的断电清理 |
| 0005 camera power domain | 已纳入；0006 根据实际原厂模块补齐 DCAM/ISP/主域时序、总线错误和时钟计数处理 |
| 默认关热点深睡、禁用 IPv6 等应用 | 不导入；不能以减少路由功能冒充驱动省电 |

整套修复接入 E5/T551M/M8 及 upstream 两种构建入口，stager 先验证全部文件后
写入、反向卸载已有补丁后重建完整栈，支持干净源码和缓存源码升级，重复应用不改文件。
看门狗回调的运行／停止状态、错误传播测试已通过。
没有更改 eMMC 休眠，没有自动执行整机深睡。

E5 已部署新内核 `6.18.54-e5-mobile4-idle1-g020b970e351e-dirty`，完整更新 45 个
initramfs 模块和 267 个配套根分区模块，旧 release 保留。启动脚本、命令行、misc 和
持久日志区不变。新备份位于 `/root/update-backups/idle-power-1792135783`。
正常启动后基带、WAN/外网、热点、屏幕服务、ttyd 均恢复，没有新的 WARNING/Oops/BTF
错误。驱动为 `psci_idle`、governor 为 `menu`；20.01 秒的采样中 CPU0 核心断电 7.615 秒、
簇断电 8.465 秒，八核累计空闲断电驻留约占采样总核时的 89.5%。这是实际状态计数，
不是直接测得的省电百分比。

后续软件侧工作已补齐，不再因等待用户实测而保留 GPU／相机补丁未接入：

- 原厂相机模块的 qogirn6l `sprd_cam_pw_on.58` 位于 0x25b4，顺序为主域→DCAM→ISP；
  `sprd_cam_pw_off.59` 位于 0x2d80，顺序为 DCAM→ISP→主域。
- 使用原设备树的 9 组 syscon/register/mask，不硬编码某机型物理地址；关闭自动关断后
  切换 FORCE_SHUTDOWN。确认值为开启 0、关闭 7，按字段 mask 移位。
- 原厂每轮延迟 300–350 us 并读取三次状态；移植保留三次一致确认，最多 30 轮，
  总线错误与超时返回调用方，不能把失败当成已经断电。
- 失败恢复时保持 genpd 逻辑状态与硬件操作一致；只有确认全部关闭才释放时钟引用，
  不在每轮恢复时重复增加引用。provider 编入内核，按原 DT compatible 匹配并按需供电。
- 不影响现有 VPU／显示域；E5 DT 中相机主域 FORCE_SHUTDOWN 为 PMU 0x2e8，
  VPU 域为 0x308/0x30c/0x314，是不同域。
- 真实 C 函数测试覆盖开关次序、每处寄存器写失败、每次状态读取失败、时钟开启失败、
  状态超时和 GPU 恢复失败清理。三机相应驱动对象编译通过。
- E5 完整构建为 `6.18.54-e5-mobile4-idle2-g020b970e351e-dirty`，包含新的相机 builtin
  provider 和 GPU 修复；已写入 E5，45 个 initramfs 模块和全部 267 个根分区模块同步，
  备份 `/root/update-backups/idle-power-1792136943`。不改 misc、Android、NV 或启动顺序。
- 启动日志在约 1.78 秒确认 `camera/DCAM/ISP domains off`；随后 WAN 自动恢复，
  infoscreen、ttyd 正常运行，未见新的 WARNING/Oops 或 SOC 保存错误。未安装的相机
  消费者会使内核报告 `sync_state() pending`，不等于相机域重新上电或相机功能已经驱动完成。

软件处理／编译检查完成，与交给用户的长期验证分开记录。用户需实测电量重启稳定性、
满充／放电、外场无覆盖后的恢复和续航；这些验证不作为完成源码修复的前置条件。

熄屏并临时停止充电的早期短时测量为约 0.6–1.2 W。三个不同时点样本均值分别为
0.827 W、0.948 W、1.087 W，无线环境／开机后时间不受控，不能据此声称已降低整机功耗。
长时间待机和电源域对照仍待验证。
同一次启动进一步进行 PSCI→仅 WFI→仅 WFI→PSCI 的短时 ABBA 对照，四段平均分别为
1.140、1.119、0.968、1.049 W；波动大于组间差异，没有稳定的整机降耗证据。
临时禁用的所有深层 idle 状态均已恢复为启用，充电控制恢复。
因此本轮只能确认 CPU 电源管理状态生效，不能宣布“耗电快”已经彻底解决。
该 fork 的深睡数据对应 E5、关闭热点等特定条件，不能外推为本仓库在线路由功耗。

## 出电梯后的自动恢复

原厂 telephony DEX 的 `Phone` 构造函数使用资源 `0x01110156` 选择数据栈；本机
framework-res 中该资源 `config_force_disable_telephony_new_data_stack=false`。
已在其 `DataNetworkController.onServiceStateChanged` 和
`shouldReevaluateNetworkRequests` 确认：PS 重新注册、RAT 变化、允许 PS attach 后
重新评估尚未满足的数据请求，未知 RAT 不直接触发 setup。不是只有一个固定倒计时循环。
实际应用仍可能受运行时资源覆盖和运营商配置影响；未宣称已还原所有运营商重试表。

当前 netifd 的 `proto_block_restart` 会清除 autostart，若无覆盖失败走这条路，信号恢复
也不会自行重拨。本次对 SIPC 的明确暂时失败，在 cached PS 状态为 searching/detached
时释放 setup、标为 unavailable，并保留 autostart。新公共服务只订阅 MM D-Bus 与
netifd 事件，PS attached、home/roaming、有效 RAT 后恢复 availability，由 netifd 按原
顺序重走 setup。它不发 AT，不禁用／启用基带，不增加周期轮询。

用户手动 ifdown、PIN/APN/鉴权错误、已连接或正在连接的 WAN 不被该服务强行拉起。
既有注册成功后的临时 PDP 错误退避表保留为兼容机制，不再把它描述为原厂精确时间表。

E5 已热部署；受控实机 availability 故障恢复到 WAN up 用时约 8.04 秒；手动 ifdown
保持关闭，随后测试脚本恢复原 WAN。此测试不等于已经完成真实电梯／弱覆盖外场验证。
最终 `modemmanager-1.24.0-r933.apk` 与配套 RPCD 已编译，直接解包核对当前 helper 内容、
执行权限、服务启停链接和协议脚本语法，构建输入／APK 校验清单一致。

## ttyd

E5、MU300 的公共 rootfs 构建均加入 ttyd、luci-app-ttyd 及翻译、开机启用。
E5 旧基础镜像的 profile 构建也安装，避免只改全新镜像漏掉增量打包。
连接的 E5 已安装并启用，监听 LAN `192.168.9.1:7681`，执行 `/bin/login`。
MU300 已同步源码，未操作当前连接的其他 MU300 系列设备。

本轮没有提交、没有重新生成三机发布安装包；安装器/APK 的其他工作区修改未覆盖。
