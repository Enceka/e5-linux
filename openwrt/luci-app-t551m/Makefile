include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-t551m
PKG_VERSION:=1.1.0
PKG_RELEASE:=8
PKG_LICENSE:=MIT
PKG_MAINTAINER:=MU300 Linux contributors
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-t551m
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=Unisoc modem control center
  DEPENDS:=+luci-base +rpcd +jsonfilter +curl +ca-bundle +openssl-util +msmtp +python3-light +ucode +ucode-mod-fs +ucode-mod-ubus +ucode-mod-uci +ucode-mod-uloop
endef

define Package/luci-app-t551m/description
 A single LuCI application for the MU300 dashboard, cellular locks, raw AT
 terminal and SMS. Platform adapters isolate the UI from the modem daemon,
 serial port, SMS store and network-interface layout of the host firmware.
endef

define Package/luci-app-t551m/conffiles
/etc/config/unisoc_modem
/etc/config/unisoc_apn
/etc/e5-cpu.json
/etc/e5-cpu-voltage.json
/etc/e5-cpu-voltage-armed.json
/etc/unisoc-modem/forward/
/etc/e5-sounds/
/etc/e5/sim-radio
endef

define Build/Compile
endef

define Package/luci-app-t551m/install
	$(INSTALL_DIR) $(1)/www
	$(CP) ./htdocs/. $(1)/www/
	$(CP) ./root/. $(1)/
	chmod 0755 $(1)/etc/init.d/unisoc-modem-ui $(1)/etc/init.d/unisoc-traffic $(1)/etc/hotplug.d/net/90-unisoc-usb-host $(1)/etc/hotplug.d/iface/90-unisoc-usb-host $(1)/usr/libexec/rpcd/mu300dash $(1)/usr/libexec/unisoc-modem/*
	chmod 0755 $(1)/etc/init.d/e5-cpu $(1)/usr/libexec/rpcd/e5-cpu
	chmod 0755 $(1)/etc/init.d/unisoc-sms-forward
	chmod 0600 $(1)/etc/config/unisoc_apn
	chmod 0755 $(1)/usr/libexec/rpcd/e5-sounds
	chmod 0755 $(1)/usr/libexec/rpcd/e5-charge
	$(INSTALL_DIR) $(1)/usr/lib/lua/luci/i18n
	$(CP) ./lmo/. $(1)/usr/lib/lua/luci/i18n/
endef

define Package/luci-app-t551m/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	state=$$(uci -q get unisoc_modem.main.state_dir 2>/dev/null)
	state=$${state:-/etc/unisoc-modem/lock-state.d}
	old=/etc/mu300/dash/lock-state.d
	if [ -d "$$old" ] && [ ! -d "$$state" ]; then
		mkdir -p "$$state"
		cp -a "$$old"/. "$$state"/
	fi
	ucode /usr/libexec/unisoc-modem/disable-channel-analysis || exit 1
	rm -f /tmp/luci-indexcache /tmp/luci-modulecache/* 2>/dev/null
	uci -q get luci.languages.tr >/dev/null || uci set luci.languages.tr='Türkçe'
	uci commit luci
	[ ! -f /opt/e5/t551m-network-startup ] || python3 /opt/e5/t551m-network-startup --root /
	/etc/init.d/rpcd restart 2>/dev/null || true
	/etc/init.d/unisoc-modem-ui enable 2>/dev/null || true
	/etc/init.d/unisoc-modem-ui start 2>/dev/null || true


	/etc/init.d/unisoc-traffic enable 2>/dev/null || true
	/etc/init.d/unisoc-traffic start 2>/dev/null || true
	/etc/init.d/unisoc-sms-forward enable 2>/dev/null || true
	/etc/init.d/unisoc-sms-forward start 2>/dev/null || true
	/etc/init.d/e5-cpu disable 2>/dev/null || true
	/etc/init.d/e5-cpu enable 2>/dev/null || true
	/etc/init.d/e5-cpu start 2>/dev/null || true
}
exit 0
endef

define Package/luci-app-t551m/postrm
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] || {
	if [ "$$1" = remove ]; then
		/etc/init.d/unisoc-modem-ui stop 2>/dev/null || true
		/etc/init.d/unisoc-modem-ui disable 2>/dev/null || true
		/etc/init.d/unisoc-traffic stop 2>/dev/null || true
		/etc/init.d/unisoc-traffic disable 2>/dev/null || true
		/etc/init.d/unisoc-sms-forward stop 2>/dev/null || true
		/etc/init.d/unisoc-sms-forward disable 2>/dev/null || true
		/etc/init.d/e5-cpu disable 2>/dev/null || true
		rm -f /etc/unisoc-modem/usb-boot.conf
	fi
	rm -f /tmp/luci-indexcache /tmp/luci-modulecache/* 2>/dev/null
	/etc/init.d/rpcd restart 2>/dev/null || true
}
exit 0
endef

$(eval $(call BuildPackage,luci-app-t551m))
