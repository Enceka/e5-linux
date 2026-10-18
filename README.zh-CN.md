# Unisoc 设备上的 Linux

Windows EXE 与 Apple Silicon APP 共用 [桌面安装器](installer/README.md)，支持 TF、
内部分区安装与覆盖重装、两阶段续装、SSH 更新和 Android 卸载。操作前阅读包内
`START-HERE.md` 或 [安装指南](installer/GUIDE.md)。TF 安装会覆盖已有第一分区；
仅在卡上没有分区表时使用整卡，文件系统扩到所选目标容量。同一个 ZIP 也可交给 Magisk 安装到 TF。

[English](README.md)

本项目维护荣悦 E5、T551M 和 VIPME M8 的 Linux 启动、内核适配及用户空间构建。
支持 Debian 13 / Phosh 和 OpenWrt；设备配置通过 `sprd-linux-devs` 的独立 Git 仓库管理。

## 设备与系统

| 设备 | Debian | OpenWrt | 说明 |
| --- | --- | --- | --- |
| 荣悦 E5 / UMS9621 | 已适配 Phosh | 已适配 | SD 多系统是推荐布局，兼容旧 userdata loop 镜像 |
| T551M | 暂无配置 | 试运行适配 | 独立充电、GPIO 背光、32 位 vendor runtime 和 NV 隔离 |
| VIPME M8 / UMS9620 | 暂无配置 | bring-up | 独立内核、显示、USB 和音频适配，尚非正式发布镜像 |

设备的实测范围、构建参数和试运行限制见各自说明：
[E5](https://github.com/sprd-linux-devs/linux_device_e5/blob/main/README.md)、[T551M](https://github.com/sprd-linux-devs/linux_device_t551m/blob/main/README.md)、
[M8](https://github.com/sprd-linux-devs/linux_device_m8/blob/main/README.md)。已有设备支持不代表任意同平台机型可直接刷入。

## 获取源码

```sh
git clone --recurse-submodules https://github.com/sprd-linux-devs/e5-linux.git
cd e5-linux
```

已有检出更新后执行：

```sh
tools/sync-device-repos.sh
python3 tools/device-layout.py list
```

主仓库固定每个 submodule 的提交。同步脚本恢复这些提交，不自动跟随子仓库的最新分支。
内核完整源码另行检出到 `linux-lts-e5/`：

```sh
git clone --branch e5-6.18 https://github.com/sprd-linux-devs/linux.git linux-lts-e5
```

各设备适配器可能要求固定内核提交，应以设备 README 和脚本的校验为准。

## 仓库分层

所有设备仓库均来自 [sprd-linux-devs](https://github.com/sprd-linux-devs)，
路径与仓库名一致：`device/[系统名称]_device_[型号]`；通用仓库使用 `common`。
`linux` 层用于发行版共用的内核适配和运行脚本，`debian` / `openwrt` 层用于各系统的配置。

| 主仓库路径 | 职责 |
| --- | --- |
| `device/linux_device_common/` | 共用内核修复、CPUFreq、Wi-Fi/USB 辅助代码、运行脚本和 regulatory.db |
| `device/linux_device_e5/`、`linux_device_t551m/`、`linux_device_m8/` | 各机型的内核、硬件/音频资源、启动和采集工具 |
| `device/debian_device_common/` | Debian 的 systemd 服务、网络配置、UFI-TOOLS 等通用用户空间 |
| `device/debian_device_e5/` | E5 的桌面、按键和设备默认值 |
| `device/openwrt_device_common/` | OpenWrt 的 procd 服务、LuCI 看板、共享安装器、声音和软件包依赖 |
| `device/openwrt_device_e5/`、`openwrt_device_t551m/`、`openwrt_device_m8/` | 各机型的 overlay、无线默认值及用户空间适配 |
| `ci/infoscreen/` | 独立的 [infoscreen](https://github.com/Enceka/infoscreen)，含合并后的屏幕界面与服务 |
| `ci/infoscreen-plugins/` | 独立的 [infoscreen-plugins](https://github.com/Enceka/infoscreen-plugins)，含电话插件 |
| `boot/`、`upstream/`、`kernel/` | 启动镜像工具、主线构建入口及旧厂商内核参考构建 |
| `rootfs/`、`openwrt/`、`magisk/` | 系统构建、安装、刷入包和 Android 切回 Linux 模块 |
| `tools/`、`docs/` | 仓库同步、overlay 合成、校验工具和实测记录 |

overlay 顺序由 [device/manifest.json](device/manifest.json) 明确声明：
`linux common → linux 机型 → 系统 common → 系统机型`，后面的文件覆盖前面的同名文件。
机型的无线模式和频段保存在自己的 overlay，通用逻辑读取这些配置。
安装到设备上的 `e5-*` / `t551m-*` 名称保留为兼容接口。

## 构建

使用具备 Docker、Python 3、LLVM/构建工具和 arm64 C 编译器的主机。
设备端适配和离线 root 操作需在 Linux / WSL 环境执行。
完整的安装与回退流程见 [OpenWrt 说明](openwrt/README.zh-CN.md)、
[SD 多系统](openwrt/MULTIBOOT.md) 和 [发布构建](docs/RELEASE.md)。

### E5 OpenWrt 发布包

```sh
E5_RELEASE=1 bash upstream/build.sh
bash openwrt/build-modemmanager.sh
bash openwrt/build-bluez.sh
E5_MAINLINE=1 bash openwrt/make-flash-bundle.sh
```

构建器会合成 OpenWrt overlay，加载独立 infoscreen 和电话插件源码。
输出位于 `out/openwrt/`；在线构建与发布入口为 [sprd-linux-devs/release](https://github.com/sprd-linux-devs/release)。发布校验同时记录设备子仓库和信息屏的提交。
`E5_DEVICE_FILES=0` 的通用包不包含目标设备的固件、校准和 Android vendor runtime。
安装器从接收设备提取它们。

OpenWrt common 的 [packages.list](https://github.com/sprd-linux-devs/openwrt_device_common/blob/main/packages.list) 包含
`openssl-util`、`curl`、`ca-bundle` 和 `msmtp`。`openssl-util` 提供 `openssl` 命令，
用于短信邮件编码和钉钉签名；构建检查 Base64 / HMAC-SHA256，发布校验拒绝缺少 OpenSSL 的镜像。

### E5 Debian

```sh
rootfs/pull-wcn-firmware.sh
rootfs/pull-audio-firmware.sh
rootfs/extract-android-vendor.sh
rootfs/build-rootfs-container.sh
```

固件提取需要目标设备在已 root 的 Android 下连接 ADB。
私有 overlay 放入 `work/device-files/e5/overlay/`；Debian 构建时在设备仓库的 overlay 之后合入。
完整参数、模块和 vendor runtime 的安装说明见 [详细构建参考](docs/E5-BUILD-REFERENCE.zh-CN.md)。

### 检查与手工合成 overlay

```sh
python3 tools/device-layout.py check --system openwrt --model t551m
python3 tools/device-layout.py overlay --system openwrt --model t551m
python3 tools/device-layout.py overlay --system debian --model e5
```

默认输出为 `work/overlays/[系统]-[型号]/`。它是构建产物，不是源码目录。
手工制作 Debian 启动镜像时，`--overlay` 应指向合成目录。
私有文件只有显式传入 `--private-overlay` 时才被合成工具加入；通用发布包不会合入它们。
T551M / M8 的专用内核与离线用户空间流程仍按设备 README 执行，不能用 E5 发布包替代。

## 新增设备

1. 在组织中建立 `linux_device_[型号]` 和所需系统的 `[系统]_device_[型号]` 仓库。
   增加 `profile.json`、`overlay/`、硬件适配及设备 README。
2. 将仓库添加为同名路径的 submodule，并在 `device/manifest.json` 声明依赖和覆盖顺序。
3. 将共享修复放入对应的 common 仓库；将型号、频段、充电、音频和启动策略放入机型仓库。
4. 在目标设备验证后，再扩展发布构建和支持状态。只有配置文件不代表已验证支持。

修改子仓库时，先提交并推送子仓库，再在主仓库提交更新后的 gitlink。
info screen 的前端、API 和屏幕服务直接在 `ci/infoscreen` 修改；电话应用在插件仓库修改。
旧的 T551M `infoscreen/base` 和按源码锚点打补丁的生成步骤已移除，来源提交记录保留在信息屏仓库的迁移说明。
主仓库原有公开提交历史保留。

## 安装与使用

从 [Releases](https://github.com/sprd-linux-devs/release/releases) 获取与设备匹配的包，
先阅读包内说明并备份启动镜像及 `misc`。E5 使用 `boot_b` 启动 Linux，Android 保留在 slot A；
TF 安装覆盖所选第一分区或无分区整卡，不修改分区表。回退与持久启动策略因机型而异。

E5 默认 LAN 为 `192.168.9.1`。OpenWrt 通过 LuCI / SSH 管理，并提供信息屏、短信与电话应用；
Debian 提供 Phosh。账户和热点配置以设备或刷入包说明为准，使用前修改初始密码。
固件、Android 厂商组件、设备转储及每台设备的身份数据不进入源码仓库。

APN 管理在 LuCI 与信息屏中共用，支持按 SIM 保存选择及 PAP/CHAP。长短信片段会持久保存，收齐后才显示、提醒和转发。设备专用 TF 打包入口为 `openwrt/build-profile-tf.py --profile e5|t551m|m8`，须提供匹配内核和不含私有数据的基础根文件系统；详见 [安装包构建](docs/PROFILE-PACKAGES.zh-CN.md)。Android 安装器先备份并校验 B 槽启动链，再完成系统及 boot_b 的写入。Debian 包源码补丁统一由 `device/debian_device_common/patches/` 提供。

## 许可与来源

脚本、工具和文档使用 MIT，见 [LICENSE](LICENSE)。内核及导入的驱动按各文件的 GPL/SPDX 许可分发。
保留各子仓库的原作者说明、源文件许可和 M8 源码校验清单。
感谢 [mu300-linux](https://github.com/dikeckaan/mu300-linux) 及相关上游项目。
