# Sourced by Magisk's module installer. Installing never changes boot slots.
[ "$BOOTMODE" = true ] || abort '请在 Android 的 Magisk 应用内安装 / Install through the Android Magisk app'
[ "$ARCH" = arm64 ] || abort '此模块仅支持 E5 arm64 / E5 arm64 only'
[ -b /dev/block/by-name/boot_b ] && [ -b /dev/block/by-name/misc ] && [ -b /dev/block/by-name/l_agdsp_a ] || abort '未找到 E5 所需分区 / Required E5 partitions are missing'
[ -x /data/adb/magisk/magiskboot ] || abort '缺少 magiskboot / magiskboot is missing'
set_perm "$MODPATH/e5-bootctl" 0 0 0755
set_perm "$MODPATH/action.sh" 0 0 0755
set_perm "$MODPATH/switch.sh" 0 0 0755
ui_print '安装完成后点击模块「操作」即可切回 Linux。'
ui_print 'Linux 须已安装；保留当前 SD 系统选择，试启动失败回退 Android。'
