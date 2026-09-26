# 在荣悦 E5（Unisoc UMS9621）上运行 Linux

> English: [`README.md`](README.md)

本项目为荣悦 E5 5G 手机/随身热点（`ums9158_1h10`，Unisoc UMS9621 / qogirn6lite，
Android 13）移植 Linux，做法与 [mu300-linux](https://github.com/dikeckaan/mu300-linux)
为中兴 F50 / MU300 所做的一致：以设备自身的 GPL 内核源码构建定制内核，配合一个
initramfs——它建立 USB gadget，再切换到完整的 Linux 根文件系统。系统安装在 slot b，
与 Android **并存**，不改写分区表。

内核源码为 [`kernel_sprd_ums9158`](https://github.com/Enceka/kernel_sprd_ums9158) 的
`linux-staging` 分支（Google android13-5.15 GKI + Unisoc UMS9621 平台，含 E5 设备支持及
本项目的补丁），由 `kernel/build-linux.sh` 在设备自带的 `e5_rongyue_defconfig` 基础上
重新构建为通用 Linux 内核。

> **警告。** 本项目会写入 `boot_b` 以及 `misc` 中的 32 字节，并依赖 bootloader 回退到
> slot a。该机制是 mu300-linux 针对这一 bootloader 系列记录的行为，但**尚未**在本机型上
> 验证。可能导致设备变砖或数据丢失。本项目与 Unisoc、荣悦均无关，也未获其认可。
>
> **电池。** 充电可以工作，但前提是加载了 `aw32257_charger.ko`。该驱动的名称与其所驱动
> 的硬件不一致；缺少它时，充电器还会使 USB 完全不可用——`fw_devlink` 在 USB 控制器的
> probe 函数运行前检查其设备树 supplier，而充电器正是其中之一（`docs/FINDINGS.md`
> 第 7.2 节）。
>
> **启动哪个系统。** 安装根文件系统后，Linux 即为持久默认系统（`/etc/e5linux/default-boot`
> 为 `linux`，`e5-boot-ok` 在每次成功启动后重新设定 slot b）；在 Linux shell 中执行
> `e5-next-boot android` 可切回 Android。若某次启动未能进入用户空间，设备仍会自行回退到
> slot a。未安装根文件系统时，initramfs 以独立模式运行，除非存在 `/run/stay`，否则十分钟
> 后重启回 Android。

## 为什么不是 mu300-linux 的照搬

E5 有三处实质性差异，每一处都改变了设计：

| | MU300（UMS9620） | 荣悦 E5（UMS9621） |
|---|---|---|
| eMMC 空闲空间 | `userdata` 之后有未分区空间 | **无**——`userdata` 恰好结束于 GPT 最后一个可用 LBA |
| ramdisk 的来源 | `boot` | `boot`（仅当 `boot` 的 ramdisk 为空时 LK 才回退到 `init_boot`） |
| 内核 | 中兴 GPL 源码的 5.4.254 | E5 源码树中的 5.15.211 GKI + Unisoc 平台 |

由于没有空闲空间，根文件系统以 loop 文件的形式存放在 Android 的 `/data` 中
（`/data/e5linux/rootfs.ext4`），而不是独立分区。这保留了项目沿袭下来的“绝不改动 GPT”
原则。

上述每一项结论的实测依据见 [`docs/FINDINGS.md`](docs/FINDINGS.md)：显示 LK 选用哪个
ramdisk 的 bootloader 日志、`misc` 中的实时 `bootloader_control`、GPT 的精确计算，以及
启动失败后仍能保留的日志通道。

## 状态

| 功能 | 状态 |
|---|---|
| 定制 Linux 内核（5.15.211，`e5_rongyue_defconfig` + Linux 配置片段） | ✅ 可构建 |
| 启动镜像构建器（slot b，保留原厂 header/vbmeta/footer） | ✅ |
| ramdisk 位于 boot.img（LK 的 generic ramdisk 路径） | ✅ 已在原厂 LK 日志中确认 |
| `boot_b` 试启动 + 在 `misc` 中一次性设定 slot | ✅ **可启动** |
| Linux 未进入用户空间时回退到 Android | ✅ 已验证——设备回到 slot a |
| initramfs：67 个按依赖排序的模块，USB ECM + ACM 控制台 | ✅ |
| **Linux 在设备上启动** | ✅ **67/67 个模块加载，无遗留 deferred** |
| USB gadget 网络（NCM） | ✅ usb0 与热点为同一局域网，`br0` 192.168.9.1/24（dnsmasq DHCP；USB 主机固定获得 192.168.9.2，不下发默认路由）；initramfs 救援模式仍使用 192.168.77.1 |
| Linux 下电池充电 | ✅ **已验证——`battery/status = Charging`** |
| DRM/KMS 显示（480x320 DSI 屏，现为 `card1`——`card0` 由 panfrost 占用） | ✅ phoc 完成 modeset（活动 plane `320x480`，`allocated by = phoc.orig`） |
| Debian 13 + Phosh 根文件系统 | ✅ SDDM 自动登录 `phosh.desktop` |
| Phosh 会话（phoc，wlroots GLES2 渲染器运行于 Mali-G57） | ✅ **已验证**——`GL renderer: Mali-G57 (Panfrost)`，客户端同样运行其上；docs/FINDINGS.md 第 20.7 节 |
| 在 Linux 内重新设定 slot（`e5-boot-ok`） | ✅ 已验证，`misc` 逐字节比对 |
| Linux 下触摸屏 | ✅ **可用**——`tlsc6x_touch` 位于 `event1`，udev 标记为 `ID_INPUT_TOUCHSCREEN=1`，phoc 接收其事件 |
| Wi-Fi | ✅ **已在设备上验证**——WCN 芯片上的 `sprd_wlan_combo` + `wcn_bsp`，开箱即可扫描 2.4 GHz 与 5 GHz AP（需要 initramfs overlay 中的固件以及厂商的 *user* 构建变体）；docs/FINDINGS.md 第 8.5–8.6 节 |
| 蓝牙 | ✅ 内核按厂商 HAL 的方式配置 marlin3 核心（经 `request_firmware` 发送 pskey/RF/启用，关闭 tty 前发送核心禁用）——出厂地址 `FC:B5:85:D0:85:9B`，可扫描、可连接；内核补丁 `0018`、`0021`，FINDINGS §33.3、§35。⏳ 音频 profile 未测试 |
| 会话时长 | ✅ 已修复：约 295 秒的静默重启来自 PMIC 看门狗；加载负责喂狗的 sprd_pmic_wdt.ko 后，会话可持续运行 10 分钟以上——docs/FINDINGS.md 第 9 节 |
| 基带、数据 | ✅ **原生**：`sipc_wwan` 把 AT 通道注册为 WWAN 端口（内核 `0022`、`0023`），ModemManager 的 `unisoc` 插件驱动它（打过补丁的 modemmanager，见 `rootfs/deb-patches/`），NetworkManager 的 `Mobile` 连接在 `sipa_eth0` 上建立数据（IPv4 + IPv6）；5G SA、Phosh 显示信号、Chatty 读取短信；CP 仍由 chroot 中的 Android `modem_control` 启动——FINDINGS §36、§37；短信收发、VoLTE 电话拨打和接听均正常（Chatty、Calls）。⏳ 通话音频：双方目前都听不到声音 |
| 基带备用方案 | [`unisoc-cpd`](https://github.com/Enceka/unisoc-cpd) 仍然安装但不启用：`systemctl start unisoc-cpd` 会从 ModemManager 手中收回基带（运行时页面位于 `http://192.168.9.1:7887`） |
| UFI-TOOLS（Linux 移植版） | ✅ `http://<设备>:2333`，修改前登录口令为 `admin` |
| 热点 | ✅ NetworkManager 的 `Hotspot` 连接（Phosh 的开关和设置里的 Wi-Fi 面板已打补丁可识别它；UFI-TOOLS、`nmcli` 也可控制），5 GHz 149 信道 / 80 MHz（使用打过补丁的 network-manager，见 `rootfs/deb-patches/`），SSID `E5-Linux`，作为 `br0` 的端口与 USB 端口同网；IPv4 经 NAT 走承载，承载的公网 IPv6 /64 通过 SLAAC 分配给所有局域网客户端（带状态防火墙）——FINDINGS §35 |
| 音频 | ✅ 扬声器与麦克风均已实际使用验证（Amberol、GNOME 录音机、设置中的声音测试）：扬声器经 ALSA（UCM `HiFi`/`Speaker`，S16 交错格式）与 PipeWire 播放，麦克风为 “Internal Microphone” 音源（DSP 录音，单声道 S16）；`e5-audio.service` 从 `l_agdsp_a` 启动 AGDSP；内核补丁 `0010`–`0014`、`0017`、`0019`、`0020`，FINDINGS §24.8、§33、§34。⏳ 听筒尚未实听 |
| 空闲负载 | ✅ 空闲时负载均值约为 0（此前因厂商内核线程处于 `D` 状态及同步控制台输出而读数在 6 以上）——内核补丁 `0015`，FINDINGS §29 |

## 仓库结构

| 路径 | 内容 |
|---|---|
| `kernel/` | `build-linux.sh`、`e5-linux.fragment`（在设备 defconfig 之上追加的 Linux 配置）、`patches/0001-0026`（由 `build-linux.sh` 应用） |
| `boot/` | `init`（initramfs）、`build-boot-image.py`、`stage-modules.sh` + `module-order.{stock,extra}`、`flash-trial.sh` / `android-boot-linux.sh`（从 Android 执行）、`flash-from-linux.sh`（从运行中的 e5-linux 执行） |
| `rootfs/` | `build-rootfs-container.sh`（及 `rootfs-in-container.sh`，在 Debian arm64 容器中构建）、`install-rootfs.sh`、`packages.list`、`configure-rootfs.sh`、`fetch-debian-rootfs.py`、`install-packages.sh`、`pull-wcn-firmware.sh` / `pull-audio-firmware.sh` / `extract-android-vendor.sh`（从你的设备提取文件）、`stage-unisoc-cpd.sh`、`overlay/`；`device-*.sh` 与 `build-rootfs.sh`/`e5-chroot.sh` 是较早的设备端构建与 qemu 构建路径 |
| `tools/` | `collect-logs.sh`、`e5-telnet.py`、`e5-serial.py`，以及截图/按键/触摸辅助工具 |
| `docs/` | `FINDINGS.md`（实测记录与走不通的路）、`STATUS.md`（工作清单） |

**不包含**：原厂固件、Android 厂商二进制、设备转储。脚本会从*你自己的*设备上读取这些内容。

## 前置条件

* 一台 bootloader 已解锁的荣悦 E5（`ro.boot.verifiedbootstate=orange`），Android 已 root 且
  `adb` + `su` 可用，并具备恢复手段（SPD 下载模式或已知可用的原厂镜像）。
* 装有 `clang`/`lld`（LLVM）、`make`、`python3`、`lz4` 的 Linux 构建主机。在 macOS 上，这意味着
  使用 brew 的 `make`（系统自带的是 GNU Make 3.81，kbuild 要求 ≥ 3.82）、供 kbuild 脚本使用的
  `coreutils` + `gnu-sed`、提供 `llvm-objdump`/`llvm-nm`/`llvm-objcopy` 的 `llvm`，以及一个包含
  `elf.h` 的目录供 `scripts/mod` 使用（本仓库中为 `work/hostinc/`）。
* 可选：带 `aarch64-unknown-linux-musl` 目标的 Rust 工具链，仅在重新构建 `unisoc-cpd` 时需要
  （overlay 中已包含静态二进制）。
* Docker，用于构建根文件系统：`rootfs/build-rootfs-container.sh` 在 arm64 的 `debian:trixie`
  容器中安装软件包，以原生速度运行。`rootfs/e5-chroot.sh` 是面向 Linux 主机的非特权 qemu
  路径，无法在 macOS 上运行。
* 需自行制作的转储：slot b 的原厂启动镜像，以及 `misc` 的前 4 KiB（见下文）。
* 基带需要 Android 厂商文件子集（由 `rootfs/extract-android-vendor.sh` 从设备提取，约
  49 MiB）：缺少它时 `e5-vendor.service` 会被跳过，没有 CP、没有 `/dev/stty_nr1`，也就没有基带。
  这部分为专有文件，不会进入镜像，需单独放入 `/opt/e5/android/`。

## 构建与运行

### 0. 转储

```sh
mkdir -p dumps
adb shell 'su -c "dd if=/dev/block/by-name/boot_b of=/data/local/tmp/boot_b.img"'
adb pull /data/local/tmp/boot_b.img dumps/boot_b.img
adb shell 'su -c "dd if=/dev/block/by-name/misc of=/data/local/tmp/misc.bin bs=4096 count=1"'
adb pull /data/local/tmp/misc.bin dumps/misc-head.bin
```

### 1. 内核

```sh
git clone -b linux-staging https://github.com/Enceka/kernel_sprd_ums9158   # 克隆到本仓库目录内
kernel/build-linux.sh
```

`linux-staging` 是在设备源码树之上提交了 e5-linux 改动的分支（`main` 为厂商发布的原始源码树）。
`KERNEL_TREE` 默认为 `./kernel_sprd_ums9158`，`O` 默认为 `./out_linux`。脚本随后将
`kernel/patches/*.patch` 与源码树比对——在 `linux-staging` 上每个补丁都显示“已应用”；在不含
这些补丁的源码树上则会应用它们——并将版本字符串固定在 `.scmversion` 中，避免打过补丁的源码树
变成 `-dirty`；随后将 `kernel/e5-linux.fragment` 合并进 `arch/arm64/configs/e5_rongyue_defconfig`，
若 initramfs 依赖的配置项未能保留则立即报错，最后构建 `Image`、模块与 DTB。

### 2. 模块与 initramfs

```sh
boot/stage-modules.sh          # -> out_modules/, boot/module-order.txt
```

initramfs 按**原厂 first-stage 的顺序**（而非字母顺序）`insmod` 这些模块；这一点为何至关重要，
见 `docs/FINDINGS.md` §3。

initramfs 需要一个静态 arm64 busybox：

```sh
mkdir -p work/busybox/ext && cd work/busybox
curl -O http://ports.ubuntu.com/ubuntu-ports/pool/main/b/busybox/busybox-static_1.36.1-6ubuntu3.1_arm64.deb
ar x busybox-static_*.deb && tar --zstd -xf data.tar.zst -C ext ./usr/bin/busybox
cd -    # -> work/busybox/ext/usr/bin/busybox
```

### 2a. 从设备提取固件与厂商文件

overlay 的 `lib/firmware/` 中只包含无线电管制数据库；WCN（Wi-Fi/BT）固件、AGDSP 镜像与音频
参数均为厂商文件，需在设备处于 Android 状态（adb + su）时从*你自己的*设备提取：

```sh
rootfs/pull-wcn-firmware.sh      # wcnmodem.bin、gnssmodem.bin、wifi_board_config*.ini、MAC 地址
rootfs/pull-audio-firmware.sh    # l_agdsp_a.img、audio_structure、dsp_vbc、cvs、aw87xxx_acf.bin
rootfs/extract-android-vendor.sh # -> work/android-subset/（modem_control 及其运行环境）
```

前两个脚本的结果放入 `rootfs/overlay/`，随启动镜像一同分发；厂商文件子集则单独安装到根文件
系统中（第 3 步）。

### 2b. unisoc-cpd（可选）

overlay 中已包含构建好的 `unisoc-cpd`（`usr/local/bin/`、`etc/unisoc-cpd/` 及 systemd 单元）。
如需从其独立仓库的检出更新：

```sh
git clone https://github.com/Enceka/unisoc-cpd
rootfs/stage-unisoc-cpd.sh       # 构建、复制，并应用 Linux 侧的修改
```

该副本只应通过此脚本更新：它关闭 profile 中仅适用于 Android 的 NAT，将 Web 页面绑定到局域网
（`192.168.9.1`，仅限 USB 端口访问），并在 `etc/unisoc-cpd/VERSION` 中记录所用提交。

### 3. 根文件系统（全新安装）

根文件系统是 Android `/data` 中的一个 loop 文件而非分区，因此只需构建并推送一次，更换启动镜像
时无需重建：

```sh
rootfs/build-rootfs-container.sh            # 全部阶段 -> out/rootfs.ext4（8 GiB）
rootfs/install-rootfs.sh out/rootfs.ext4    # 以 1 GiB 分块推送、校验、发布
```

`build-rootfs-container.sh` 将 `rootfs/packages.list` 中的软件包（phosh——自 2026-09-19 起的唯一
会话，Plasma Mobile 及其 X11 已从列表中移除；Wi-Fi 与热点所需的 NetworkManager/`wpasupplicant`、NAT 所需的 `nftables`、
pipewire 等）安装到 Debian trixie arm64 目录树中，覆盖 `rootfs/overlay/`，从 `out_linux/` 中
放入音频模块（因此需先构建内核），创建 `e5` 用户，启用各服务单元，并打包输出。镜像**默认大小为
8 GiB**（可用 `E5_IMG_MIB=N` 覆盖）：该 loop 文件是设备上唯一可写的文件系统，若打包为恰好容纳
现有内容的大小，第一次 `apt install` 就会没有空间。

各阶段可单独重新运行，后续修改 overlay 或软件包时正需如此：

```sh
rootfs/build-rootfs-container.sh configure pack           # 仅修改了 overlay
rootfs/build-rootfs-container.sh install configure pack   # 软件包列表有变化
```

`install-rootfs.sh` 在已 root 的 Android 上运行（`adb` + `su`）：删除旧的
`/data/e5linux/rootfs.ext4` 以腾出空间，分块推送新镜像，在设备上比对 sha256，然后重命名到位。
它创建的账户为 `e5`/`123456` 和 `root`/`root`（已启用自动登录，触屏会话不会询问密码）。

基带是**唯一不在镜像中**的部分。Android 厂商文件子集为专有内容，既不提交到仓库也不打包进镜像；
请在系统启动后安装（loop 文件可写，安装后会保留）。Linux 下不挂载 userdata，因此经由 USB 局域网
传输：

```sh
tar -C work -cf work/android-subset.tar android-subset
( cd work && python3 -m http.server 8000 --bind 192.168.9.2 )   # USB 主机的固定地址
# 在 e5-linux 的 shell 中（telnet 192.168.9.1 或 USB 串口控制台），以 root 身份执行：
cd /tmp && /usr/local/bin/busybox wget http://192.168.9.2:8000/android-subset.tar
mkdir -p /opt/e5 && tar --no-same-owner -xf android-subset.tar -C /opt/e5
mv /opt/e5/android-subset /opt/e5/android && systemctl start e5-vendor e5-sipc-wwan ModemManager
```

`--no-same-owner` 必不可少：bionic 拒绝解析不属于 root 的 `__properties__` 目录。`e5-vendor`
运行期间切勿再用 `chown -R` “修正”属主——chroot 中绑定挂载了 `/dev`、`/proc` 与 `/sys`，递归操作
会改写运行中的设备节点（FINDINGS §28）。在厂商文件子集就位之前，`e5-vendor.service` 会被跳过
（`ConditionPathExists=`），`/dev/stty_nr1` 返回 `ENODEV`，ModemManager 找不到基带。

### 4. 启动镜像

```sh
boot/build-boot-image.py \
  --stock-boot dumps/boot_b.img --misc-head dumps/misc-head.bin \
  --kernel out_linux/arch/arm64/boot/Image --modules out_modules \
  --busybox work/busybox/ext/usr/bin/busybox --overlay rootfs/overlay \
  --out boot-linux-slotb.img
```

输出 `boot-linux-slotb.img`、一份 `.json` 清单，以及用于设定 slot 的 `.misc-slot-b-trial.bin`。

**`--overlay` 不可省略。** 缺少它时 initramfs 中完全没有 `e5-overlay/`：没有 `wcnmodem.bin`、没有
systemd 单元、没有 `/etc/environment`——设备可以启动，但只是一个没有 Wi-Fi 固件、没有服务的裸系统。
此外，`boot/init` 每次启动都会将 overlay 覆盖到根文件系统上，因此镜像中的副本优先于在设备上手动
修改的内容（`/var/lib` 除外，它只在文件缺失时写入初始值）——请修改 `rootfs/overlay/` 后重新构建。
构建器以 `a+r`（可执行文件为 `a+rx`）打包 overlay，而非沿用检出目录中的权限；曾有构建主机因
umask 过严生成了 0600 的 `phoc.ini`，导致 `e5` 用户的会话完全无法启动。

### 5. 刷写

首次刷写在已 root 的 Android 上执行：

```sh
boot/flash-trial.sh boot-linux-slotb.img
```

**只**写入 `boot_b` 与 `misc` 中 32 字节的 `bootloader_control`；`boot_a`、`init_boot_*`、
`vendor_boot_*`、GPT 与 `userdata` 均不受影响。脚本在设定 slot 之前，分别在本地、设备上和分区上
校验镜像哈希；若 `misc` 的当前内容不是预期的 slot a 状态，则拒绝执行。

尚未安装根文件系统时，设备以独立 Linux 模式启动：telnet `192.168.77.1`（或 USB CDC-ACM 控制台）——
十分钟后（安全定时器，正式会话会将其停止）或内核 panic 时重启回 Android。如需在 Android 中再次
启动 `boot_b` 中已有的 Linux 镜像而不重新刷写：

```sh
boot/android-boot-linux.sh boot-linux-slotb.img
```

之后的镜像均可从运行中的 e5-linux 经 USB 局域网刷写，无需回到 Android：脚本通过 HTTP 提供镜像，
写入并校验 `boot_b`，设定 slot b 后重启。

```sh
boot/flash-from-linux.sh boot-linux-slotb.img
```

### 6. 使用

| | |
|---|---|
| 局域网 | `br0` = USB 端口（NCM）+ 热点，设备地址为 `192.168.9.1`；USB 主机固定获得 `192.168.9.2` 且无默认路由，热点客户端获得 `.10`–`.200`；所有客户端均从承载的 /64 获得公网 IPv6 地址 |
| shell | `telnet 192.168.9.1`（`root`/`root`，仅限 USB 端口），或 USB CDC-ACM 串口控制台 |
| 账户 | `e5`/`123456`（phosh 会话自动登录）、`root`/`root` |
| 热点 | SSID `E5-Linux`，WPA2 密码 `12345678`，客户端位于 192.168.9.0/24 |
| 基带 | ModemManager：Phosh 的移动网络设置、Calls、Chatty、`mmcli -m any`；数据是 NetworkManager 的 `Mobile` 连接（`nmcli c up/down Mobile`）；原始 AT 用 `e5-at 'AT+CSQ'` |
| UFI-TOOLS | `http://192.168.9.1:2333`（仅限 USB 端口），口令 `admin`；命令行 `ufi-tools status`、`ufi-tools set-token` |
| 切回 Android | `e5-next-boot android && systemctl reboot` |

设备离开你的桌面之前，请修改各账户密码、热点密码与 UFI-TOOLS 口令。对于来自网桥 Wi-Fi 侧的帧
以及来自上行链路的一切连接，telnet、gotty 与 UFI-TOOLS 均会被丢弃（`etc/e5/nat.nft`），
因此热点客户端和互联网都无法访问它们——USB 线缆即管理端口。

### 7. 读取结果

```sh
tools/collect-logs.sh logs
```

在某次启动回退到 Android 之后，此命令会拉取 `/sys/fs/pstore/*`、`boot_b` 内 4 MiB 的持久日志以及
bootloader 日志。pstore 控制台中的 `E5-LINUX: stage=…` 行是 initramfs 报告的启动进度。

## 致谢与许可

* 内核源码：Google android13-5.15 GKI 与 Unisoc UMS9621 平台，发布于
  `Enceka/kernel_sprd_ums9158`——GPL-2.0。
* 方法、仓库结构及若干脚本源自 [`dikeckaan/mu300-linux`](https://github.com/dikeckaan/mu300-linux)（MIT）。
* 本仓库中的脚本、工具与文档：MIT（见 `LICENSE`）。
* 原厂固件、Android 厂商组件与 bootloader 归其各自所有者所有，不在此分发。
