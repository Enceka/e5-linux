'use strict';
'require view';
'require poll';
'require mu300.common as M';
'require mu300.data-sim as DataSim';
'require mu300.sim-radio as SimRadio';

return view.extend({
	load: function() { return Promise.resolve(); },
	render: function() {
		M.injectCss();
		var root = document.createElement('div');
		root.className = 'mud';
		root.innerHTML = '<div class="mud-card"><h3>SIM 卡管理</h3>' +
			'<p class="mud-note">切换上网卡后，看板、锁定和 AT 的查看卡槽会同步；仍可手动查看另一张卡。</p>' +
			'<div class="mud-data-sim-host"></div></div>';
		M.localize(root);
		this._control = DataSim.attach(root.querySelector('.mud-data-sim-host'));
		var radios=document.createElement('div'); radios.className='mud-card'; root.appendChild(radios);
		radios.style.marginTop='16px';
		this._radios=SimRadio.attach(radios);
		var self = this;
		this._refresh = function() {
			if (document.hidden) return Promise.resolve();
			self._radios.refresh();
			return M.callSimGet().then(function(data) { self._control.update(data); }, function() { self._control.update(null); });
		};
		this._refresh();
		poll.add(this._refresh, 2);
		return root;
	},
	unload: function() {
		poll.remove(this._refresh);
		if (this._control) this._control.dispose();
		if (this._radios) this._radios.dispose();
	},
	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
