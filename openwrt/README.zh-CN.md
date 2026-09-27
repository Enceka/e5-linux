# 荣悦 E5 上的 OpenWrt

> English: [`README.md`](README.md)

OpenWrt 25.12 作为 E5 上的第二个 Linux，与本仓库构建的 Debian 镜像并存，做法与
[mu300-linux](https://github.com/dikeckaan/mu300-linux) 在中兴 F50 / MU300 上
让 OpenWrt 与 Ubuntu 并存一致：同一个内核和 initramfs（slot b 的 boot 镜像），
OpenWrt 自己的用户空间，外加 E5 的硬件支持。定位是路由器：5G 模组作 WAN，USB 口
和热点同在一个 LAN，带 LuCI 和 SSH。屏幕上没有图形界面（见文末）。

## 结构

* **没有自己的内核，也没有固件镜像。** E5 从 `boot_b` 启动厂商内核；initramfs
  （`boot/init`）挂载 Linux 根镜像（`/data/e5linux/rootfs.ext4`），再启动
  `e5linux/boot-os` 指定的系统：Debian 就是镜像本身，其他系统放在镜像内的一个
  目录里，OpenWrt 在 `/openwrt`。`e5linux/boot-os-next` 作用相同，但只管一次启动。
* **硬件文件用 Debian 的。** Wi-Fi/BT 固件、这个内核要的 Debian 签名
  `regulatory.db`、启动基带用的 Android vendor 子集（`/opt/e5/android`）以及内核的
  modem 模块，都已从本机提取到 Debian 根里。OpenWrt 启动时从 `/mnt/e5-disk`
  （initramfs 把镜像留挂在这里）把它们 bind 进来，不再另存一份。initramfs 也不再
  把 Debian 的 overlay（systemd 单元、NetworkManager 配置）拷进非 Debian 的根。
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
| `lib/preinit/05_e5_debian_root` | 把 Debian 根里的固件和 vendor 子集 bind 进来 |
| `etc/init.d/e5-hw` | USB gadget 守护、无线电管制数据库 |
| `etc/init.d/e5-vendor` | 基带：在 vendor chroot 里运行 `modem_control`、`cp_diskserver`、`refnotify` |
| `etc/init.d/e5-sipc-wwan` | CP 起来后提供模组的 AT 端口 |
| `etc/init.d/e5-telnetd` | 救援用 telnet，只对 USB 口开放 |
| `etc/init.d/e5-boot-ok` | 启动成功后重新武装 slot b（`e5-next-boot`） |
| `etc/hotplug.d/wwan/26-e5-sipa-eth`、`lib/udev/rules.d/78-e5-mm-sipc.rules` | 没有 udev 时的 ModemManager 衔接：AT 端口出现后再交出数据口，不探测 tty |
| `etc/hotplug.d/iface/10-e5-usb0` | 把 `usb0` 加进 `br-lan`，netifd 不碰它：NCM gadget 绝不能 down |
| `etc/uci-defaults/90-e5`、`91-e5-wireless` | 首次启动：LAN、WAN、DHCP、把承载的 IPv6 /64 放到 LAN、热点 |
| `usr/libexec/e5-sysupgrade` | 替换 `sysupgrade`：刷固件镜像会覆盖 eMMC |

两个系统共用的脚本来自 `rootfs/overlay/opt/e5`（`vendor-start.sh`、
`e5-next-boot`、`e5-os` 等）。

## 构建

在主机上（Docker，arm64，Apple silicon 上原生运行）：

```sh
openwrt/build-modemmanager.sh   # 带 unisoc 插件的 ModemManager -> out/openwrt/*.apk
openwrt/build-rootfs.sh         # -> out/openwrt/e5-openwrt-25.12.5-rootfs.tar.gz
```

`build-modemmanager.sh` 从 OpenWrt 源码树的发布 tag 构建，用发布时的 feeds 和配置，
因此编出的包与一同安装的仓库包相匹配。第一次运行会编译 OpenWrt 的主机工具和工具链
（保存在 Docker 卷 `e5-openwrt-src`），之后只重编 ModemManager。

`build-rootfs.sh` 取 OpenWrt 的 `armsr/armv8` 根文件系统，安装软件包（hostapd、iw、
bash、LuCI 的 ModemManager 协议、`out/openwrt/` 里的 ModemManager），加入
`overlay/`、共用脚本、一个完整的静态 busybox（补上 OpenWrt 版省掉的 applet），
以及 `logdw`（`src/logdw.c`，来自 mu300-linux）。

## 安装

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

* LuCI：`http://192.168.9.1`；SSH：`ssh root@192.168.9.1`；USB 口上可用 telnet。
  密码与 Debian 镜像一样是 `root`，直到用 `passwd` 修改。
* 切换系统：`e5-os debian` 或 `e5-os openwrt`，然后 `reboot`
  （`e5-os openwrt --once` 只启动一次；`e5-os status` 查看状态）。Debian 上也有
  同样的命令。
* 回 Android：`e5-next-boot android`，然后 `reboot`。
* APN：LuCI -> 网络 -> 接口 -> wan，或
  `uci set network.wan.apn=...; uci commit network; ifup wan`。
* 模组：`mmcli -m unisoc-sipc`、`e5-at 'AT+CSQ'`。
* **切勿**刷 OpenWrt 固件镜像，也不要用它运行 `sysupgrade`：该功能已禁用，因为
  armsr 镜像是整盘镜像，会覆盖分区表、Android 和引导程序。软件包用 `apk upgrade`
  更新；整个系统树在主机上重新构建后再重装。

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

尚未验证：LuCI 的 ModemManager 页面、OpenWrt 下收发短信、`--switch` 设为默认后
的多次启动。

## 暂不包含

* **屏幕上的图形界面。** 没有手机界面（OpenWrt 的 `video` feed 有 wayland、
  wlroots、weston、cage、cog、gtk 和 Mesa 的 panfrost，但没有 Phosh）。屏幕上运行的
  是信息屏：cage + cog 跑在 panfrost 上，状态页面可用触摸和键盘操作。它放在单独的
  仓库 `e5-infoscreen` 里，装在这棵系统树之上。
* **蓝牙。** 没有启动 `btattach`，BT 核心保持关闭（从内核 `0026` 起不会影响 Wi-Fi）。
* **音频、带声音的通话。** 和 Debian 一样，通话音频尚未解决；音频模块不加载。
