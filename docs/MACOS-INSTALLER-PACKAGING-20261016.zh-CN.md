# Windows 与 Apple Silicon 安装器完整打包

两个仓库的正式桌面安装包同时提供：

- 根目录 `OpenWrt-Installer.exe`：Windows x64 图形安装器。
- 根目录 `OpenWrt-Installer.app`：Apple Silicon macOS 图形安装器。
- `tools/macos/adb` 和 `tools/macos/backend/`：Mac 所需的 ADB 与私有后端。
- 根目录 `START-HERE.md`：安装、续装、更新和切换系统的说明。

EXE 和 APP 共用原有的一份系统载荷，不重复放置 rootfs。Mac 无需另外安装 Python、
Node 或 Rust。Intel Mac 不在原生 APP 的支持范围内。

## 防止漏装与旧版本混入

`installer/package_gui.py` 在复制前校验两端的源码指纹、平台、完整文件列表和 SHA-256。
本地默认读取 `installer/artifacts/windows` 与 `installer/artifacts/macos-arm64`，也可分别通过
`OPENWRT_GUI_ARTIFACT`、`OPENWRT_GUI_MACOS_ARTIFACT` 指定目录。缺少 Mac 产物会停止正式
打包，不再生成只有 Windows 安装器的包。`OPENWRT_GUI_OPTIONAL=1` 仅供源码测试夹具使用。

## ZIP 执行权限

旧 MU300 ZIP 虽带有 APP，但 Windows 重打包会丢失 POSIX 执行权限。
`installer/archive_tools.py` 统一写入 Unix 文件属性，保留 APP、Mac 后端、ADB、Mach-O
运行库和命令行启动脚本的执行权限。E5 的 profile/主发布入口、两仓库的安装器更新打包、
MU300 的 TF 混合包构建均使用这一归档函数。

MU300 旧包刷新时也更新 `.sh` 启动器，使 Apple Silicon 使用随包后端。
实际归档回归覆盖 Windows 式文件权限、内容不变及单份系统载荷；原生 Mac CI 检查 ARM64
架构、ad-hoc 签名，以及真实冻结后端与 ADB 启动。上述检查不会写入连接的设备。
