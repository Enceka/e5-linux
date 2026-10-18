# WPA3 热点连接失败：分析与公共适配

日期：2026-10-15。范围：E5 公共 OpenWrt 构建及 MU300 仓库的 SC2355 驱动。

## 结论与验证边界

现有配置界面能提供 WPA3-SAE 选项，但这不代表展锐固件热点的 SAE
认证接口已经接通。两边存在相同的用户态/驱动适配缺口；E5 另有 PMF
显式关闭值残留的风险。不能把换成完整版 wpad 当成完整修复。

已补齐下述公共代码、配套 APK 和构建校验。T551M 已热部署，纯 WPA3 与
WPA2/WPA3 混合模式均已完成手机客户端 SAE 握手、PMF 和上网验证。

## 1. 包含 SAE，但界面没有验证固件认证链路

两个构建脚本均安装 `wpad-basic-mbedtls`。OpenWrt 25.12 的 hostapd
Makefile 对 mbedtls 变体设置 `CONFIG_SAE=y`，包说明也包括 WPA3-Personal。

已打包 LuCI 的 `view/network/wireless.js` 根据
`L.hasSystemFeature('hostapd', 'sae')` 等软件功能展示加密选项。
这是软件编译能力判断，不能确认展锐固件所需接口完整可用。

官方源：
<https://github.com/openwrt/openwrt/blob/openwrt-25.12/package/network/services/hostapd/Makefile>

## 2. 固件热点认证与标准 hostapd 之间缺少桥接

MU300 可直接核对的代码在 `upstream/modules/sprd_wlan_combo/`；E5 检查的是
当前构建树 `/home/kano/e5-live-20261014/linux/drivers/unisoc_platform/sprd_wlan_combo/`。

两边的关键行为一致：

- `sc2355/init.c` 根据固件能力设置 `WIPHY_FLAG_HAVE_AP_SME`，认证状态机
  由设备/固件参与；同时无条件设置 `NL80211_FEATURE_SAE`。
- `sc2355/vendor.c` 的 `vendor_set_sae_password()` 接受展锐私有命令
  `VENDOR_CMD_SET_SAE_PASSWORD`（43，OUI `0x001374`），检查固件的
  `SPRD_EXTEND_SOATAP_WPA3`（BIT(6)），再通过 `CMD_SET_SAE_PARAM` 下发。
- `sc2355_start_ap()` 主要向固件发送 beacon，没有把标准
  `settings->crypto.sae_pwd` 交接到上面的 SAE 参数命令。
- 没有声明标准 `NL80211_EXT_FEATURE_SAE_OFFLOAD_AP`；也没有实现
  `.external_auth` / `cfg80211_external_auth_request()` 这条标准外部认证链路。

对照官方 OpenWrt 25.12 hostapd：标准 AP SAE offload 密码下发依赖
`SAE_OFFLOAD_AP` 能力，使用 `NL80211_ATTR_SAE_PASSWORD`。设备 SME 的
外部认证路径则需要驱动配合处理认证交互和结果。这些路径没有自动调用
展锐私有的命令 43。

核对的官方 hostapd 源码包：
`hostapd-2025.08.26~ca266cc2.tar.zst`，SHA-256：
`59ac677093f524ff98588abd9f33805a336a6e929d6814222f0d784c854f2343`，
与 OpenWrt 分支 Makefile 的 `PKG_MIRROR_HASH` 一致。

因此不能只凭 `iw`/LuCI 出现 SAE，或源码里有 SAE 常量，就判定 WPA3 热点
已经支持。MU300 的旧 FINDINGS §14 还记录过 WPA3 上联关联失败，但那个
记录属于 STA 模式，不能用来替代本次 AP 模式验证。

## 3. E5 的 PMF 关闭值可能随切换保留下来

`openwrt/overlay/etc/uci-defaults/91-e5-wireless` 显式写入
`ieee80211w='0'`，这对默认 WPA2 配置有效。

离线 rootfs 的 `/lib/netifd/hostapd.sh` 在 SAE 模式使用
`set_default ieee80211w 2`，混合模式通常默认 1。`set_default` 不覆盖
已有的 0。如果切换加密方式时没有清除这个旧值，就可能产生关闭 PMF 的
SAE 配置。LuCI 有自己的动态默认值和写入行为，因此不能断言所有界面操作
都会保留 0；需要检查最终 UCI 和生成的 hostapd 配置。

WPA3-only 要求 PMF；混合模式允许传统 WPA2 客户端不启用 PMF，但 SAE
客户端仍需满足相应保护要求。不能用关闭 PMF 来修 WPA3。

官方配置说明：
<https://android.googlesource.com/platform/external/wpa_supplicant_8/+/refs/heads/main/hostapd/hostapd.conf>

## 验收要求

1. 接通标准 hostapd 到展锐固件的 SAE 认证路径。选择固件卸载或外部认证
   方案前，确认固件能力、命令顺序、PMK 交接、失败传播和 PMF 密钥处理；
   不能仅设置能力位或仅发送密码就宣称完成。
2. 加密方式切换时正确处理 PMF 默认值，兼顾网页、脚本和已有配置升级；
   保持 WPA2 用户配置语义，不强行全局开启 PMF。
3. 固件不支持时明确拒绝所选模式，不要静默改成 WPA2，也不要只发布一个
   无法关联的热点。
4. 分别验证 WPA2、WPA3-only、WPA2/WPA3 mixed、修改密码和重启后重连。
   混合模式手机连上还不够，必须确认客户端实际使用 SAE 而非 WPA2 回退。
5. 实机验证需覆盖 E5/T551M/M8 及 MU300 PCIe 系列的实际固件差异。
   密码、PMK 不得写入诊断日志。

## 已实现的修复

### 原厂认证链路的逆向结论

对本机提取的 Android `vendor/bin/hw/hostapd` 进行了 AArch64 反汇编核对。
原厂不是完整四次握手卸载：固件负责 SAE，hostapd 负责 EAPOL 四次握手。
固件在 NEW_STATION 关联信息尾部附加私有 IE：

```text
dd 34 40 45 da 04 <PMK:32> <PMKID:16>
```

这不是需要客户端发送的空中协议。Android 在关联事件中提取这些数据，
将该 station 标记为 SAE，随后正常执行四次握手。本修复沿用这条链路，
不会伪造已授权状态，也不声明完整四次握手卸载。

### 内核与 hostapd

- 仅在固件同时支持 SoftAP WPA3、AP SME 和 802.11w 时公布 AP SAE 卸载能力。
- 同时公布至少三种 AKM 的下发容量。混合模式实际携带 PSK、PSK-SHA256、
  SAE，旧的默认容量为二，hostapd 因此省略整个 AKM 属性；驱动看不到 SAE，
  就不会给固件设置密码。实机复测已经确认并修复这个独立问题。
- START_AP 之前，把标准 SAE 密码转换为原厂命令 85：请求类型 2，
  ENTRY、PWD、END 三组 16 位小端 TLV；密码不附加 NUL。
- 保留命令串行锁，传播锁获取失败、命令被关闭路径拦截和固件拒绝的错误。
- 固件 AP SME 接管 AUTH 帧，避免 hostapd 注册 AUTH 后把认证帧从固件引走。
- hostapd 仅对明确启用 `unisoc_sae=1` 的此类接口导入固件 PMK/PMKID。
  严格检查 IE 长度、重复项、RSN 的 SAE 和 PMF；缺失密钥时只允许真实 PMKSA
  缓存重连。WPA2 不使用该密钥，SAE 切回 WPA2 时清理旧 station 状态。
- 调试输出隐藏 SAE 密码命令及带 PMK 的关联事件，不记录密码和密钥。

### 配置与构建

- 从 WPA2 切换到 SAE 后，生成配置会纠正遗留 PMF=0：纯 SAE 使用必需 PMF，
  混合模式至少启用可选 PMF。不会全局改写 WPA2 的 PMF 设置。
- 仅 SC2355 生成私有桥接配置。默认使用已逆向确认的传统 SAE
  hunting-and-pecking、group 19；不支持的 H2E/FT-SAE/额外组明确拒绝，
  不静默退回 WPA2。不宣称支持 WPA3 R3 的 H2E 或 6 GHz。
- 同时接入 OpenWrt 25.12 默认 ucode 生成器和可选旧 shell 生成器。
  只修 shell 文件并不会影响默认 ucode 路径。
- 此类固件接口关闭 RSN Override 广告。实机发现固件未把 RSN Selection
  扩展完整带入关联事件，混合模式会在四次握手的消息 2/4 上校验失败。
  保留正常校验，禁用不兼容的扩展，不绕过 EAPOL 检查。
- 只有固件 SAE BSS 配置发生变化时才完整重启 AP，再下发密码；配置未变的
  普通 reload 保留连接。Linux SET_BEACON 没有 crypto 更新回调，原先的
  原地 BSS 更新不能保证新密码进入固件。
- 固定 OpenWrt 25.12.5 与对应 hostapd 源码哈希，重建并配套安装
  `wpad-basic-mbedtls`、`hostapd-common`、`wifi-scripts` 三个 APK。
- 显式保留 AC/AX/BE 编译开关。外置展锐模块不经过 OpenWrt 的 kmod 选择，
  不能依赖它自动打开这些开关，否则旧热点的 VHT 配置都会被新 daemon 拒绝。
- E5 三机型内核准备流程、原生构建及容器构建均接入同一适配；MU300 的
  公共 SC2355 模块和 rootfs 构建同步。增量重打包检查源码指纹和三个 APK
  哈希，避免旧 rootfs 丢掉用户态修复。

## 已执行验证

- 两仓库的 C 测试使用 ASan/UBSan 执行实际共用头文件，检查 1～63 字节
  密码编码、能力/错误分支、PMK/PMKID 交接、截断/重复 IE、PMF、缓存重连、
  分配失败和 SAE/WPA2 状态切换；配置生成 shell 测试也通过。
- E5 内核相关对象、MU300 的 6.18.54 与 7.2.8 相关对象编译通过。
- T551M 使用实机相同 BTF 和版本、相同 Clang 18 工具链编译完整模块，
  实机加载成功并出现 `SAE_OFFLOAD_AP` 能力。
- 配套 APK 交叉编译、离线清单校验、ARM64 容器安装和程序加载通过。
- 实际 ucode 策略测试通过，包括非展锐接口隔离、PMF、显式 H2E 配置保留、
  以及禁用不兼容 RSN Override。
- T551M 纯 WPA3 与混合模式都观察到 `auth_alg=sae`、四次握手完成、
  `authorized=true`、`mfp=true`；用户分别确认可以正常连接和上网。
- 实机临时更换和恢复密码时，分别确认固件收到新的 SAE 密码命令，
  原密码已恢复；不在日志中记录密码内容。
- 重启验证发现 Wi-Fi 驱动在 initramfs 中提前加载，单独更新根分区的 `.ko`
  只在手动重载后生效。T551M 已同步更新现有 boot_b 内的那一份模块，
  校验只改变该文件，内核、启动参数、其余 initramfs 文件与持久日志区保留。
  再次重启后 `SAE_OFFLOAD_AP` 仍存在，热点自动启动。
- 本次恢复了 T551M 原来的 `psk2+ccmp` 设置，未改变原密码；后续可自行
  在网页选择 WPA3 或混合模式。修复及配套软件包保留。

不包含 E5、M8 或 MU300 系列手机客户端的实机关联验收。不同固件仍需分别验证。
