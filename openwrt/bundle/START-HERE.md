# 使用指南：@MODEL@ OpenWrt 安装与维护

**先读这一份。** 本包只适用于 **@MODEL@**（配置名 `@PROFILE@`），不能跨机型刷入。
同一个 ZIP 提供两种入口：在 Android 的 Magisk 中直接部署到 TF 卡，
或者解压到电脑，通过安装器选择 TF、内置独立分区、userdata 镜像和更新。

> 在 Magisk 里安装本 ZIP，就表示同意清空 TF 第一分区（无分区表时整卡）并部署 OpenWrt。
> 不想动 TF 卡、想先了解步骤或选择其他安装方式，请先在电脑解压并运行安装器。
> 本 ZIP 不是仅用于“切回 Linux”的小型 Magisk 模块。

## 1. 包内文件怎么找

```text
OpenWrt-Installer.exe       Windows 主入口（包含此文件时无需安装 Python）
OpenWrt-Installer.py        电脑 Python 入口，Windows / Linux / macOS 共用
START-HERE.md              本使用指南
module.prop                Magisk 必需的模块信息
customize.sh               Magisk 必需的安装入口，请勿手动执行
skip_mount                 禁止作为 Android 文件覆盖模块运行
launchers/                 按用途命名的快捷脚本
files/                     一份系统镜像、内核、校验清单及设备侧脚本
scripts/                   安装器的辅助代码与固件转换工具
docs/                      补充说明、许可证
extras/                    可选附件，若本构建包含
tools/                     可选的 ADB 工具，若本构建包含
backups/                   电脑安装时自动生成的备份、续装记录和 SSH 主机记录
```

**不要只复制 EXE 或 PY。** 必须保留整套目录。可以把整个文件夹搬到其他位置，
但续装时仍需指定原来的 `transaction.json`，并保留它旁边的备份文件。
文件名均采用英文，避免不同系统的终端、压缩软件和脚本处理中文文件名时出问题。

固件 ZIP 顶层直接含 `module.prop` 和 `customize.sh`，适合 Magisk 读取；
在电脑上建议使用“解压到同名文件夹”，避免散落到下载目录。
若另外提供 TAR.GZ，它供电脑解压使用，不能当作 Magisk 模块安装。

## 2. 开始之前

1. 确认包与机型一致，Android 已解锁 bootloader，并能正常使用 root。
2. 当前流程要求 **Android 在 A 槽、OpenWrt 在 B 槽**。不要自行对调文件名绕过检查。
3. 安装前自行备份重要文件。TF 方式会清空整卡；内置缩容方式可能清空 Android，见下文。
4. 不要同时启动两个安装器，也不要同时进行 Android OTA、分区操作或另一项刷机。
5. 使用可靠的 USB 线和稳定供电，安装期间不要拔线、拔卡、强制关机。
6. 固件不预置其他设备的私有固件、MAC、NV 或校准数据；安装时提取目标机自己的文件。
7. 若有发布方提供的 ZIP SHA-256，先校验下载包；包内 `files/SHA256SUMS` 用于检测解压后的文件损坏。

本包保留 Docker/KVM 的内核支持，不预装 Docker。用户以后可自行安装相应软件包。

电脑安装入口可使用 Magisk、KernelSU 或 KSUNext 的 `su` 授权。请给 Android 的 **Shell** root 权限；
电脑和 ZIP 模块入口统一使用 `files/busybox` 中随包携带的静态 ARM64 安装工具，不依赖管理器的 BusyBox 或安装路径。
重置 Android 后，需重新恢复相应管理器及 Shell 授权。不同管理器、不同机型的原生模块安装仍需实刷验证；
这不代表给 OpenWrt 内核增加 KSU，也不需要在 OpenWrt 中安装 Android root 管理器。

## 3. 选哪一种方式

先运行根目录的 **`OpenWrt-Installer.exe`**，或在解压目录运行：

```sh
python3 OpenWrt-Installer.py
```

EXE 和 PY 提供同一套菜单；通常不需要进入 `launchers/`，更不要手动运行 `files/`、`scripts/` 内部脚本。

| 菜单 | 什么时候选 | 会清除什么 |
| --- | --- | --- |
| 1 — TF 卡首次安装 | 有可清空的 TF 卡 | 清空第一分区；无分区时清空整卡 |
| 2 — 缩容 userdata 安装 | 不用 TF，安装独立内置系统 | 缩容 userdata；加密 data 必须重置 Android |
| 3 — 覆盖重装已有内置系统 | 重装原 OpenWrt 分区 | 原 OpenWrt 系统及配置，不重新缩容 Android |
| 4 — 继续加密 data 的两阶段安装 | 缩容重置 Android 后续装 | 写入已准备的 OpenWrt 分区，不重复缩容 |
| 5 — 从 Android 临时启动 OpenWrt | 系统已经安装，只想切回 | 仅修改 misc，检查后切槽并重启，不更改默认启动设置 |
| 6 — 更新 OpenWrt | 设备运行 OpenWrt，更新并保留设置 | 替换系统与内核，先备份重要文件 |
| 7 — userdata 镜像安装【实验性】 | 在未加密 userdata 内创建镜像 | 占用所选容量，保留旧镜像备份；可能损坏 Android F2FS |
| 0 — 退出 | 取消操作 | 不执行安装 |

**菜单 7 是实验性功能：userdata 镜像模式可能破坏 Android 的 F2FS 文件系统。**
通常选择 TF 或独立内置分区；即使 userdata 未加密，也不能把镜像方式视为同等可靠。
Experimental: userdata-image installation may damage Android's F2FS filesystem.

`launchers/` 只是可选的快捷入口，不是另一套安装流程。下面均以根目录主安装器为准。

## 4. 在 Magisk 内部署 TF 卡

### 准备

- 插入可清空的 TF 卡：所选目标至少容纳包内根镜像，建议 **4 GB 或以上**。不预留 OTA 分区。
- 把完整固件 ZIP 放在手机内部存储，不要依赖将被清空的 TF 卡保存唯一一份包或备份。
- Android 内部空间需容纳临时展开的系统镜像、启动备份和本机固件：通常至少约 2.5 GiB，建议 3 GiB 以上。
  脚本按包内实际大小检查，空间不足会在清卡前停止。
- 安装工具使用随包携带的静态 BusyBox；仍需要 Android 提供正常的 root 授权。
  Android 用户空间为 32 位不等于内核不是 ARM64，安装器按内核和实际执行能力检查。

### 操作

1. 打开 Magisk → 模块 → 从本地安装，选择**完整固件 ZIP**。
2. 仔细阅读“清空所选 TF 目标”的提示。选错包或不想清卡时立即取消，不要进入刷写阶段。
3. 等待型号、包校验、容量、boot、两槽启动链和固件检查。
4. 脚本先在 Android 的临时镜像内运行固件转换，提取这台机器的 Wi-Fi、蓝牙、音频和基带运行文件。
   这一阶段不格式化 TF，也不格式化 userdata。
5. 自动尝试导入 Android 热点名称和密码；配置不兼容时改用本机型默认热点名和随机密码。
   **安装输出会显示最终热点和密码，请记下来。** APN 默认按 SIM 自动选择，可进系统后修改。
6. Android 释放 TF 卡；仍有挂载时停止，不强行格式化。
7. 备份、同步有差异的 B 槽 `uboot/sml/teecfg/trustos/vbmeta` 并回读校验。
8. 优先使用已有第一分区，无任何分区时才使用整卡；写入根镜像、离线扩容到目标全部容量，导入固件并只读复验。不修改分区表。
9. 根文件系统通过检查后，才写 `boot_b` 并校验；最后根据本机 misc 生成并写入 32 字节启动控制信息。
10. 出现 **`E5-TF-INSTALL-OK`** 和 Magisk 的成功提示后，手动重启进入 OpenWrt。

TF 容量使用方式与 MU300 对齐：使用所选第一分区或无分区整卡的全部容量，不创建第二根分区，不保留 OTA 空间。
如果现有第一分区只有 2 GiB，安装器不会越界扩到后面的空闲空间；要用满整卡，请先备份并自行准备占满卡的第一分区。
第一分区不存在但其他分区存在时拒绝安装，避免把有分区的卡误当整卡覆盖。

安装期间每 10 秒输出阶段和耗时，整项部署设有 30 分钟上限。错误后停止后续步骤，不自动重试写盘。
日志、阶段状态及启动备份保存在 Android `/data/adb/e5-tf-install/run.*`；
启动链备份另在 `/data/adb/e5-bootchain/`。
失败后不要反复点安装：先保存 Magisk 安装输出和这些文件，检查故障，必要时重启 Android 后再尝试。

成功后的部署模块没有启动服务和系统覆盖，自动禁用，可在 Magisk 中删除。
删除模块**不会删除 TF 上的 OpenWrt，也不会恢复 boot_b**。

## 5. 用电脑安装

### 电脑准备

- Windows 优先双击 `OpenWrt-Installer.exe`，不需要另装 Python。
- 不含 EXE，或在 Linux/macOS：需要 Python 3.8+。首次安装需要 ADB；更新需要 Python 的 Paramiko。
- 安装 Android platform-tools，将 `adb` 加入 PATH；也可放入 `tools/` 或旧的 `platform-tools/` 目录。
- Android 开启 USB 调试、授权当前电脑，在 root 提示中允许 Shell。
- **只连接一台待刷设备。** 当前 E5 安装器要求唯一在线 ADB 设备，不自动猜测目标。
- 程序不会主动更改电脑的网卡、网络优先级或防火墙配置。

先查看帮助或只校验解压文件（不访问设备）：

```powershell
.\OpenWrt-Installer.exe --help
.\OpenWrt-Installer.exe --verify-package
```

```sh
python3 OpenWrt-Installer.py --help
python3 OpenWrt-Installer.py --verify-package
```

`--check` 是另一项操作：它会连接 Android、检查启动链和固件，并产生/清理临时文件，
不写分区；不要把它和纯离线 `--verify-package` 混淆。

### TF 首次安装

打开根目录 EXE／PY，选 **1**；命令行也可运行 `OpenWrt-Installer.exe --tf` 或 `python3 OpenWrt-Installer.py --tf`。

按提示设置 APN、热点名和密码，确认清卡。提取与上传本机固件通过后才释放卡、写入所选目标。
与 Magisk 入口一样，只清空所选目标并使用其全部容量，不重建分区表，也不预留 TF 更新空间。目标内的原文件不会保留；其他分区不写入。
结束后看到成功提示再手动重启。

### 内置独立分区：未加密 data

打开根目录 EXE／PY，选 **2**，选择分区大小。
“完全使用空间”默认 **yes**，直接回车即可扩满所选分区；初始镜像约 2 GiB 不是最终容量。
例如分配并使用完整 10 GiB：

```powershell
.\OpenWrt-Installer.exe --part --part-size 10
```

只有明确选择 no，或传入 `--no-grow-fs`，才保留初始镜像的文件系统容量。
保数据流程会离线缩小 userdata、创建 `e5root` 并写入系统。
**第一次开机正在执行缩容安装，通常需要数分钟，数据多或闪存慢时可能更久。**
屏幕显示阶段与耗时；不要因暂时没有桌面或百分比就强制重启，保持供电。
**缩容安装完成后会自动重启一次，再进入 OpenWrt。**
该流程涉及分区表和文件系统修改，重要数据仍应提前备份。
E5 安装器当前按 userdata 缩容规划，不承诺支持 MU300 安装器的 GPT 空洞优先分配流程。

### FBE / FDE / metadata 加密 data：两阶段

加密 data 不能由 initramfs 直接解密，不能走保数据缩容。脚本会要求明确同意清空 userdata：

1. 电脑保存设备身份、分区计划、原 boot、GPT 和 misc 等备份。
2. 刷入准备启动镜像并重启，在未挂载 data 的环境下调整分区；首次离线缩容通常需数分钟，期间不要断电。
3. 缩容完成后自动重启进入原厂 recovery，由原厂清空 userdata 并初始化加密；必要时在机器上确认恢复出厂，期间可能另外重启。
4. 回到全新 Android，完成初始设置、打开 USB 调试、重新授权电脑并恢复 root/Shell 授权。
5. 原安装器可继续等待；也可重新打开根目录 EXE／PY，选 **4** 并提供原 `transaction.json`。
6. 核验设备身份、分区边界、准备标记和系统载荷后，写入已准备的独立分区，最后写 boot、切槽。

```powershell
.\OpenWrt-Installer.exe --resume-part "backups\part-日期-标识\transaction.json"
```

**不要为了续装再次运行首次缩容。** 记录是电脑上的文件，恢复出厂不会替你保留电脑文件：
必须保存整个 `backups/part-*` 目录。记录丢失时不要伪造 token 或跳过校验，先恢复备份/寻求诊断。
修补版安装器可使用相同 boot 和根镜像续装；换了系统载荷仍会拒绝，避免跨包写错。
`-y` 不代表允许新检测出的 Android 数据清空；无人值守重置还需显式 `--format-userdata`。

### userdata 镜像文件

**实验性：可能破坏 Android F2FS。** 打开根目录 EXE／PY，选 **7**，或使用下面的 `--data` 参数。
仅适用于 OpenWrt 启动时可直接读取的**未加密 userdata**。
程序按当前空闲空间给出范围，可以输入例如 `4`、`6.5`、`10` GiB：

```powershell
.\OpenWrt-Installer.exe --data --image-size 6.5
```

镜像位于 `/data/e5linux/openwrt.ext4`。不格式化 userdata，但会占用所选容量，
已有镜像作为备份保留，计算空间时不能把它当作可立即回收的空间。
创建、扩容和检查大镜像需要时间，尤其是较慢的 eMMC；等待明确成功/失败状态。

## 6. 首次启动、登录与系统切换

- 首次启动会初始化配置，通常比后续启动慢。插好 TF 并等到界面和网络起来。
- 管理页面：`http://192.168.9.1`，默认账号 `root`、密码 `root`；进入后尽快修改密码。
- SSH：`ssh root@192.168.9.1`。
- 用安装输出里的热点名称/密码连接，或通过 USB 网络访问。电脑端网卡被禁用时需用户自行启用。
- APN、上网 SIM、热点等可进网页或屏幕设置；流量与短信等在公共服务中同步。
- 回 Android：使用屏幕的系统切换，或 SSH 执行 `e5-next-boot android && reboot`。
- Android 切回已装 OpenWrt：电脑打开根目录 EXE／PY，选 **5**，核验后会重启。
  只校验 B 槽启动镜像和启动链，再修改 misc 的 32 字节启动控制块并回读。
  不挂载或修复 OpenWrt 文件系统，不改启动选择文件、默认启动设置，也不自动同步启动链。
  进入 OpenWrt 后沿用原有默认启动策略；需要永久默认启动时在 OpenWrt 网页／屏幕中设置。
  也可另装独立的 `e5-linux-switch` 小模块，通过其“操作”按钮切回。
  Android APK：本包 `extras/android/op-system-switcher.apk`，应用名为 **op系统切换器**，
  在 Android 中安装并授予 root 后即可选择系统。新版仅修改 misc，不挂载 OpenWrt 根分区，
  不更改默认启动设置。可以覆盖同签名旧版应用；详情见 `docs/ANDROID-SWITCHER.md`。
- 不要把完整固件 ZIP 反复装入 Magisk来切系统，那会重新部署并清空所选 TF 目标。
- 试启动失败会回退 Android；回退不等于安装成功，应保存启动日志后排查。

## 7. 更新与重装的区别

**更新**：设备正在运行 OpenWrt，电脑能访问其 USB 网络时打开根目录 EXE／PY，选 **6**。
安装器通过 SSH 主动上传，同一机型包才允许更新；保留设置，更新根与内核。TF 更新也统一使用这个电脑入口：重启进入 initramfs，将载荷校验并复制到内存，卸载根后更新原分区，扩回原容量并恢复配置和本机固件。
不新建分区，不修改 GPT，不占用额外 OTA 空间。自行安装的软件包及未列入配置备份的其他文件不迁移，重要资料请自行备份。
单根系统没有另一份 TF 根分区可自动回退，写入期间须保持供电。旧版多根卡仍能启动，更新只改当前根；不会自动合并旧分区。
它不是 Android OTA，也不是 LuCI 的通用 sysupgrade 固件；不要把本 ZIP 直接交给 sysupgrade。

**重装独立分区**：设备运行 Android 时打开电脑根目录 EXE／PY，选 **3**，
只覆盖已有 `e5root` 与 boot_b，不重新缩容或重建 userdata；OpenWrt 原系统及配置会被替换。
这是覆盖重装，不是保留设置升级。

更新前备份重要配置。不要在保存/更新期间断电，也不要手动删回退镜像或改 GPT。
成功提示会说明是否需要手动重启；更新入口通常会自动重启应用，首次安装不会。

## 8. 常见报错与处理

| 提示 / 现象 | 处理 |
| --- | --- |
| Wrong device / model mismatch | 换正确机型包，不能改校验文件绕过 |
| 找不到 TF 卡 | 确认设备有卡槽、卡插好且能被 Android 识别；不想用 TF 就选内置安装 |
| TF 仍然挂载 | 在 Android 存储设置卸载该卡，保留卡在槽内；不要强拆正在使用的卷 |
| Android 不在 A 槽 | 先弄清当前 OTA/槽位状态，本包不支持强行反向安装 |
| userdata 已加密 | 选独立分区并明确同意两阶段恢复出厂，不能用 userdata 文件镜像 |
| boot-chain / CRC / OTA 检查失败 | 停止刷入，完成/排除 Android OTA 状态；保留完整报错 |
| 大镜像创建慢或离线缩容数分钟 | 看阶段和耗时；不要强制重启，若明确失败则保存日志 |
| 续装记录不匹配 | 使用原记录和相同关键载荷，核对是否接错机器；不要删记录重跑缩容 |
| Windows 窗口关闭太快 | 新版 EXE 会显示最终状态并等待 Enter；CMD 入口也会保留窗口 |
| EXE 与源码不一致 / stale | 发布者需要重新构建 EXE；用户不要自行替换单个程序后跳过包校验 |
| 进了 OpenWrt 但管理页打不开 | 检查 USB 网卡是否启用、地址与 SSH；不要先假定需要重刷分区 |

出现失败请保留：完整安装输出、包的版本与校验值、电脑 `backups/`、
Magisk 原生部署的 `/data/adb/e5-tf-install/` 和启动链备份。
这些目录可能含热点密码、设备身份与系统镜像，不要直接公开上传。

## 9. 验证范围与构建者说明

具体版本与内核、来源信息见 `files/VERSION`、`files/BUILD.json`（若包含）和 `files/boot.json`。
离线测试和文件校验通过，不等于每台机器的原厂 recovery、TF 卡和 Magisk 环境都已经实刷验证。
新版原生 Magisk 首次部署流程需要分别完成 E5、T551M、M8 的实机验证后，才能宣称三款均已验证。

构建者修改 `flash.py` 后，必须先在 Windows 运行 `python tools/build-flash-exe.py`，
更新 EXE 和指纹，再用公共打包脚本生成新包；旧 EXE 会被拒绝。
原生部署还需要从仓库源码静态编译的 ARM64 `e5-bootctl`，两个打包入口都已接入此步骤。
现有已发布压缩包不会因为仓库修改自动变成新格式，应重新完整构建与核验。
