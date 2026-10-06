# 荣悦 E5 上的 OpenWrt

> English: [`README.md`](README.md)

当前使用 **OpenWrt 25.12.5 + E5 主线 6.18.y 内核**。Android 保留在 A 槽，Linux
使用 B 槽。设备面板运行信息屏及其应用，电话拨号盘／通讯录就在信息屏里；LuCI
是独立的路由器网页管理界面。

## 安装与更新

从 [Releases](https://github.com/Enceka/e5-linux/releases) 下载完整主线刷入包，解压后
Windows 运行 `flash.cmd`，macOS／Linux 运行 `./flash.sh`，按包内说明和安装器操作。
首次安装从已 root 的 Android 开始，提取目标设备自身固件和 vendor 文件；通用镜像
不携带这些文件，也不包含用户设备身份。

推荐 SD 安装：写入前检查空间，仅分配可移除卡，保留 Android eMMC 分区表。
共享 `e5boot` 注册表管理所选系统和各系统槽位，旧 userdata 独立镜像与目录安装
仍可使用。

已运行 OpenWrt、通过 USB 连接电脑时：

```sh
./flash.sh --update
```

更新保留配置、通讯录、转发设置和持久短信收件箱。内核和根目录模块必须来自同一次
构建。失败时先看完整错误，安装器会显示失败阶段和设备返回内容。

## 日常使用

- USB 管理局域网：设备 **192.168.9.1**，电脑通常是 **192.168.9.2**；USB 与热点
  共用 `br-lan`。移动网络通过 ModemManager 提供 IPv4／IPv6。
- **信息屏 → 应用 → 电话：** 同一页面包含拨号盘和通讯录。电话插件 1.5 支持
  本次拨号选卡、来电来源卡；铃声、震动和亮屏可在插件设置中调整。
- **单卡启动：** 首选上网卡槽为空时自动选择已插卡的槽；基带初始化跳过空槽。
  LuCI 基带页保留物理 SIM1／SIM2 编号，并显示当前上网卡；双卡时保留选卡设置。
- **LuCI → 服务 → 短信：** 双卡合并／分别查看收件箱，显示来源卡，发送时选卡，
  转发可共用配置或按卡分别设置。收发短信不切换上网卡。
- **信息屏 → 设置 → USB：** 重置 USB 连接、一键检查连接，便于排查 USB／热点。
- 在信息屏启动设置切回 Android，或执行 `e5-next-boot android` 后重启。
  [Magisk 模块](../magisk/README.md) 提供从 Android 手动切回已安装 Linux 的“操作”
  按钮，保留 SD 当前系统选择。

## 双卡验证范围

当前组合：内核 `6.18.54-e5-00072-g020b970e351e`，ModemManager
`1.24.0-r918`，信息屏核心 `1.6.7`，电话插件 `1.5`。

双卡短信接收、发送和来源标记已验证；SIM2 拨出听筒下行和来电提醒已验证。
SIM2 麦克风上行、来电接听音频、持续 30 秒通话仍未验证。设备共用一条语音前端，
已有通话时再次拨号会返回忙，不会自动挂断现有通话。
实现、测试记录和原生选卡接口见 [MULTISIM.md](MULTISIM.md)。

## 构建与发布

在主仓库根目录执行：

```sh
docker build -t e5-mainline-build upstream/
E5_RELEASE=1 upstream/build.sh
openwrt/build-modemmanager.sh
openwrt/build-bluez.sh
E5_MAINLINE=1 E5_TOOLS_BUILD_IMAGE=e5-mainline-build openwrt/make-flash-bundle.sh
```

需要已有启动模板、BusyBox 和信息屏构建输入，准备方法见
[RELEASE.md](../docs/RELEASE.md)。`build-rootfs.sh` 会拒绝旧的或未经校验的
ModemManager APK；软件包构建运行通话身份与路由测试，不访问真实基带。
通用包输出到 `out/openwrt/`，发布校验检查后端／界面源码、模块版本和 ZIP／TAR 内容。

GitHub Actions 编译并发布主线刷入包和 Magisk ZIP，编译时间为 UTC+8、精确到秒。
启动后由 ModemManager、vendor CP 运行库和音频服务接管硬件，网络待注册完成后可用。

硬件服务在 `overlay/`，共享脚本在 `../rootfs/overlay/opt/e5/`，Unisoc MM 补丁在
`../rootfs/deb-patches/`。旧 5.15／vendor 和 userdata 目录安装保留作兼容路径，
当前一键包使用主线内核、推荐 SD 安装。
