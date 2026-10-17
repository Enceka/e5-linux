'use strict';
'require baseclass';
'require rpc';
'require mu300.common as M';

var get = rpc.declare({object:'e5-charge', method:'get', expect:{'':{}}, nobatch:true});
var configure = rpc.declare({object:'e5-charge', method:'configure', params:['enabled','start','stop','power_on'], expect:{'':{}}, nobatch:true});
var fullOnce = rpc.declare({object:'e5-charge', method:'full_once', expect:{'':{}}, nobatch:true});

function message(error) {
	return M.translate({
		charge_invalid: '充电阈值必须是范围内的整数',
		charge_threshold_order: '恢复充电阈值必须低于停止阈值',
		charge_unavailable: '当前设备的充电控制暂不可用',
		charge_save_failed: '充电设置保存失败',
		charge_reload_failed: '充电设置已保存，但服务应用失败，请重试',
		charge_busy: '充电设置正在应用，请稍后重试'
	}[error] || '充电控制读取失败，请刷新重试');
}

return baseclass.extend({
	mount: function(root) {
		var card = document.createElement('section');
		card.className = 'mud-card mud-charge-card';
		card.style.marginTop = '14px';
		card.innerHTML = `
<style>
.mud-charge-controls{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;max-width:560px}
.mud-charge-controls input{width:100%;min-height:38px;box-sizing:border-box;padding:6px 10px;border:1px solid var(--hairline,var(--border,#ccc));border-radius:var(--radius-base,.5rem);background:var(--surface,var(--background,#fff));color:var(--text,#222)}
.mud-charge-card .mud-device-toggle{margin-top:16px}
.mud-charge-card .mud-note{line-height:1.65}
@media(max-width:420px){.mud-charge-controls{grid-template-columns:1fr;gap:0}}
</style>
<div class="mud-device-head"><h3>充电管理</h3><button type="button" class="mud-btn" data-charge="refresh">刷新</button></div>
<div class="mud-r"><span class="mud-k">当前电量</span><span class="mud-v" data-charge="capacity">--</span></div>
<div class="mud-r"><span class="mud-k">充电状态</span><span class="mud-v" data-charge="status" role="status" aria-live="polite">正在读取…</span></div>
<form data-charge="form">
 <label class="mud-device-toggle"><input type="checkbox" data-charge="enabled" disabled>启用充电上限</label>
 <label class="mud-device-toggle"><input type="checkbox" data-charge="power_on" disabled>插电直接启动 OpenWrt</label>
 <div class="mud-note">关机后插电，跳过充电动画并启动系统。关闭此选项保留关机充电；下次启动生效。</div>
 <div class="mud-charge-controls">
  <div class="mud-device-field"><label for="mud-charge-stop">停止充电于（50–100%）</label><input id="mud-charge-stop" data-charge="stop" type="number" min="50" max="100" step="1" required disabled></div>
  <div class="mud-device-field"><label for="mud-charge-start">恢复充电于（20–95%）</label><input id="mud-charge-start" data-charge="start" type="number" min="20" max="95" step="1" required disabled></div>
 </div>
 <div class="mud-note">到达上限后暂停充电，降至下限时恢复。关闭上限会恢复正常充电。设置与屏幕共用，重启后保留。</div>
 <div class="mud-device-actions"><button type="submit" class="mud-btn" data-charge="save" disabled>保存并应用</button><button type="button" class="mud-btn" data-charge="once" disabled>临时充满一次</button></div>
 <div class="mud-note" data-charge="note" role="status" aria-live="polite">临时充满后，自动恢复原来的充电上限。</div>
</form>`;
		M.localize(card);
		root.appendChild(card);
		var q = function(name) { return card.querySelector('[data-charge="' + name + '"]'); };
		var state = {}, pending = false;
		function disable() {
			['enabled','power_on','start','stop','save','once'].forEach(function(name) { q(name).disabled = pending || !state.available; });
			q('once').disabled = pending || !state.available || !!state.full_once;
			q('refresh').disabled = pending;
		}
		function paint(s) {
			state = s || {};
			q('capacity').textContent = Number.isInteger(s.capacity) ? s.capacity + '%' : '--';
			var label = !s.available ? '当前设备的充电控制暂不可用' : s.online && s.stopped ? '已按上限暂停充电' :
				s.status === 'Full' ? '已充满' : s.status === 'Charging' || (s.status === 'Not charging' && s.current_ma > 20) ? '正在充电' : !s.online ? '使用电池' : '未充电';
			q('status').textContent = M.translate(label);
			q('enabled').checked = !!s.enabled;
			q('power_on').checked = !!s.power_on;
			q('start').value = s.start == null ? 70 : s.start;
			q('stop').value = s.stop == null ? 80 : s.stop;
			q('once').textContent = M.translate(s.full_once ? '正在临时充满…' : '临时充满一次');
			disable();
		}
		async function perform(action, saving) {
			if (pending) return;
			pending = true; disable();
			q('note').textContent = M.translate(saving ? '正在应用充电设置…' : '正在读取…');
			try {
				var r = await action();
				if (!r || !r.ok) throw new Error(r && r.error);
				paint(r);
				q('note').textContent = M.translate(saving ? '充电设置已应用，与屏幕同步生效' : '临时充满后，自动恢复原来的充电上限。');
			} catch (error) {
				q('note').textContent = message(error.message);
				// A failed read must never enable controls with invented defaults.
				if (!saving) { state.available = false; q('status').textContent = message(error.message); }
			} finally { pending = false; disable(); }
		}
		q('refresh').onclick = function() { return perform(get, false); };
		q('form').onsubmit = function(event) {
			event.preventDefault();
			if (pending || !state.available || !q('form').reportValidity()) return;
			var start = Number(q('start').value), stop = Number(q('stop').value);
			if (start >= stop) { q('note').textContent = message('charge_threshold_order'); return; }
			return perform(function() { return configure(q('enabled').checked ? '1' : '0', String(start), String(stop), q('power_on').checked ? '1' : '0'); }, true);
		};
		q('once').onclick = function() { if (state.available && !state.full_once) return perform(fullOnce, true); };
		// One local snapshot on entry; no background polling or new policy loop.
		return perform(get, false);
	}
});
