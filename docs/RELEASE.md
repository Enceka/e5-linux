# 自动打包与发布

`.github/workflows/release.yml` 构建主线内核 OpenWrt 一键刷入包，并在校验通过后发布
GitHub Release。支持两种入口：

- Actions → **Build and publish OpenWrt** → **Run workflow**。可选择 OpenWrt 版本、
  内核/信息屏/插件的分支、tag 或 commit，默认发布；关闭 `publish` 只保存构建产物。
- 推送 `v*` tag。使用该 tag 对应的 e5-linux 提交，编译完成后发布同名 Release。

手动构建的 Release tag 为 `build-YYYYMMDD-HHMMSS-<commit>`。包名的时间戳、
`files/VERSION`、`build.json`、内核编译时间和 Release 说明都使用同一个构建开始时间，
时区固定为 **UTC+8**，与 runner 所在地区无关。根镜像的 `/etc/e5/build-time` 保存
同一时刻的 Unix 时间戳，供信息屏按设备时区显示。

## 首次配置

现有 boot 构建器保留 E5 原始 Android boot v4 的头、vbmeta 和 AVB 尾；OpenWrt
软件源也曾移除信息屏需要的 WPE 软件包。全新 runner 需要一次性准备这些输入，不能
依赖维护者电脑上的 `dumps/` 和 `work/`。在已能打包的本机执行：

```sh
python3 tools/ci-inputs.py create
```

输出 `out/e5-ci-inputs.tar.gz` 和 `.sha256`。输入仅包括：

- 从 boot 镜像裁剪出的头、vbmeta、尾模板；原 Android 内核和 ramdisk 被清空。
- misc 中通过 CRC 校验的 32 字节 bootloader_control，其他内容清空。
- 用于 initramfs 的静态 ARM64 BusyBox。
- 从已安装包清单提取的 `cog`、`libcogcore`、`libwpewebkit` 文件、链接和依赖。

不包含 Wi-Fi/蓝牙/音频固件、Android vendor 运行库、设备身份、SSH 密钥、用户配置或
本机 kernel 对象。BusyBox 与 WPE 软件包源码分别来自 BusyBox/Ubuntu 和 OpenWrt 的
对应软件包；发布 bootstrap 时应保留对应源码和许可来源。

将输入归档放在固定的 HTTPS 下载地址，例如本仓库 `build-inputs` Release 的 asset。
在 Settings → Secrets and variables → Actions → **Variables** 配置：

| 名称 | 内容 |
|---|---|
| `E5_CI_INPUTS_URL` | `e5-ci-inputs.tar.gz` 的 HTTPS 下载地址 |
| `E5_CI_INPUTS_SHA256` | 归档的 64 位 SHA-256；用生成的 `.sha256` 文件中的值 |
| `E5_KERNEL_REF`（可选） | tag 构建使用的内核 ref；默认 `e5-6.18` |
| `E5_INFOSCREEN_REF`（可选） | tag 构建使用的信息屏 ref；默认 `main` |
| `E5_PLUGINS_REF`（可选） | tag 构建使用的插件 ref；默认 `main` |

公开下载地址不需要额外 PAT。工作流通过自带 `GITHUB_TOKEN` 发布本仓库 Release，
只有发布 job 获得 `contents: write`。依赖更新时可指定准确 commit；实际解析到的四个
仓库提交都记录在 `build.json` 中。输入缺失、SHA 不匹配或归档越界会在编译前停止。

## 构建和发布内容

构建使用 GitHub 原生 `ubuntu-24.04-arm` runner，编译主线发行内核、打过补丁的
ModemManager/BlueZ 和通用 OpenWrt 镜像。主线镜像只装入本次内核的音频/WWAN 模块，
不要求再构建 5.15。补丁 APK 按 OpenWrt 版本和补丁内容缓存；首次构建耗时较长。
运行环境见 [GitHub runner 文档](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

每个 Release 提供：

- ZIP 和 TAR.GZ 一键刷入包。
- `SHA256SUMS`：两个刷入包的 SHA-256。
- `build.json`：UTC+8 时间、软件版本、源码提交和输入归档 SHA-256。

发布前核对源码文件、内核模块版本、包内哈希、启动镜像清单、ZIP CRC、两种归档的
逐文件一致性，并检查通用镜像中没有设备专属文件。文件先上传到 draft，全部上传成功
后才公开；已公开的 Release 不会被重跑覆盖。失败时保留诊断 artifact。CI 不连接 E5，
不会刷机或拨号；硬件验证仍在设备上进行。

当前工作流发布 OpenWrt。Debian 一键安装器仍使用独立构建的 Debian 镜像，其通用
发布准备不属于此工作流。
