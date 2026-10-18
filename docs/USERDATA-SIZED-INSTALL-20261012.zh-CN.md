# 可选容量的 userdata 镜像安装（2026-10-12）

> 已退役（2026-10-12 晚）：刷机包不再包含 `install-userdata.cmd` /
> `install-userdata.sh` 与 `userdata-image.sh`（flash.py 内的实现保留）。
> 替代方案见 [INTERNAL-PARTITION-SYSTEM-20261012.zh-CN.md](INTERNAL-PARTITION-SYSTEM-20261012.zh-CN.md)——
> 在 eMMC 真分区上启动，userdata 不再被 mainline 读写。本文档保留为故障史与教训记录。

TF 安装出现 `expected one SD card, found 0` 表示没有找到外置卡；可以用本次新增的
`install-userdata.cmd` / `install-userdata.sh` 安装到内置存储的普通镜像文件。
三机型共用实现，安装器仍检查对应型号、Android A 槽、root、解锁状态及启动链。

## 使用

Windows 双击 `install-userdata.cmd`；Linux/macOS 执行 `bash install-userdata.sh`。
也可运行 `flash.cmd --data` / `bash flash.sh --data`。
脚本显示 `/data` 剩余容量、可选镜像范围，随后输入 GiB 数值，例如 `4`、`6.5`。
指定参数：`install-userdata.cmd --image-size 4`。
`-y` 模式没有明确指定大小时选最小镜像；不会自动占满剩余空间。

最小值为原始根镜像容量（现有包 2 GiB）。按 MiB 向上对齐，最大值扣除：

- 至少 1 GiB Android 可用空间；
- 上传的压缩根镜像、boot 镜像；
- 512 MiB 固件、转换工具、临时文件预算。

上传和固件提取后再次读取可用容量；现有镜像不作为“将会删除”的可回收容量。
因此旧系统和新系统同时存在时，也要有足够空间。

## 写入流程

1. 检查状态和容量；拒绝存在待提交 `.new`、残留 `.part` 或不安全符号链接的路径。
2. 提取本机固件到临时文件，上传根镜像、boot、ext4 工具包。
3. 在 `/data/e5linux/openwrt.ext4.part` 解压新镜像；实际写零分配扩展空间，避免稀疏文件
   表面很大而真实剩余容量不足；运行 e2fsck、resize2fs、只读 e2fsck。
4. 只读 loop 挂载新镜像并检查关键程序可读/可执行；真实卸载完成才继续。
5. 备份同步差异 B 槽启动链，再提交新镜像。已有镜像及配套固件/安装配置保留到
   `/data/e5linux/previous.<时间>.<进程号>/`。
6. 写入并回读检查 boot_b，记录 userdata 启动目标，最后修改 misc 启动控制块。
   成功后由用户手动重启。

不格式化 userdata，不对 userdata 块设备执行 ext4 fsck/resize；工具只操作新建镜像文件。
首次安装使用新的 OpenWrt 默认配置；旧镜像作为备份保留，不是保留设置的升级。
进程可捕获的失败会卸载检查挂载并清理新镜像；断电或强制杀进程可能留下 `.part`，
下次会拒绝覆盖，需要先检查残留。

## 工具和构建

`openwrt/prepare-ext4-tools.py` 从目标 ARM64/musl 根目录取 e2fsck、resize2fs 及 ELF
依赖，生成 `files/ext4-tools.tar` 和内部 SHA256SUMS；不依赖原厂 Android resize2fs 版本。
在隔离工具 chroot 内执行，绑定临时镜像目录及只读查询所需的 proc/dev，完成后卸载。
工具本身不添加常驻进程或轮询。

本次重新打包三机型电脑安装包，保留上一批已验证的 kernel/root 镜像，仅更新安装器、
工具和说明；旧 TF ZIP 不原地修改。输出在 `out/userdata-releases/20261012/`，每包支持
TF 默认安装和独立 userdata 入口，并带包内校验、整包 SHA256 和 `VERIFIED.json`。

## 验证

- 容量选择、非法数值/超出范围、空间不足、大容量参数、扩容失败不得同步启动链/写 boot：5 项测试。
- 安装器既有失败路径和机型检查：13 项测试；发布验证：11 项测试。
- 实际 ARM64 ext4 工具在隔离环境中将 64 MiB ext4 扩到 256 MiB，前后 fsck 通过。
- 完整 userdata-image.sh 使用 T551M 的实际 2 GiB 发布根镜像扩到 3 GiB，完成工具哈希检查、
  实际分配、扩容、fsck、只读挂载和关键程序检查；卸载后主机 fsck 通过。
- 本次未在用户实机执行 userdata 安装或改变启动选择；Android SELinux/挂载策略等实机
  条件仍需首装验证。

## 10 GiB 扩容失败修复

用户实际选择 10 GiB 后，resize2fs 仍显示 524288 个 4 KiB 块（2 GiB）。
在已连接的 Android 上执行只读 shell 对照，确认 `[ 10737418240 -gt 2147483648 ]`
返回假，而 `[ 10240 -gt 2048 ]` 返回真：Android mksh 的数值比较在字节数超过
32 位范围后溢出，导致扩容分支被跳过。日志里的 SELinux 拒绝带 `permissive=1`，
不是这次容量校验失败的原因。此失败发生在启动链同步、镜像提交及 boot/misc 写入之前。

修复后由电脑端用 Python 校验 MiB 对齐并传入 MiB 数值；Android 的比较、seek 和
count 全部只处理 MiB，字节数只用于文件大小字符串校验。分配完成立即检查长度，
再明确指定 resize2fs 的目标 MiB 容量，避免不足容量进入后续安装阶段。
这一修复为 E5、T551M、M8 共用，不改变内核和根文件系统内容。

隔离环境使用 mksh 运行完整安装阶段、实际 ARM64 ext4 工具和 T551M 发布根镜像，
从 2 GiB 实际分配并扩到 10 GiB：文件长度为 10737418240，文件系统为 2621440 个
4 KiB 块，fsck、只读挂载、关键程序检查和卸载后的主机 fsck 全部通过。
这次仅在实机执行只读 shell 对照，没有替用户格式化、安装或切换启动槽位。
打包时 D 盘剩余空间不足，修正版三机型安装包统一放在
`C:\Users\kano\Downloads\e5-linux-userdata-20261012-size-fix\`，旧包保持不变。
M8 首次导出遇到宿主盘空间不足及 WSL 连接超时，后续直接在 Windows 下以已校验
的上一版 M8 包更新公共安装器并重新打包，内核、根镜像和 ext4 工具保持一致；
包内 SHA256、ZIP CRC 和整包 SHA256 均已完成校验。

## 实机首装写入风暴与修复（2026-10-12 晚）

mksh 修复后的实机首装（T551M，10 GiB）：容量校验通过、扩容真正执行后，
旧实现以 dd 实写 8192 MiB 零并 fsync，约 187 秒时设备重启、adb 断开
（`device returned no completion status`）。隔离验证在 PC 上通过，实机差异是
10 GiB 写入风暴的页缓存与回写压力（Android 看门狗），与容量计算无关。

改为 `fallocate -l` 预留真实块（不经过页缓存）；新增的块数校验按 MiB 比较
（`stat -c %b` / 2048，避免再次触碰 mksh 的 32 位字节比较），`fallocate`
不可用时回退零填充。回读 e2fsck 不读取空闲数据块，新区域内容与校验无关。

失败或断电会留下 `/data/e5linux/openwrt.ext4.part`（脚本自身退出会清理，
设备重启则不会），脚本拒绝覆盖，重试前需人工删除；`/data/local/tmp` 下的
上传包可一并清理。修复后的实机结果待验证。

## 各机型默认热点名称

安装器以前将 `--ssid` 默认值写成 `E5-OpenWrt`，虽然机型校验读取了包内
`device-profile.json`，热点提示却没有使用该信息。现改为按安装包机型生成
`E5-OpenWrt`、`T551M-OpenWrt`、`M8-OpenWrt`，TF 和 userdata 两种首装入口共用。
用户显式传入 `--ssid` 或在提示处输入名称仍优先使用；升级不会覆盖已有热点名称。
三机型安装包都重新打包并更新校验清单。机型默认值及无 profile 的旧 E5 包回退
测试通过；这只更新安装器，不需要重刷已安装系统以修改现有 SSID。
