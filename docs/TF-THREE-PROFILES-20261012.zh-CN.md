# E5 / T551M / VIPME M8 TF 安装包（2026-10-12）

> 2026-10-14 更新：下文 TF 预留空间/重建 GPT/双根更新描述为旧版流程。新版使用已有第一分区（无分区则整卡）的全部容量，更新统一走电脑安装器；见 [TF-SINGLE-ROOT-20261014.zh-CN.md](TF-SINGLE-ROOT-20261014.zh-CN.md)。

输出目录：`out/tf-releases/20261012/`。这是电脑通过 ADB 安装的 TF 包，不是 Magisk 首装模块。

| 机型 | ZIP 文件 | 大小 | 根文件系统模块数 |
| --- | --- | ---: | ---: |
| 荣悦 E5 | `e5-openwrt-25.12.5-tf-20261012-173903.zip` | 178,289,852 字节 | 158 |
| T551M | `t551m-openwrt-25.12.5-tf-20261012-173935.zip` | 178,327,253 字节 | 157 |
| VIPME M8 | `m8-openwrt-25.12.5-tf-20261012-174007.zip` | 177,969,906 字节 | 125 |

每个包旁有 `.sha256` 和构建来源 JSON，目录内 `VERIFIED.json` 记录最终 ZIP 哈希。
包内包含 `START-HERE.zh-CN.md`、双语说明、逐文件 `SHA256SUMS` 和 `BUILD.json`。

## 构建内容

- 以已清理的 OpenWrt 25.12.5 软件包根目录为基础，重新装配三个独立的 2 GiB ext4；
  不是从零重编全部 OpenWrt 软件包。
- 公共看板、屏幕、电话、通知音、事件驱动充电亮屏、CPU 控制等从当前源码重新 staging。
  ModemManager 使用已验证的 voice-r13 二进制，记录 SHA-256。
- 五个静态辅助程序重新编译：logdw、e5-vibrate、e5-ctl-raw、e5-modemd、e5-sim-probe。
- 安装修正版 block-mount，字符设备类型过滤防止扫描展锐通信端口；通过 APK 更新包数据库，
  保留原 fstab 服务的 START=11，不增加常驻轮询。
- E5 沿用已部署的 mobile4 内核及最新模块；M8 增量重编公共 Wi-Fi 修复；
  T551M 重新编译内核和模块，去掉强制 userdata 试启动的 `e5.openwrt=` 参数。
  打包器拒绝仍含该参数的内核，避免 TF 被跳过。
- 三个 initramfs 从公共 `boot/init` 重建，各带 45 个匹配的早期模块。
  M8 不使用带单台设备 CID 的 bring-up init。
- E5 / T551M 旧输出目录里的模块归档与最新散装模块存在差异；本轮重新生成归档，
  再核对内核版本、各模块 vermagic、归档/散装哈希和容器支持清单。
- 保留 Docker/KVM 内核支持，不预装 docker、dockerd、containerd 或 runc。
- 不含 Android 私有固件、NV、用户配置、联系人/短信记录或设备密钥。
  安装时提取目标机自己的固件和 Android 运行库。

## 安装和范围

解压对应机型的 ZIP，Windows 运行 `flash.cmd`，Linux/macOS 运行 `bash flash.sh`。
需要 Python 3.8+、ADB、已解锁且 root 的 Android A 槽，以及 Magisk BusyBox。
安装器在写入前检查 Android 型号；USB LAN 升级也检查设备 profile。

**首次安装会重新分区并清空整张 TF 卡**。至少 4 GB，建议 8 GB 或更大。
根分区约 2 GiB，其余空间保留；尚未改为“使用现有第一分区全部容量”的方案。
固件提取和上传在清卡前完成；Android 释放卡后，备份并同步有差异的 B 槽启动链。
根分区写入后卸载、只读重新挂载并校验，再写 boot_b、记录 SD 启动目标，最后切槽。
安装成功后由用户手动重启；安装器不自动重启。

首次管理地址 `192.168.9.1`，账号/密码 `root` / `root`，进入系统后修改。
TF 启动跳过 userdata F2FS 自动修复。

## 验证

- 三个 ext4 的 `e2fsck -fn` 均通过。
- 包内校验、ZIP CRC、ZIP 内逐文件 SHA-256、复制到 Windows 后整包 SHA-256 均通过。
- 从最终 boot 解出 initramfs，确认公共 init 完全一致，45 个早期模块与对应根目录逐个相同。
- 确认三个内核均无强制 userdata 试启动参数，M8 无单台 CID 启动限制。
- 三个根目录均包含修正版 block-mount、正确 fstab 启动链接、voice-r13 及相应硬件配置。
- 安装器失败路径/机型检查 13 项、启动链模拟 15 项、发布检查 11 项通过。
- **未对这三份最终完整 TF 包进行实机安装测试**；离线验证不等于实机首装通过。

## 后续重新打包

Linux/WSL 以 root 运行 `openwrt/build-profile-tf.py --help`，显式提供干净 base、
原始默认配置 tar、对应 kernel 输出、stock boot/header、misc 模板、BusyBox、
修正版 block-mount APK，以及新的 work/output 目录。
kernel 输出必须先通过 `upstream/check-container-support.py`；T551M 发布内核的
`CONFIG_CMDLINE` 必须去掉 `e5.openwrt=openwrt-t551m.ext4` 后重编 Image 和 modules。
输出记录构建时源码哈希，包括尚未提交的修改，不仅依赖 HEAD。
