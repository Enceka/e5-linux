# eMMC 内部分区系统（2026-10-12）

给 userdata 缩容，在腾出的空档里建一个真 ext4 分区跑 OpenWrt。动机是
docs/FINDINGS.md 48：mainline 会在电源循环后损坏厂商 F2FS，SD 卡系统因此让
userdata 保持只读，而 userdata 镜像系统必须把它挂读写。真分区系统是卡系统
的原理放进 eMMC——启动时 userdata 完全不挂载，mainline 永远不碰那个 F2FS。

## 组成

**e5-gpt 新增 `resize`**（`openwrt/overlay/usr/libexec/e5-gpt`）：按名字改动
一个既有分区的结束位置（缩容，或向空档扩容），重叠、越界、重名一律拒绝；
两条 GPT 副本沿用 backup-先-再-primary 的重写次序。`plan` 新增
`resize:NAME:SECTORS` 只读模拟——同一个 plan 里先缩容再加分区，就是安装器
会执行的序列。测试 `openwrt/tests/gpt-plan.py` 10 项：既有 6 项不变，另加
计划内缩容+新增、错误路径（未知分区）、真实缩容后二次 resize（强制校验双份
GPT 一致）、缩容后真实新增加分区、扩容重叠拒绝。

**boot/init 内部分区系统**：`part_root()` 只在系统盘（含 misc 的 eMMC）上找
`PARTNAME=e5root` 且带 `/etc/e5/part-root` 标记和可执行 `sbin/init` 的分区；
`e5linux/boot-os` = `part` 时选用（注册过的 SD 卡仍优先，与既有规则一致）。
`part-trial` 语义与卡的 `sd-trial` 相同：首启写入 0，运行系统起来后由
两个 `e5-boot-ok`（OpenWrt/Debian 版）删除；启动夭折则下次跳过它、回退到
卡或镜像。`/run/e5linux/init-features` 增加 `part-root` 令牌供安装器探测，
`on_part` 与 `on_card` 同权（自带固件，跳过设备文件解包）。分区系统就绪时
后续的卡/镜像分支整体短路（含跳过 sd_wait）。测试
`openwrt/tests/part-root-boot.py` 5 项（函数抽取 + 桩 mount 运行）。

**`openwrt/device-install-part.sh`**：默认 dry-run——打印尺寸、`e5-gpt plan`
只读模拟结果，以及 `--commit` 将执行的每一步；`--commit` 依次执行：

1. 卸载 userdata（必须先只读挂载过，用于检查剩余空间）；
2. `fsck.f2fs -f` userdata（缩容前置条件，脏文件系统拒绝继续）；
3. `resize.f2fs -s -t <目标扇区>`，随后读原始 superblock 校验 magic 与
   4 KiB 块计数（不信任工具的输出）；
4. `e5-gpt resize userdata` + `add e5root`；
5. 新分区内容经**整盘偏移写入**（内核不重读分区表，节点下次启动才出现）；
6. `losetup -o` 挂载新分区，保留运行系统配置（keep_config）与设备固件
   （device_files_tar，各自从 device-install-image.sh 照搬并有标记段）；
7. 标记 `/etc/e5/part-root` 与 `/etc/e5/part-trial`（首启为试启动）；
8. 短暂读写挂载 userdata 一次写入 `boot-os=part`（与 boot/init 处理单次
   选择的做法相同）。

## 使用（在 TF 卡系统里）

```sh
apk add f2fs-tools
sh device-install-part.sh openwrt.ext4.gz              # dry-run，先看计划
sh device-install-part.sh openwrt.ext4.gz --commit     # 执行；然后重启
```

回退：删掉 userdata 上的 `e5linux/boot-os`（或重新装别的系统）；试启动失败
会自动回退。Android 侧只是 userdata 变小，其余无感。

## 无卡首装（install-part，2026-10-13）

`install-part.cmd` / `bash install-part.sh`（即 `flash.py --part`）在 Android 侧只做三件事：
按所选大小落位载荷（镜像、device-files、`part-install.conf`/`.settings`）、写 boot_b、
记 `boot-os=part` 并武装 slot b。下一次启动由引导镜像里的 `boot/install-part.sh` 完成全部
重活，顺序保证任何一步失败都不影响 Android 可启动：

1. 读 conf（此时 userdata 还没缩，可正常只读挂载）；
2. 以 raw 工具 fsck + `resize.f2fs -s -t` 缩容（**f2fs 先小**：此后即使 GPT 步骤失败，
   Android 只会把文件系统扩回原分区）；
3. `e5-gpt` 缩 userdata 分区、加 `e5root` 分区；
4. 镜像经整盘偏移写入新分区，`losetup` 挂载、拷 device-files、写 `part-root`/`part-trial` 标记；
5. 清载荷（全程唯一一次 Linux 侧对厂商 F2FS 的写：几个 unlink）；
6. **重填 B 槽试启动（tries=2）后自动重启一次进入新系统**——两个必须同时成立的机制：本轮内核的
   分区表看不到刚建的分区（无法在同一次启动里选择它），且 LK 每次启动 B 槽递减 tries、"未成功且
   只剩 1 次"会立即回滚 Android；安装启动消耗的那次必须在重启前补齐，系统起来后由 e5-boot-ok
   继续续期。首启为试启动，起不来下次回退。

**M8 实机踩中的坑（2026-10-13）**：安装（缩容/建区/写入）全部成功，却每次都回落到 Android——
上一版只加了"装完自动重启"，没补 tries（安装启动 2→1，重启后 LK 见 tries=1 直接回滚），于是
形成"装好了永远进不去"的循环。修复即第 6 步里的 `write_misc_bc … part-install-rearm`；
测试里加了 rearm 必须出现在 reboot 之前的守卫。已装好的设备重跑一次 install-part 即可进入
（已完成的分区步骤会快速跳过）。

工具以**标准路径**暂存进 initramfs（`/sbin/*.f2fs`、`/usr/bin/ucode`、`/usr/lib/ucode/fs.so`、
`/usr/sbin/resize2fs`、`/lib/*`）：ucode 的模块路径是编译期固定的，`prepare-f2fs-tools.py`
的工具包因此含 14 件（resize.f2fs——fsck.f2fs 的 argv[0] 分身；ucode + libucode + libjson-c +
fs 模块；resize2fs + libe2p/libext2fs/libcom_err，供"完全使用空间"）。
initramfs 的 PATH 已补 `/usr/bin:/usr/sbin`，脚本里 ucode 仍以绝对路径调用。

**"完全使用空间"**：install-part 在计划确认前多问一句"是否把根文件系统扩满所选分区"——
默认否（按镜像约 2 GiB 分配，余量保留；与卡更新器的行为一致），选"是"则写入后由
initramfs 里的 resize2fs 在线扩到分区的精确 4 KiB 块数（loop 设备无 sizelimit，直接
resize 会越过分区进入备份 GPT，所以给绝对值）；`--grow-fs` 为非交互等价开关。已存在的
系统可随时手动 `resize2fs /dev/mmcblk0p71` 补上。

**首装实机首跑的两个缺陷（2026-10-13，均已修）**：① initramfs 的 PATH 只有 `/bin:/sbin`，
脚本里裸调 `ucode` 报 not found，且被 `list | awk` 管道吞掉、直到下一步才显形；② 工具包漏了
`libjson-c.so.5`（ucode 与 libucode 的依赖），ucode 在设备上根本起不来。修复：绝对路径调用、
`list` 输出单独检查、PATH 补齐、工具包加 libjson-c。首跑中 f2fs 缩容已成功、GPT 步骤失败并安全
回退 Android（f2fs 小于分区 = Android 可自行扩回，属安全序设计内）；重跑 install-part 用新包即可。

**屏幕进度（2026-10-13）**：长步骤（fsck/缩容）的输出重定向到日志文件，之前面板上几分钟毫无
动静，无法判断是否在进行。现在安装期间每 5 秒向内核日志打一条心跳，屏幕帧缓冲控制台显示
`E5-LINUX: installing, step N/5 <动作> (已用秒数)`，五个步骤各自有名字，开始/结束/失败均有
err 级日志行。**面板控制台字体无 CJK，屏幕上的行必须是 ASCII**（测试里有守卫），因此进度行
用英文；背光不被修改。更漂亮的图形进度（预渲染帧，如充电画面）未做。

**加密的 userdata 能不能缩**：能。Android 的 FBE 是文件级加密，文件系统元数据（superblock/
SIT/NAT/位图/检查点）保持明文，`resize.f2fs` 只搬元数据、把数据块当不透明字节移动，密钥与 IV
记在 inode/xattr 里、与块地址无关，因此离线缩容不需要密钥——本机（T551M，Android 13）实测：
22380MiB → 12140MiB 缩容成功，随后 Android 挂载正常。只有块层全盘加密（dm-default-key）会让
raw 端连 `f2fs52010` 都看不到；install-part 的第一步就是这个 magic 检查，不通过即
`stage=part-install no-f2fs` 安全退出、不写任何东西。

## 验证状态

- e5-gpt 10 项、part_root 5 项测试通过；boot/init 经 `sh -n`。
- 实机未验证：等待 TF 卡到位（先修好 userdata 的 F2FS 再缩容）。风险点：
  `resize.f2fs` 作用在厂商 F2FS 上（故强制先 fsck）、GPT 写入瞬间断电（双份
  重写兜底）、首启试启动靠 e5-boot-ok 清除标记。安装器需要新的引导镜像
  （`init-features` 令牌），用本仓库构建的包即是。
