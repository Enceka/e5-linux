# E5 Debian 一键刷入包

这个目录就是 Debian 包内的入口。它的使用方式与 OpenWrt 刷入包一致：

```text
Windows：flash.cmd              （默认：SD 卡首次安装）
macOS/Linux：./flash.sh
先检查：flash.cmd --check       或 ./flash.sh --check
```

默认流程会切到现有 OpenWrt，先检查 SD 卡是否能分配 `e5boot 32 MiB + Debian 4 GiB x 2`，再安装 Debian A/B。空间、分区、下载、解压、写入和镜像校验失败都会显示具体阶段和设备输出；已注册的卡会直接拒绝覆盖。默认不会拨打、接听或挂断电话，刷入完成后重启也由操作者决定。

其它入口：

```text
./flash.sh --update          # 已运行 Debian：更新非活动 Debian 槽
./flash.sh --android-update  # Android + root/adb：更新非活动 Debian 槽
```

两种更新都会先校验完整 raw 镜像、容量和新系统目录，只写非活动槽并设置试启动标志；脚本不会自动重启。Android 路径要求设备运行 slot A、adb 可见且 Shell 已获 root。

需要 Python 3.8+、adb（仅 Android 更新需要）和 USB LAN。默认网络参数为设备 `192.168.9.1`、电脑 `192.168.9.2`，可用 `E5_HOST`、`E5_LOCAL`、`E5_HTTP_PORT`、`E5_TELNET_USER`、`E5_TELNET_PASS` 覆盖。
