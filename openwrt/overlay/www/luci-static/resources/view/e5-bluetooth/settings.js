'use strict';
'require view';
'require form';

// The E5's Bluetooth settings (服务 -> 蓝牙): /etc/config/e5-bluetooth.
// Saved, e5-bt's reload trigger writes the boot setting into bluetoothd's
// AutoEnable (/usr/libexec/e5-bt-autostart).  Pairing and connecting are on
// the info screen (高级 -> 蓝牙).

return view.extend({
	render: function() {
		var m = new form.Map('e5-bluetooth', '蓝牙',
			'配对和连接耳机、音箱在设备屏幕上（高级 → 蓝牙）。');
		var s = m.section(form.NamedSection, 'main', 'bluetooth');
		s.addremove = false;

		var o = s.option(form.Flag, 'autostart', '开机启动',
			'开机时打开蓝牙。关掉后开机时蓝牙保持关闭（芯片的蓝牙部分也不上电），需要时在屏幕上打开。');
		o.default = '1';
		o.rmempty = false;

		return m.render();
	}
});
