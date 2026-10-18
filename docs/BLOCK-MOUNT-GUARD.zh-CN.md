# 挂载点与通信设备扫描过滤

公共 OpenWrt 镜像增加经过修补的 `block-mount` APK，适用于 E5、T551M、M8。
LuCI 原有「系统 → 挂载点」依赖 `/sbin/block`，无需另写一套挂载页面。

## 过滤位置

参考 MU300 仓库的 `fstools-probe-device-types.patch` 和 `block-probe-guard.h`，
把过滤放在 fstools `block.c` 的探测入口、打开设备之前。`/dev/sd*` 除了 USB
磁盘，还可能匹配展锐 `sdiag/sdiom` 等通信字符设备。即使调用时指定磁盘，
底层的扫描缓存仍可能遍历这些节点，因此不能只过滤 LuCI 的显示结果。

- 正常块设备、普通文件（包括 swap 文件）允许探测。
- 字符设备仅放行 sysfs 确认为 UBI 子系统的节点，不按文件名猜测。
- 其他字符设备、FIFO、socket、目录、不存在的路径及无法识别的节点直接跳过。
- 不打开被拒绝的节点，不增加定时器、守护进程或后台轮询。

这项改动提供挂载管理，不加入自动格式化策略，也不覆盖已有 fstab 配置。

## 构建与发布

`openwrt/build-block-mount.sh` 使用固定 SHA-256 的 OpenWrt 25.12.5 ARM64 SDK、
固定 fstools 源码版本编译真正的 APK。SDK 主机工具是 x86_64，ARM64 CI runner
通过 binfmt/QEMU 运行；SDK 缓存独立于内核，带编译互斥锁。

默认产物：`out/openwrt/block-mount-guarded.apk`，另带 `.sha256` 和 `.build-id`。
构建缓存校验脚本、补丁和包哈希。其他 OpenWrt 版本直接报错，需先更新 SDK
和 fstools 固定版本，避免把未经验证的 ABI 混进镜像。

公共 rootfs 构建通过 APK 安装该包及依赖，核对 `block`、`libblkid-tiny` 和
fstab 服务，并保存 `/etc/e5/block-mount.build-id`。发布检查拒绝缺少组件或
构建标识过期的镜像。CI 同时测试真正的 ARM64 APK。

```sh
sh openwrt/build-block-mount.sh
python3 openwrt/tests/block-probe.py
E5_TEST_BLOCK_APK="$PWD/out/openwrt/block-mount-guarded.apk" \
  E5_TEST_IMAGE=e5-openwrt-base:25.12.5 python3 openwrt/tests/block-probe.py
```

APK 测试只使用临时容器和临时 ext4 文件：验证依赖安装、文件系统发现，以及
混入 FIFO、指向 FIFO 的链接和通信字符设备链接后，`block info` / `block detect`
能限时完成。不会连接或扫描实机设备。

2026-10-12 已完成编译和容器验证：APK 正常安装，ext4 正常识别，全量扫描、
生成挂载配置及显式查询通信节点均通过。设备类型测试与发布检查回归通过。
同时修正了移植脚本的产物查找目录：此 SDK 的 APK 位于
`bin/targets/armsr/armv8/packages`，不能只搜索 `bin/packages`。

未来独立升级到未打补丁的软件源版本可能丢失过滤，更新 fstools 时应重编译此包。
这次没有重打完整固件或向实机安装；旧发行包和已有实机不会自动获得该组件。
