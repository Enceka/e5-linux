# 荣悦 E5 上的 OpenWrt

> English: [`README.md`](README.md)

OpenWrt 25.12 作为 E5 上的第二个 Linux，与本仓库构建的 Debian 镜像并存，做法与
[mu300-linux](https://github.com/dikeckaan/mu300-linux) 在中兴 F50 / MU300 上
让 OpenWrt 与 Ubuntu 并存一致：同一个内核和 initramfs（slot b 的 boot 镜像），
OpenWrt 自己的用户空间，外加 E5 的硬件支持。定位是路由器：5G 模组作 WAN，USB 口
和热点同在一个 LAN，带 LuCI 和 SSH。屏幕上没有图形界面（见文末）。

## 结构

* **没有自己的内核，也没有固件镜像。** E5 从 `boot_b` 启动厂商内核；initramfs
  （`boot/init`）挂载 userdata，启动其中 `e5linux/boot-os` 指定的系统
  （`e5linux/boot-os-next` 只管一次启动；两者都由 `e5-os` 写入）。OpenWrt 有两种形式：
  * **独立安装**：自己的根镜像 `/data/e5linux/openwrt.ext4`，不需要 Debian。旁边没有
    Debian 镜像（`/data/e5linux/rootfs.ext4`）时启动的就是它；有的话由 `e5-os` 选择。
  * **装在 Debian 镜像里**：Debian 根镜像内的一个目录 `/openwrt`。
* **硬件文件。** Wi-Fi/BT 固件、这个内核要的 Debian 签名 `regulatory.db`、启动基带用的
  Android vendor 子集（`/opt/e5/android`）以及内核的 modem 模块，都是从本机提取的。
  独立镜像自带这些文件，另带信息屏用的 Noto Sans CJK 字体。目录形式则在启动时从
  `/mnt/e5-disk`（initramfs 把 Debian 镜像留挂在这里）把 Debian 根里的那份 bind 进来，
  不另存一份。initramfs 只把 Debian 的 overlay（systemd 单元、NetworkManager 配置）
  拷进 Debian。
* **userdata** 在运行的系统里位于 `/mnt/e5-data`（initramfs 把挂载移到这里），根镜像和
  `e5linux/boot-os` 都在其中。
* **模组和 Debian 一样由 ModemManager 管**：用 OpenWrt 自己的软件包，加上 unisoc
  插件重新编译（`rootfs/deb-patches/modemmanager-0*.patch`，同一套补丁），再用
  OpenWrt 为它提供的 netifd 协议：`wan` 是 `proto modemmanager`，模组为
  `unisoc-sipc`。`mmcli`（短信、小区信息、`--command`）和 Debian 上是同一个程序。
* **其余都用 OpenWrt 的**：netifd（`br-lan` = USB + 热点）、防火墙（fw4）、
  dnsmasq、odhcpd、hostapd（wpad）、LuCI、dropbear。

OpenWrt 对仓库其他部分的要求：内核选项 `CONFIG_BRIDGE_VLAN_FILTERING`（netifd 的
网桥要用），ModemManager 补丁 `06`（模组尚未定义的上下文也能写入初始 EPS 承载），
以及上面提到的 `boot/init` 改动。原因见 `docs/FINDINGS.md` 第 39 节。

E5 另外需要的东西在 `overlay/` 里：

| | |
|---|---|
| `lib/preinit/05_e5_debian_root` | 把 Debian 根里的固件和 vendor 子集 bind 进来（目录形式） |
| `etc/init.d/e5-hw` | USB gadget 守护、无线电管制数据库 |
| `etc/init.d/e5-vendor` | 基带：在 vendor chroot 里运行 `modem_control`、`cp_diskserver`、`refnotify` |
| `etc/init.d/e5-sipc-wwan` | CP 起来后提供模组的 AT 端口 |
| `etc/init.d/e5-telnetd` | 救援用 telnet，只对 USB 口开放 |
| `etc/init.d/e5-boot-ok` | 启动成功后重新武装 slot b（`e5-next-boot`） |
| `etc/hotplug.d/wwan/26-e5-sipa-eth`、`lib/udev/rules.d/78-e5-mm-sipc.rules` | 没有 udev 时的 ModemManager 衔接：AT 端口出现后再交出数据口，不探测 tty |
| `etc/hotplug.d/iface/10-e5-usb0` | 把 `usb0` 加进 `br-lan`，netifd 不碰它：NCM gadget 绝不能 down |
| `etc/uci-defaults/90-e5`、`91-e5-wireless`、`92-e5-default-boot` | 首次启动：LAN、WAN、DHCP、把承载的 IPv6 /64 放到 LAN、热点；从 Android 安装时把 Linux 设为默认启动 |
| `etc/init.d/e5-luci`、`usr/libexec/e5-luci-revision` | LuCI 的“蜂窝网络”页把模组修订版本按行拆成单独的行（Platform Version、Project Version、BASE Version、HW Version、Build），不再挤成一行；构建时和每次启动时都会应用 |
| `etc/uci-defaults/93-e5-luci` | 首次启动：LuCI 设为中文和 Argon 主题（都已预装；Argon 用其发布页的软件包，版本和校验值固定在 `build-rootfs.sh` 里） |
| `etc/init.d/e5-apn-auto`、`usr/libexec/e5-apn-auto` | 没有指定 APN 时（`network.wan.apn_auto=1`），每次启动按 SIM 卡运营商（MCC+MNC）自动设置 APN |
| `etc/init.d/e5-sms-notify`、`usr/libexec/e5-sms-notify` | 新短信时震动（`e5-vibrate`，设置在 `/etc/config/e5-notify`），并记为未读（`/tmp/run/e5-sms/unread`，`e5-sms-notify read` 清除） |
| `etc/init.d/e5-charge`、`usr/libexec/e5-charge` | 充电控制：到上限停止充电，降到下限重新充电，可临时充满一次（`/etc/config/e5-charge`，通过 charger-manager 的 `stop_charge`） |
| `usr/libexec/e5-sysupgrade` | 替换 `sysupgrade`：刷固件镜像会覆盖 eMMC |

两个系统共用的脚本来自 `rootfs/overlay/opt/e5`（`vendor-start.sh`、
`e5-next-boot`、`e5-os` 等）。

## 构建

在主机上（Docker，arm64，Apple silicon 上原生运行）：

```sh
openwrt/build-modemmanager.sh   # 带 unisoc 插件的 ModemManager -> out/openwrt/*.apk
openwrt/build-rootfs.sh         # -> out/openwrt/e5-openwrt-25.12.5-rootfs.tar.gz（目录形式）
E5_STANDALONE=1 openwrt/build-rootfs.sh   # -> out/openwrt/e5-openwrt-25.12.5.ext4.gz（独立安装）
```

`build-modemmanager.sh` 从 OpenWrt 源码树的发布 tag 构建，用发布时的 feeds 和配置，
因此编出的包与一同安装的仓库包相匹配。第一次运行会编译 OpenWrt 的主机工具和工具链
（保存在 Docker 卷 `e5-openwrt-src`），之后只重编 ModemManager。

`build-rootfs.sh` 取 OpenWrt 的 `armsr/armv8` 根文件系统，安装软件包（hostapd、iw、
bash、LuCI 的 ModemManager 协议、`out/openwrt/` 里的 ModemManager），加入
`overlay/`、共用脚本、一个完整的静态 busybox（补上 OpenWrt 版省掉的 applet），
`logdw`（`src/logdw.c`，来自 mu300-linux），以及 `e5-vibrate`（`src/e5-vibrate.c`，
驱动 PMIC 的震动马达）。如果信息屏仓库就在本仓库旁边（`../e5-infoscreen`，或用
`E5_INFOSCREEN=<目录>` 指定；`E5_INFOSCREEN=` 留空则不包含），它的软件包和文件也会
一并装进系统树。

`E5_STANDALONE=1` 会补上目录形式从 Debian 根里取的东西：固件
（`rootfs/overlay/lib/firmware`，由 `rootfs/pull-wcn-firmware.sh`、
`pull-audio-firmware.sh` 提取）、vendor 子集（`work/android-subset`，由
`rootfs/extract-android-vendor.sh` 提取）、内核构建产物里的 `wwan.ko` 和 `sipc_wwan.ko`
（`out_linux`，须与 boot 镜像的内核是同一次构建），以及取自 Debian `fonts-noto-cjk` 的
Noto Sans CJK；然后把系统树打包成 1 GiB 的 ext4 镜像（`E5_IMAGE_MB` 可改；带信息屏约用
330 MB）。固件和 vendor 子集是这台设备自己的文件，不在仓库里：请为自己的设备构建镜像。

## 安装

### 独立安装

boot 镜像须支持 OpenWrt 独立镜像（2026-09-27 之后的 `boot/init`，native18 或更新）。
在设备上运行的 Linux（Debian，或任一形式的 OpenWrt）中，通过 USB LAN：

```sh
openwrt/install-standalone.sh            # 安装 /data/e5linux/openwrt.ext4
openwrt/install-standalone.sh --try      # 安装，并启动一次 OpenWrt
openwrt/install-standalone.sh --switch   # 安装，并把 OpenWrt 设为默认
```

设备从主机下载镜像，运行 `device-install-image.sh`：解包到已装镜像旁边，并保留已有
OpenWrt 的配置（正在运行的那个，否则是已装的镜像，再否则是 `/openwrt`）：`/etc/config`、
密码、SSH 密钥、流量记录。用 `apk` 另装的软件包不会带过去。在还没有 OpenWrt 的 Debian 上
安装时，会像 `install.sh` 一样取 Debian 的 APN 和热点设置。在独立 OpenWrt 自身里更新时，
新镜像先存为 `openwrt.ext4.new`，下次启动时由 initramfs 换上，旧镜像保留为
`openwrt.ext4.old`。

从已 root（Magisk）的 Android 通过 adb 安装，适用于从没跑过 Linux 的设备：

```sh
openwrt/install-standalone.sh --adb --apn <APN> --wifi-key <密码>
boot/flash-trial.sh work/boot-linux-slotb-<名称>.img
```

APN 和热点（`--ssid`，默认 `E5-Linux`）写到 userdata 上的
`e5linux/openwrt-install.conf`，供首次启动使用；不给密码时热点保持关闭。OpenWrt 起来后
运行 `e5-next-boot linux`，设备就会一直启动它。之后可以删掉 Debian：删除
`/mnt/e5-data/e5linux/rootfs.ext4`，OpenWrt 就成了唯一的系统。

### 给别人用的一键刷入包

```sh
openwrt/make-flash-bundle.sh   # -> out/openwrt/e5-openwrt-flash-<版本>-<git>.tar.gz
```

一个压缩包，解压后在装有 adb 的 macOS 或 Linux 上运行 `./flash.sh`：从 Android 给已解锁
bootloader、装了 Magisk 的 E5 安装 OpenWrt；之后可通过 USB 网络更新（`--update`，保留设置），
或从 Android 再次启动它（`--boot-openwrt`）。说明书是 `bundle/README.zh-CN.md`。包里是通用镜像
（`E5_DEVICE_FILES=0`）和不带 Debian overlay 的 boot 镜像，不含本机的任何文件：本机的固件和
vendor 文件属于厂商，且带有本机身份信息（pskey 里的蓝牙地址、Android 属性里的序列号），overlay
里还有本机的 MAC 地址和热点配置。`flash.sh` 用 `rootfs/pull-wcn-firmware.sh`、
`pull-audio-firmware.sh` 和 `extract-android-vendor.sh` 提取每台设备自己的文件，打包成 userdata
上的 `e5linux/device-files.tar`，由 boot/init 解到镜像里。没有指定 APN 时按 SIM 卡自动选择
（`e5-apn-auto`）。

### 装在 Debian 镜像里

E5 运行 Debian，可通过 USB LAN（192.168.9.1）访问：

```sh
openwrt/install.sh            # 安装 /openwrt
openwrt/install.sh --try      # 安装，并启动一次 OpenWrt
openwrt/install.sh --switch   # 安装，并把 OpenWrt 设为默认
```

设备从主机下载 tarball，运行 `device-install.sh`：解包到 `/openwrt`，并从 Debian
取来 OpenWrt 需要一致的设置，即 NetworkManager `Mobile` 连接的 APN、`Hotspot` 的
SSID、密码和信道，以及默认启动项。重装会保留 OpenWrt 的配置。boot 镜像须带有当前的
`boot/init`（native13 或更新）。

## 使用

* LuCI：`http://192.168.9.1`（中文界面、Argon 主题；可在 系统 → 系统 → 语言和界面 中更改）；SSH：`ssh root@192.168.9.1`；USB 口上可用 telnet。
  密码与 Debian 镜像一样是 `root`，直到用 `passwd` 修改。
* 切换系统：`e5-os debian` 或 `e5-os openwrt`，然后 `reboot`
  （`e5-os openwrt --once` 只启动一次；`e5-os status` 查看状态和已安装的系统）。
  Debian 上也有同样的命令；信息屏只提供“下次启动 Android”，启动 Debian 留给命令行。
* 回 Android：`e5-next-boot android`，然后 `reboot`。
* APN：LuCI -> 网络 -> 接口 -> wan，或
  `uci set network.wan.apn=...; uci commit network; ifup wan`。
* 模组：`mmcli -m unisoc-sipc`、`e5-at 'AT+CSQ'`。
* **切勿**刷 OpenWrt 固件镜像，也不要用它运行 `sysupgrade`：该功能已禁用，因为
  armsr 镜像是整盘镜像，会覆盖分区表、Android 和引导程序。软件包用 `apk upgrade`
  更新；镜像（或系统树）在主机上重新构建后再重装。

## 状态

已在设备上验证（2026-09-27，用 `--try` 全新安装）：

| | |
|---|---|
| 启动 | 从根镜像内的 `/openwrt` 启动，可一次性（`boot-os-next`）或设为默认；一次性启动之后回到 Debian；启动完成时重新武装 slot b |
| LAN | `br-lan` 192.168.9.1/24 = `usb0` + `wlan0`；USB 主机固定拿到 192.168.9.2（与 Debian 一样不给默认路由），其他客户端 .10-.200 |
| 基带 | CP 由 vendor chroot 里的 `modem_control` 启动；ModemManager 的 unisoc 插件驱动 `wwan0at0` + `sipa_eth0`，上下文 1 使用从 Debian 取来的 APN |
| WAN | `proto modemmanager`：IPv4 默认路由走 `sipa_eth0`，LAN 走 NAT；设备本身有 IPv6，每个 LAN 客户端也从承载的 /64 获得 IPv6（SLAAC，无 NAT） |
| 热点 | hostapd，5 GHz 149 信道 / 80 MHz，WPA2-PSK，SSID 和密码与 Debian 一致；手机能连上并拿到地址 |
| 管理 | telnet（仅 USB 口）、SSH、LuCI；`e5-os`、`e5-next-boot`、`e5-at` |
| 独立安装 | 从 Debian 用 `--try` 安装：从 `openwrt.ext4` 启动（loop，已用 287 MB），保留了 `/openwrt` 的配置和流量记录；模组、WAN、热点和信息屏都用镜像自带的固件、vendor 子集、模块和字体正常运行；在它内部更新，新镜像在下次启动时换上 |

尚未验证：LuCI 的 ModemManager 页面、OpenWrt 下收发短信、`--switch` 设为默认后
的多次启动。

## 暂不包含

* **屏幕上的图形界面。** 没有手机界面（OpenWrt 的 `video` feed 有 wayland、
  wlroots、weston、cage、cog、gtk 和 Mesa 的 panfrost，但没有 Phosh）。屏幕上运行的
  是信息屏：cage + cog 跑在 panfrost 上，状态页面可用触摸和键盘操作。它放在单独的
  仓库 `e5-infoscreen` 里，装在这棵系统树之上。
* **蓝牙。** 没有启动 `btattach`，BT 核心保持关闭（从内核 `0026` 起不会影响 Wi-Fi）。
* **音频、带声音的通话。** 和 Debian 一样，通话音频尚未解决；音频模块不加载。
