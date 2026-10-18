#!/system/bin/sh
# Installing this ZIP explicitly requests TF deployment. No boot-time service
# or system overlay is installed, and this is NOT the separate switch module.
SKIPUNZIP=0
[ "$BOOTMODE" = true ] || abort '请在 Android root 管理器内安装 / Install from the Android root manager'
[ "$(uname -m)" = aarch64 ] || abort '需要 ARM64 内核 / ARM64 kernel required'
ui_print '***************************************'
ui_print ' OpenWrt TF deployment / TF 卡部署'
ui_print ' TF 第一分区（无分区则整卡）清空 / SELECTED TF TARGET WILL BE ERASED'
ui_print ' 不格式化 userdata；不写 NV / No userdata format or NV writes'
ui_print '***************************************'
E5_PACKAGE=$MODPATH
BB=$E5_PACKAGE/files/busybox
[ -f "$BB" ] && [ ! -L "$BB" ] || abort '缺少随包安装工具 / Bundled installer BusyBox missing'
chmod 755 "$BB"
for tool in sh chroot nsenter timeout sha256sum dd od blockdev tar gzip losetup mount umount mktemp stat readlink; do
    "$BB" --list | "$BB" grep -qx "$tool" || abort "安装工具缺少功能 / Installer applet missing: $tool"
done
# Require standalone applets, not Android's PATH or the manager's BusyBox.
ASH_STANDALONE=1 "$BB" sh -c 'PATH=/nonexistent; sha256sum "$1" >/dev/null' sh "$BB" || \
    abort '随包安装工具无法运行 / Bundled installer BusyBox is incompatible'
chmod 755 "$E5_PACKAGE/files/"*.sh "$E5_PACKAGE/files/e5-bootctl"
"$BB" timeout -k 10 1800 "$BB" nsenter -t 1 -m "$BB" env E5_PACKAGE="$E5_PACKAGE" ASH_STANDALONE=1 \
    "$BB" sh "$E5_PACKAGE/files/magisk-tf-install.sh" || \
    abort '安装未完成，已停止切槽。保留 /data/adb/e5-tf-install 日志和备份 / Installation failed; keep logs and backups'
# All bulk files belong to deployment, not a permanent Magisk service.
rm -f "$MODPATH/files/openwrt.ext4.gz" "$MODPATH/files/boot.img"
touch "$MODPATH/disable"
ui_print '安装完成；请手动重启 / SUCCESS: reboot manually to enter OpenWrt'
ui_print '模块可删除，不影响已安装系统 / You may remove this inert deployment module'
