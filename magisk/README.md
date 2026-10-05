# E5 Android → Linux Magisk 模块

在已 root 的 E5 Android 内安装 `e5-linux-switch-*.zip`，然后在 Magisk
模块列表点击 **E5 切回 Linux → 操作**，设备会重启进入已安装的 Linux。
安装模块不会自动切系统，也没有开机自动切换脚本。

模块使用 [Magisk 官方 action.sh 接口](https://topjohnwu.github.io/Magisk/guides.html)，
通过 [magiskboot](https://topjohnwu.github.io/Magisk/tools.html) 只读解包 `boot_b`，
确认其包含 e5-linux 的 initramfs，并确认已安装 Linux 根目录。支持已注册的
SD 多系统、旧 SD 安装和 userdata 内的旧镜像安装，保留当前 SD 的 default/next
选择。SD 注册内核必须与 boot_b 一致。

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
bash magisk/build.sh
```

输出位于 `out/magisk/`，时间精确到秒，使用 UTC+8。构建使用主线内核的
arm64 Docker 镜像 `e5-mainline-build`；静态辅助程序不依赖 Android 的 Python
或动态库。`E5_MAGISK_BUILD_IMAGE` 可指定已有的 arm64 C 编译环境。
