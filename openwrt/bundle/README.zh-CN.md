详细使用流程请先看根目录 **START-HERE.md**，运行根目录 **OpenWrt-Installer.exe** 或 **OpenWrt-Installer.py** 后选择菜单。

# OpenWrt 一键刷入包（E5 / T551M / VIPME M8）

新版完整 ZIP 同时支持 Magisk 内首次部署 TF 卡和电脑解压自定义安装。**详细使用指南位于安装包顶层 `START-HERE.md`**。
快捷 `.cmd`/`.sh` 全部放在 `launchers/`；镜像和校验清单位于 `files/`，其他辅助文件在 `scripts/`、`docs/`、`extras/`。
Magisk 内刷入完整固件会清空所选 TF 目标（第一分区，无分区则整卡），不是仅安装切换按钮；需要稳定供电及足够的 Android 临时空间。
原生 Magisk 入口使用本机固件、先校验再写盘，成功后手动重启。新流程仍需逐机型实刷验证。


> English: [`README.md`](README.md)

请使用与机型对应的包，不能跨机型刷入。包内 `files/device-profile.json` 标明目标机型；
安装和升级会检查机型。没有此文件的旧包仅适用于 E5。

把 OpenWrt 25.12（带 5G 上网、热点、LuCI 和屏幕信息屏）装到设备上，与原来的 Android
共存：Android 不动，OpenWrt 装到 **SD 卡**（已有第一分区，无分区表时整卡；所选目标用满）上，从 `boot_b` 启动。
随时可以回到 Android。没有 TF 卡时可用 `install-part` 装到手机存储自己的一块内部分区
（对 userdata 缩容，Android 的文件保留）。

包内入口均为英文名称，Windows 用 `.cmd`，Linux/macOS 用 `.sh`：

| 入口 | 用途 |
| --- | --- |
| `OpenWrt-Installer.exe` / `start-installer` | 打开方式选择菜单；Windows 有 exe 时无需另装 Python |
| `install-to-tf-card` | TF 卡首次安装，会清空所选 TF 目标 |
| `install-to-userdata-image` | 未加密 userdata 内创建指定大小的镜像 |
| `install-to-internal-storage` | 缩容 userdata、创建独立根分区；加密 data 需同意清空 |
| `reinstall-internal-system` | 覆盖已有 e5root，不重新缩容、不格式化 Android data |
| `resume-internal-install` | 输入之前保存的 transaction.json，继续两阶段安装 |
| `switch-to-openwrt` | 从 Android 切回已经安装的 OpenWrt |
| `update-openwrt` | 更新正在运行的 OpenWrt |

`scripts/installer` 是内部程序，不需要手动运行。旧命令行选项仍保留，包内已不再使用含糊的 `flash` / `install-part` 入口名。

## 需要

* 与安装包对应的设备，**bootloader 已解锁**，Android 已用 **Magisk、KernelSU 或 KSUNext** 获取 root；安装器使用随包携带的静态 ARM64 BusyBox，不依赖管理器的工具路径；
* Android 在 slot a 运行（出厂状态就是）；
* 卡槽里插一张 **4 GB 以上的 SD 卡**（建议 8 GB）：所选目标会清空并用满，不修改分区表；
  或者运行 `launchers/install-to-internal-storage.cmd` / `bash launchers/install-to-internal-storage.sh`，无需插卡；
* 一台 Windows、macOS 或 Linux 电脑，装有：
  * **Python 3.8 或更新版本**（Windows 包内有 `OpenWrt-Installer.exe` 时无需安装；其他情况从 https://www.python.org/downloads/ 安装）；
  * **adb**（Android platform-tools：https://developer.android.com/tools/releases/platform-tools ，
    解压后把目录加入 PATH，或者把 `platform-tools` 文件夹放到刷机包目录里）；
  * Windows 还需要设备的 USB 驱动（多数情况下系统会自动安装）；
* USB 数据线。

## 刷入

1. 在设备上打开 USB 调试，用数据线连上电脑，在手机上允许调试；
2. 在 root 管理器里给 **Shell** 超级用户权限（第一次运行时手机会弹窗，选允许）；
3. 解压刷机包，在目录里运行：

   * **Windows**：双击 `launchers/start-installer.cmd`（或在命令提示符里运行 `launchers/start-installer.cmd`）；
   * **macOS / Linux**：`./launchers/start-installer.sh`

   想先确认设备没问题、什么都不写入，可以先运行 `launchers/start-installer.cmd --check` / `./launchers/start-installer.sh --check`。

   脚本会询问 APN、热点名称和密码。APN 直接回车即可：OpenWrt 会按 SIM 卡的运营商自动选择
   （移动 `cmnet`、联通 `3gnet`、电信 `ctnet`、广电 `cbnet`；其他运营商用网络默认的 APN），
   换卡后也会自动更新。密码直接回车会生成随机密码并在最后显示。也可以写在命令行里：

   ```sh
   launchers/start-installer.cmd --ssid E5-OpenWrt --wifi-key 12345678 -y        (Windows)
   ./launchers/start-installer.sh --ssid E5-OpenWrt --wifi-key 12345678 -y       (macOS / Linux)
   ```

   在清空所选 **SD 目标** 之前会再确认一次，需要输入 `yes`；输入别的或不回答都会中止，
   卡不会被改动。（`-y` 跳过所有询问。）

4. 等脚本显示“完成”，再手动重启进入 OpenWrt；安装器不自动重启，第一次启动约 2 分钟。

脚本做的事情：

* 检查刷机包完整性、设备状态（root、slot a、已解锁、启动控制块）和剩余空间；
  启动控制块按本机 BCAB 格式、CRC 和槽位状态检查，不再要求与打包设备逐字节相同。
* **从这台设备自己的 Android 里提取** Wi-Fi/蓝牙/音频固件和启动基带所需的 vendor 文件，打包成
  `/data/e5linux/device-files.tar`。刷机包里不带任何设备的固件：这些文件属于厂商，而且带有
  每台设备自己的信息（蓝牙地址、序列号），所以每台设备用自己的；
  固件提取、转换及镜像上传均在清卡之前完成，缺文件或上传失败不会先清卡。
* 检查两槽的 `uboot/sml/teecfg/trustos/vbmeta`。Android 释放 TF 后，对有差异的
  启动链先备份 A、B 两份至 `/data/adb/e5-bootchain/`，再从 A 同步到 B 并回读校验。
  相同项不重写；失败尝试恢复 B 原内容，任何失败都不会继续切槽。不会同步 NV。
* 使用 **SD 卡** 已有第一分区，无任何分区时才使用整卡。写入 OpenWrt 镜像，离线检查并扩到
  所选目标全部容量；initramfs 通过 `/etc/e5/sd-root` 标记直接挂载。分区表不变，不预留 OTA 空间；
* 把这台设备自己的文件解包进去，首次启动的设置写到它的 `/etc/e5/install.conf`；
  卸载、刷新缓存后以只读方式重新挂载，复核关键文件和固件 SHA-256，通过后才写 boot。
* 把启动镜像写入 `boot_b` 并校验，然后让下次启动走 slot b。**slot a 的 Android 不会被改动。**
  同时记录 userdata 上的 `e5linux/boot-os` 启动目标；最后备份本机 misc 的 32 字节
  启动控制信息、生成 B 槽试启动状态并回读校验。启动链备份也保存在 Android data 内。

## 使用

### 安装到内置分区（无需 TF 卡）

Windows 双击 `launchers/install-to-internal-storage.cmd`，Linux/macOS 运行 `bash launchers/install-to-internal-storage.sh`。
脚本显示分区大小范围并让你输入（默认：镜像大小 + 1 GiB），再问是否**完全使用空间**把根
文件系统扩满整个分区（默认 yes：扩满所选分区，明确选 no 才保留镜像约 2 GiB 容量），随后**确认三次**才开始落位。
下次启动由引导镜像完成三件事：把 userdata 缩到所选大小、建立 `e5root` 分区、把 OpenWrt
写入其中——不格式化 userdata，Android 的文件保留。首次启动是试启动，起不来会自动回退。
回 Android：屏幕或 shell 里 `e5-next-boot android`，或删掉 `/data/e5linux/boot-os` 后重启。
此后的重装或改大小，在运行中的 OpenWrt 里用 `device-install-to-internal-storage.sh`。

* 热点：用刷机时设置的名称和密码连接；或用 USB 线连接电脑（USB 网卡）。
* 管理页面 LuCI（中文、Aurora 主题）：`http://192.168.9.1`，用户 `root`，密码 `root`，**请尽快修改**
  （LuCI → 系统 → 管理权，或 SSH 里运行 `passwd`）。
* SSH：`ssh root@192.168.9.1`。
* 屏幕：左右键翻页，确认键按按钮，返回键返回；“高级”里有网络模式、频段、APN、充电控制等设置。

## 回到 Android

* 屏幕：高级 → 系统 → 下次启动 Android；
* 或 SSH 里：`e5-next-boot android && reboot`。

从 Android 临时启动已安装的 OpenWrt（不重装、不挂载根分区、不改变默认启动设置）：连上电脑运行

```sh
launchers/start-installer.cmd --boot-openwrt          (Windows；macOS / Linux：./launchers/start-installer.sh --boot-openwrt)
```

如果 OpenWrt 启动失败，设备会在两次尝试后自动回到 Android。

电脑安装器的 `--boot-openwrt` 只检查启动镜像和启动链，然后写入并回读 misc 的 32 字节启动控制块。
不挂载／修复根文件系统，不写启动选择或默认启动标记，不同步启动链；默认启动策略仍由 OpenWrt 自己管理。
独立的 Magisk 切回模块不是此电脑入口，不要混为一谈。
本安装器仍要求 Android A、Linux B，不能在 Android B 下反向安装。
TF 与 MU300 一样使用已有第一分区（无任何分区时才用整卡）的全部容量，不预留更新空间、不改 GPT。

## 加密 userdata 的内置分区安装

运行 `launchers/install-to-internal-storage.cmd`（Linux/macOS 用 `./launchers/install-to-internal-storage.sh`）。未加密 data 默认保留原有缩容安装流程；
检测到 FBE、metadata 或块级加密，必须明确同意清空 Android 用户数据，改走两阶段安装：

1. 选择 OpenWrt 分区大小。若需要用满，选择扩展整个文件系统，或传入 `--grow-fs`。
2. 电脑保留设备身份、分区计划、原 boot_b、启动控制和启动链备份。initramfs 直接重建分区布局，
   不读取旧 data，不执行保数据缩容；随后进入**原厂 recovery**，由原厂完成恢复出厂及加密初始化。
3. 回到 Android 后完成首次设置，重新开启 USB 调试、授权电脑，恢复 Magisk/Shell root 权限。
   如果 recovery 要求确认清空数据，需要在设备上确认。原厂 recovery 的实际行为仍需逐机型验证。
4. 电脑确认设备和新分区边界一致，再直接写入独立 `e5root`，导入本机固件、设置，校验容量后切换启动目标。
   安装完成后手动重启进入 OpenWrt。Android 即使重新启用加密也不影响独立根分区启动。

电脑脚本会等待重新授权；也可以退出，稍后运行：

```text
launchers/start-installer.cmd --resume-part "backups/part-日期-标识/transaction.json"
```

保留原安装包及整个备份目录，不要再次从第一阶段开始。备份目录含设备镜像和热点设置，请勿公开。
无人值守模式需显式 `--part --format-userdata -y`，单独 `-y` 不授权清空 Android。
旧启动镜像不支持此流程，会在刷写前拒绝；需重新构建完整安装包。

安装屏幕每 2 秒显示阶段和耗时，写镜像时显示实际写入量；文件系统检查、搬移不显示虚构百分比。
选择用满空间时采用挂载前扩容，并读取 ext4 超级块验证；失败时保留载荷和日志，不报告安装完成。
系统显示的可用容量会扣除文件系统元数据等开销，10 GiB 分区不会有整整 10 GiB 可用空间。

## 覆盖重装（已装过的情况）

已经装过内置分区系统的设备，再跑 `install-part` 会被拒绝（避免误动已建好的分区）。要换一套系统进去、但
**保留 Android 用户数据、userdata 文件系统和分区表**，用覆盖重装：

```text
launchers/reinstall-internal-system.cmd                       （等同于 launchers/start-installer.cmd --reinstall-part；macOS/Linux：./launchers/reinstall-internal-system.sh）
launchers/start-installer.cmd --reinstall-part          （交互：打印几何与热点设置，确认一次）
launchers/start-installer.cmd --reinstall-part -y       （无人值守）
```

它会：读设备上现有的 userdata/e5root 几何 → 从 Android 拉取本机固件 → 把包里的新镜像写进 e5root
（`e2fsck` 检查、扩到分区大小、写回原有热点/APN 设置与 `part-root`/`part-trial` 标记）→ 刷新 `boot_b`
并按 B 槽武装 → 手动重启进入新系统。不重建分区、不清 Android 数据、不走第一阶段；e5root 里原有系统及其
配置会被替换，事务记录留在 `backups/reinstalls/日期-标识/transaction.json`。

## 更新

安装失败时请保留完整终端报错：程序会显示失败的步骤（分区、写镜像、挂载、
解包设备文件或检查内容）、设备返回的错误和退出码，以及 SD/ext4 内核日志。
内容检查会列出缺失、空文件或没有执行权限的具体路径。分区前会检查卡容量和
只读状态；Android 卷无法卸载时会停止，尚未修改分区表。

设备正在运行 OpenWrt、用 USB 线连着电脑时，用新的刷机包运行：

```sh
launchers/start-installer.cmd --update                (Windows；macOS / Linux：./launchers/start-installer.sh --update)
```

它会通过 USB 网络的 SSH 主动上传并校验更新文件，不需要电脑开放入站 HTTP 端口。Windows EXE 已内置 SSH 依赖；直接运行 Python 脚本时需要先安装 paramiko。随后更新启动镜像和 OpenWrt 镜像，**保留 OpenWrt 的设置**（`/etc/config`、密码、
SSH 密钥、流量记录、信息屏上装的应用）。用 `apk` 另装的软件包不会保留。

**装在 SD 卡上**（默认方式）时，统一由电脑安装器通过 SSH 上传及校验。
保存配置和固件，校验新 boot 后发布请求，重启到 initramfs，再把载荷复制到内存并验证，
卸载原根后离线更新它，扩回原分区容量，恢复配置和本机固件。不创建新根分区、不改 GPT，
也不需要未分配的 OTA 空间。原始写入期间请保持供电，单根系统没有 TF 双根回退能力。
旧多根卡仍可启动，更新只改当前根并保留其代数；不自动删除或合并其他旧分区。

装在手机存储里（`--data`）时，新镜像在重启后生效，旧镜像保留为
`/mnt/e5-data/e5linux/openwrt.ext4.old`。

**缩容 userdata 后的独立 `e5root` 分区**现在也使用同一个更新入口，无需进入 Android。
电脑上传并校验载荷，设备保存配置和本机固件，校验新 boot 后才发布更新请求。
重启进入 initramfs 后，把所有载荷复制到内存并再次校验，卸载原分区，再写入新系统、
回读校验、扩容到原分区容量、恢复配置和固件，最后重新启动。
Android userdata（包括加密 data）和 GPT 均不修改，10 GiB 分区仍保持原容量。
内置分区与新版 TF 单根一样没有另一根分区的自动回退能力；写入阶段请保持供电。
屏幕会每两秒显示阶段、耗时和写入进度。自行安装的 APK 不迁移。

## 卸载

回到 Android 后，在 root shell 里执行 `echo android > /data/e5linux/boot-os`（或删掉该文件），
这样卡不再是启动目标，然后把卡取出来，用任意分区工具清掉它的分区即可。`boot_b` 里的启动
镜像留着也不影响 Android（Android 从 slot a 启动）。

## 免责声明

本刷机包为非官方软件，与荣悦及设备、芯片厂商无关，也未获其认可。刷机需要解锁 bootloader 和
root，可能导致设备失去保修、数据丢失或无法正常使用；修改网络、频段、AT 指令和充电设置也可能
导致断网或设备异常。本软件按“原样”提供，不作任何担保，**风险由使用者自行承担**。刷机前请备份
重要数据；所选频段和无线设置请遵守当地法规。

## 维护者与许可

Enceka <enceka@yeah.net>。脚本和 e5-linux 部分为 MIT 许可（见 `LICENSE`）；OpenWrt、Linux 内核
等组件遵循各自的许可（GPL 等），源码见 OpenWrt 官方和 e5-linux 仓库。
