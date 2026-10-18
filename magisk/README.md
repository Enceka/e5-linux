# E5 Android → Linux Magisk 模块

本文介绍独立的 **`e5-linux-switch` 切换模块**，不是完整固件的首次安装器。
新版 E5/T551M/M8 完整固件 ZIP 另有 Magisk TF 部署入口，会清空整张 TF 卡并安装 OpenWrt；
详细操作见完整安装包顶层 `START-HERE.md`，不要为了切换系统反复刷完整固件。

在已 root 的 E5 Android 内安装 `e5-linux-switch-*.zip`，然后在 Magisk
模块列表点击 **E5 切回 Linux → 操作**，设备会重启进入已安装的 Linux。
安装模块不会自动切系统，也没有开机自动切换脚本。

模块使用 [Magisk 官方 action.sh 接口](https://topjohnwu.github.io/Magisk/guides.html)，
通过 [magiskboot](https://topjohnwu.github.io/Magisk/tools.html) 只读解包 `boot_b`，
确认其包含 e5-linux 的 initramfs，并确认已安装 Linux 根目录。支持已注册的
SD 多系统、旧 SD 安装和 userdata 内的旧镜像安装，保留当前 SD 的 default/next
选择。SD 注册内核必须与 boot_b 一致。

1.1.0 起，点击「操作」时还会检查两槽的 `uboot/sml/teecfg/trustos/vbmeta`。
只对有差异的项先保存 A、B 两份原始镜像及 SHA-256，再把当前 Android A 的
启动链同步到 Linux B，并刷新缓存、回读校验。失败时尝试恢复已写过的 B 槽
项；恢复仍失败会明确报错并停止，不切槽、不重启。相同的启动链不会重写。
备份位于 `/data/adb/e5-bootchain/`，卸载模块不会删除它；不读写 NV 分区。
Android B、待完成的 B 槽 OTA、异常启动控制块或分区别名会被拒绝。

切换前读取当前 misc 的 bootloader_control，校验 BCAB 格式、版本、双槽、CRC
和 Android A 槽可回退状态。保存原始 32 字节备份后，仅修改 misc 偏移 2048
的 32 字节并回读校验，为 B 槽设置两次试启动机会。启动失败由 E5 LK 回退
Android；模块不写 boot_a、boot_b、SD 根分区、注册表或 Android userdata 镜像。
成功进入 Linux 后如需每次都启动 Linux，在信息屏设置默认系统，或运行
`e5-next-boot linux`。

需要 Android 位于 A 槽、arm64、Magisk 的 magiskboot 和已安装的 Linux。
校验失败会在 Magisk 操作输出中显示具体原因并停止。备份保存在模块目录的
`boot-control-日期-进程号.bin`，卸载模块会删除模块目录；卸载本身不改启动槽。

只读检查（不切槽、不重启）：

```sh
su -c 'ASH_STANDALONE=1 /data/adb/magisk/busybox sh /data/adb/modules/e5_linux_switch/switch.sh check'
```

本地打包及安全回归（使用普通临时文件，不访问真实 misc）：

```sh
python3 magisk/tests.py
python3 tools/tests/android-bootchain.py
bash magisk/build.sh
```

输出位于 `out/magisk/`，时间精确到秒，使用 UTC+8。构建使用主线内核的
arm64 Docker 镜像 `e5-mainline-build`；静态辅助程序不依赖 Android 的 Python
或动态库。`E5_MAGISK_BUILD_IMAGE` 可指定已有的 arm64 C 编译环境。

2026-10-06 实机验证：从 Android 执行已安装模块的 `switch.sh check` 与
`switch.sh reboot`，校验 boot_b／SD 安装并保存启动控制备份，成功返回 OpenWrt。
Magisk 界面的“操作”按钮尚未单独实测。

启动链同步新增路径通过临时文件模拟的写入、回读、信号中断和恢复失败测试，
尚未在实机执行。安装模块仍只提供切回入口，不负责首次格式化或部署 TF 卡。
