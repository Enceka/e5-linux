'use strict';
'require view';
'require rpc';
'require ui';
'require uci';
'require form';

// The E5's text messages (服务 -> 短信): the messages, sending one, and the
// forward of new ones to a webhook.  rpcd object e5-sms
// (/usr/share/rpcd/ucode/e5-sms.uc over /usr/libexec/e5-sms); the forward's
// settings are e5-notify.forward.

var callList = rpc.declare({ object: 'e5-sms', method: 'list' });
var callSend = rpc.declare({ object: 'e5-sms', method: 'send', params: [ 'number', 'text', 'card' ] });
var callSwitch = rpc.declare({ object: 'e5-sms', method: 'switch_card', params: [ 'card' ] });
var callSim = rpc.declare({ object: 'e5-sms', method: 'sim' });
var callDelete = rpc.declare({ object: 'e5-sms', method: 'delete', params: [ 'id' ] });
var callTest = rpc.declare({ object: 'e5-sms', method: 'forward_test', params: [ 'card' ] });
var callLog = rpc.declare({ object: 'e5-sms', method: 'forward_log', expect: { log: [] } });

var JSON_BODY = '{"from":"{from}","text":"{text}","time":"{time}","sim":"{sim}","device":"{device}"}';

// what a preset fills in; KEY, TOKEN and the like are the user's own
var PRESETS = {
	json: { name: '通用 JSON webhook', method: 'POST', type: 'application/json',
		url: 'https://example.com/sms', body: JSON_BODY },
	bark: { name: 'Bark (iOS)', method: 'POST', type: 'application/json',
		url: 'https://api.day.app/push',
		body: '{"device_key":"你的Key","title":"短信 {from}","body":"{text}","group":"E5"}' },
	pushplus: { name: 'PushPlus (微信)', method: 'POST', type: 'application/json',
		url: 'https://www.pushplus.plus/send',
		body: '{"token":"你的Token","title":"短信 {from}","content":"{text}\\n\\n{time} {sim}","template":"txt"}' },
	serverchan: { name: 'Server 酱', method: 'POST', type: 'application/x-www-form-urlencoded',
		url: 'https://sctapi.ftqq.com/你的SendKey.send',
		body: 'title={from}&desp={text}' },
	telegram: { name: 'Telegram Bot', method: 'POST', type: 'application/json',
		url: 'https://api.telegram.org/bot你的Token/sendMessage',
		body: '{"chat_id":"你的ChatID","text":"短信 {from}\\n{text}\\n{time}"}' },
	wecom: { name: '企业微信群机器人', method: 'POST', type: 'application/json',
		url: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的Key',
		body: '{"msgtype":"text","text":{"content":"短信 {from}\\n{text}\\n{time}"}}' },
	dingtalk: { name: '钉钉群机器人', method: 'POST', type: 'application/json',
		url: 'https://oapi.dingtalk.com/robot/send?access_token=你的Token',
		body: '{"msgtype":"text","text":{"content":"短信 {from}\\n{text}\\n{time}"}}' }
};

// "2026-09-29T16:40:12+08:00" -> "2026-09-29 16:40:12"
function mmTime(t) {
	return t ? String(t).replace('T', ' ').replace(/([+-]\d\d(:?\d\d)?|Z)$/, '') : '';
}

// Counts match the backend's GSM7/UTF-16 encoder and 16-bit multipart header.
function segments(text) {
	if (!text.length) return 0;
	var basic = '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà';
	var ext = '\f^{}\\[~]|€';
	var gsm = true, count = 0;
	Array.from(text).forEach(function(char) {
		if (basic.indexOf(char) >= 0) count++;
		else if (ext.indexOf(char) >= 0) count += 2;
		else gsm = false;
	});
	if (!gsm) return text.length <= 70 ? 1 : Math.ceil(text.length / 66);
	return count <= 160 ? 1 : Math.ceil(count / 152);
}

function safeText(value) {
	return document.createTextNode(String(value == null ? '' : value));
}

function notify(ok, text) {
	ui.addNotification(null, E('p', {}, safeText(text)), ok ? 'info' : 'danger');
}

return view.extend({
	load: function() {
		return Promise.all([ callList(), callLog(), uci.load('e5-notify') ]);
	},

	reloadList: function() {
		return callList().then(L.bind(function(r) {
			if (r && r.sim) this.sim = r.sim;
			this.list = r;
			var sim = document.getElementById('e5-sms-sim');
			if (sim) sim.replaceChildren(this.renderSim(this.sim));
			var box = document.getElementById('e5-sms-list');
			if (box) box.replaceChildren(this.renderList(r));
		}, this));
	},

	handleRefresh: function(ev) {
		var btn = ev.currentTarget;
		btn.disabled = true;
		btn.textContent = '刷新中…';
		return this.reloadList().catch(function() {
			notify(false, '刷新失败，请稍后重试');
		}).finally(function() {
			btn.disabled = false;
			btn.textContent = '刷新';
		});
	},

	handleDelete: function(msg) {
		if (!confirm('删除这条短信？\n\n' + (msg.number || '') + '：' + (msg.text || '').slice(0, 60)))
			return;
		return callDelete(msg.id).then(L.bind(function(r) {
			if (!(r && r.ok)) notify(false, '删除失败：' + ((r && r.error) || '?'));
			return this.reloadList();
		}, this));
	},

	handleReply: function(msg) {
		var num = document.getElementById('e5-sms-number');
		var text = document.getElementById('e5-sms-text');
		var card = document.getElementById('e5-sms-card');
		if (card && (msg.card === 0 || msg.card === 1)) card.value = String(msg.card);
		if (num) num.value = msg.number || '';
		if (text) { text.focus(); text.dispatchEvent(new Event('input')); }
		num && num.scrollIntoView({ behavior: 'smooth', block: 'center' });
	},

	// Switching the data SIM remains explicit; reading either inbox never switches.
	handleSwitch: function(card) {
		if (!confirm('切换到 SIM' + (card + 1) + '？\n\n数据连接也会切到这张卡，断开几十秒。'))
			return;
		return callSwitch(card).then(L.bind(function(r) {
			if (!(r && r.ok)) { notify(false, '切换失败：' + ((r && r.error) || '?')); return; }
			notify(true, '正在切换到 SIM' + (card + 1) + '，约半分钟到一分钟后刷新');
			window.setTimeout(L.bind(function() { location.reload(); }, this), 45000);
		}, this));
	},

	handleSend: function(ev) {
		var num = document.getElementById('e5-sms-number').value.trim();
		var text = document.getElementById('e5-sms-text').value;
		var card = +document.getElementById('e5-sms-card').value;
		if (!/^\+?[0-9 -]{3,24}$/.test(num)) { notify(false, '号码不对'); return; }
		if (!text.length) { notify(false, '没有内容'); return; }
		var btn = ev.currentTarget;
		btn.disabled = true;
		var ready = Promise.resolve(true);
		return ready.then(L.bind(function(ok) {
			if (!ok) { notify(false, '短信发送未启动'); return; }
			btn.textContent = '发送中…';
			return callSend(num, text, String(card)).then(L.bind(function(r) {
				if (r && r.ok) {
					notify(true, '已从 ' + (r.sim || ('SIM' + (card + 1))) + ' 发送到 ' + num);
					document.getElementById('e5-sms-text').value = '';
					document.getElementById('e5-sms-text').dispatchEvent(new Event('input'));
				} else {
					notify(false, '发送失败：' + ((r && r.error) || '?') + (r && r.submitted_parts ? '；已提交 ' + r.submitted_parts + '/' + r.total_parts + ' 段，请勿整条重发' : ''));
				}
				return this.reloadList();
			}, this));
		}, this)).finally(function() {
			btn.disabled = false;
			btn.textContent = '发送';
		});
	},

	handleTest: function(card, ev) {
		var btn = ev.currentTarget;
		btn.disabled = true;
		return callTest(card).then(function(r) {
			if (r && r.ok) notify(true, '测试转发成功（HTTP ' + r.code + '）');
			else notify(false, '测试转发失败：' + ((r && r.error) || '?') + '　（先保存设置再测试）');
			return callLog();
		}).then(L.bind(function(log) {
			var box = document.getElementById('e5-sms-log');
			if (box) box.replaceChildren(this.renderLog(log));
		}, this)).finally(function() { btn.disabled = false; });
	},

	renderSim: function(sim) {
		if (!sim) return '';
		return E('div', { 'class': 'e5-sms-sim' }, [
			E('div', {}, [
				E('div', { 'class': 'e5-sms-sim-name' }, [ '移动数据卡：', E('strong', {}, sim.name), sim.operator ? ' · ' + sim.operator : '' ]),
				E('p', { 'class': 'e5-sms-hint' }, '两张卡的短信合并显示，查看与接收不切换移动数据卡。')
			]),
			E('div', { 'class': 'e5-sms-filters' }, ['', '0', '1'].map(L.bind(function(card) {
				return E('button', { 'type': 'button', 'class': 'btn cbi-button' + ((this.filter || '') === card ? ' cbi-button-apply' : ''),
					'click': L.bind(function() { this.filter = card; document.getElementById('e5-sms-sim').replaceChildren(this.renderSim(this.sim)); document.getElementById('e5-sms-list').replaceChildren(this.renderList(this.list)); }, this) }, card === '' ? '全部' : 'SIM' + (+card + 1));
			}, this)))
		]);
	},

	renderList: function(r) {
		var msgs = (r && r.messages) || [];
		if (this.filter !== undefined && this.filter !== '') msgs = msgs.filter(L.bind(function(m) { return String(m.card) === this.filter; }, this));
		var nodes = [];
		if (r && r.error) nodes.push(E('p', { 'class': 'e5-sms-error' }, safeText(r.error)));
		Object.keys(r && r.slots || {}).forEach(function(card) {
			var state = r.slots[card];
			if (!state.ok) nodes.push(E('p', { 'class': 'e5-sms-error' }, safeText('SIM' + (+card + 1) + '：' + state.error)));
		});
		if (!msgs.length) nodes.push(E('p', { 'class': 'e5-sms-hint' }, '这张卡暂无短信'));
		return E('div', { 'class': 'e5-sms-inbox' }, nodes.concat(msgs.map(L.bind(function(m) {
			return E('article', { 'class': 'e5-sms-message', 'data-card': m.card }, [
				E('div', { 'class': 'e5-sms-message-head' }, [E('strong', {}, safeText((m.direction === 'out' ? '发往 ' : '') + (m.number || '未知号码'))),
					E('span', { 'class': 'e5-sms-badge sim' + (m.card + 1) }, safeText(m.sim || '来源未知')),
					E('time', {}, mmTime(m.time))]),
				E('p', { 'class': 'e5-sms-text' }, safeText(m.text || '')),
				E('div', { 'class': 'e5-sms-message-foot' }, [E('span', { 'class': 'e5-sms-hint' }, m.state === 'receiving' ? '长短信接收中…' : m.unread ? '未读' : ''),
					m.direction === 'in' ? E('button', { 'class': 'btn cbi-button', 'click': L.bind(this.handleReply, this, m) }, '回复') : '',
					E('button', { 'class': 'btn cbi-button cbi-button-remove', 'click': L.bind(this.handleDelete, this, m) }, '删除')])
			]);
		}, this))));
	},

	renderLog: function(log) {
		if (!log || !log.length)
			return E('p', { 'class': 'cbi-section-descr' }, '还没有转发过');
		return E('table', { 'class': 'table' }, [
			E('tr', { 'class': 'tr table-titles' }, [
				E('th', { 'class': 'th' }, '时间'), E('th', { 'class': 'th' }, '来源卡'), E('th', { 'class': 'th' }, '来自'), E('th', { 'class': 'th' }, '结果')
			])
		].concat(log.slice(0, 20).map(function(e) {
			return E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td', 'style': 'white-space:nowrap' }, new Date(e.time * 1000).toLocaleString()),
				E('td', { 'class': 'td' }, e.sim || '—'),
				E('td', { 'class': 'td' }, safeText((e.test ? '（测试）' : '') + (e.from || ''))),
				E('td', { 'class': 'td', 'style': 'word-break:break-word' },
					safeText(e.ok ? '成功 HTTP ' + e.code : '失败：' + (e.error || ('HTTP ' + e.code))))
			]);
		})));
	},

	render: function(data) {
		var list = data[0], log = data[1];
		this.sim = (list && list.sim) || null;
		this.list = list; this.filter = '';

		var m = new form.Map('e5-notify');
		var common = m.section(form.NamedSection, 'forward', 'forward', '转发模式'); common.addremove = false;
		var mode = common.option(form.ListValue, 'mode', '配置方式');
		mode.value('shared', '两张卡共用一套'); mode.value('per_sim', '两张卡分别设置'); mode.default = 'shared'; mode.rmempty = false;
		function profile(section, title, card, separate) {
		var s = m.section(form.NamedSection, section, 'forward', title); s.addremove = false;
		var o;
		o = s.option(form.Flag, 'enabled', '启用转发');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');

		o = s.option(form.ListValue, '_preset', '套用预设', '选一个会填好下面的网址、方式和正文，把其中的 Key / Token 换成你自己的');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.value('', '—');
		Object.keys(PRESETS).forEach(function(k) { o.value(k, PRESETS[k].name); });
		o.cfgvalue = function() { return ''; };
		o.write = o.remove = function() {};
		o.onchange = function(ev, section_id, value) {
			var p = PRESETS[value];
			if (!p) return;
			var set = L.bind(function(name, v) {
				var opt = this.map.lookupOption(name, section_id);
				if (opt && opt[0]) opt[0].getUIElement(section_id).setValue(v);
			}, this);
			set('url', p.url);
			set('method', p.method);
			set('content_type', p.type);
			set('body', p.body);
		};

		o = s.option(form.Value, 'url', '网址');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.placeholder = 'https://example.com/sms';
		o.validate = function(section_id, v) {
			return (v == '' || /^https?:\/\/\S+$/.test(v)) ? true : '要以 http:// 或 https:// 开头';
		};

		o = s.option(form.ListValue, 'method', '方式');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.value('POST');
		o.value('GET');
		o.default = 'POST';

		o = s.option(form.ListValue, 'content_type', '正文类型');
		o.value('application/json', 'JSON (application/json)');
		o.value('application/x-www-form-urlencoded', '表单 (x-www-form-urlencoded)');
		o.value('text/plain', '纯文本 (text/plain)');
		o.default = 'application/json';
		o.depends({ 'e5-notify.forward.mode': separate ? 'per_sim' : 'shared', method: 'POST' });

		o = s.option(form.TextValue, 'body', '正文模板');
		o.rows = 5;
		o.monospace = true;
		o.default = JSON_BODY;
		o.depends({ 'e5-notify.forward.mode': separate ? 'per_sim' : 'shared', method: 'POST' });

		o = s.option(form.DynamicList, 'header', '额外的请求头', '例如 Authorization: Bearer xxx');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.placeholder = 'Name: value';

		o = s.option(form.Value, 'timeout', '超时（秒）');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.datatype = 'range(1,120)';
		o.default = '10';

		o = s.option(form.Button, '_test', '测试');
		o.depends('e5-notify.forward.mode', separate ? 'per_sim' : 'shared');
		o.inputtitle = '发一条测试消息';
		o.inputstyle = 'apply';
		o.onclick = L.bind(this.handleTest, this, card);
		// Keep the other mode's saved targets when its fields are hidden.
		s.children.forEach(function(option) { option.retain = true; });
		}
		profile.call(this, 'forward', '共用转发配置', 0, false);
		profile.call(this, 'forward_sim1', 'SIM1 转发配置', 0, true);
		profile.call(this, 'forward_sim2', 'SIM2 转发配置', 1, true);

		var counter = E('span', { 'class': 'e5-sms-hint' }, '0 字');
		var textarea = E('textarea', {
			'id': 'e5-sms-text', 'class': 'cbi-input-textarea', 'rows': 5,
			'maxlength': 700, 'placeholder': '内容',
			'input': function(ev) {
				var t = ev.target.value, n = Array.from(t).length, k = segments(t);
				counter.textContent = n + ' 字' + (k > 1 ? '，按 ' + k + ' 条发送' : '');
			}
		});

		return m.render().then(L.bind(function(mapEl) {
			mapEl.classList.add('e5-sms-forward-map');
			return E('div', { 'class': 'e5-sms-page' }, [
				E('link', { 'rel': 'stylesheet', 'href': L.resource('view/e5-sms/sms.css') }),
				E('h2', {}, '短信'),
				E('div', { 'class': 'cbi-section e5-sms-panel' }, [
					E('div', { 'class': 'e5-sms-toolbar' }, [
						E('h3', {}, '收件箱'),
						E('button', { 'class': 'btn cbi-button', 'type': 'button', 'click': L.bind(this.handleRefresh, this) }, '刷新')
					]),
					E('div', { 'id': 'e5-sms-sim' }, this.renderSim(this.sim)),
					E('div', { 'id': 'e5-sms-list', 'class': 'e5-sms-list' }, this.renderList(list))
				]),
				E('div', { 'class': 'cbi-section e5-sms-panel e5-sms-compose' }, [
					E('div', { 'class': 'e5-sms-toolbar' }, [ E('h3', {}, '发送短信') ]),
					E('div', { 'class': 'e5-sms-field' }, [
						E('label', { 'for': 'e5-sms-card' }, '发送 SIM'),
						E('div', {}, [
							E('select', { 'id': 'e5-sms-card', 'class': 'cbi-input-select' }, [0, 1].map(L.bind(function(c) {
								var cur = this.sim && this.sim.card == c;
								return E('option', { 'value': c, 'selected': (this.sim ? cur : c == 0) ? '' : null },
									'SIM' + (c + 1) + (cur ? '（当前' + (this.sim.operator ? '，' + this.sim.operator : '') + '）' : ''));
							}, this))),
							E('p', { 'class': 'e5-sms-hint' }, '仅选择本次发送卡，不切换移动数据。')
						])
					]),
					E('div', { 'class': 'e5-sms-field' }, [
						E('label', { 'for': 'e5-sms-number' }, '收件号码'),
						E('div', {},
							E('input', { 'id': 'e5-sms-number', 'type': 'tel', 'class': 'cbi-input-text', 'placeholder': '例如 10086' }))
					]),
					E('div', { 'class': 'e5-sms-field' }, [
						E('label', { 'for': 'e5-sms-text' }, '短信内容'),
						E('div', {}, [ textarea, E('div', { 'class': 'e5-sms-send-actions' }, [
							counter,
							E('button', { 'class': 'btn cbi-button cbi-button-apply', 'type': 'button', 'click': L.bind(this.handleSend, this) }, '发送')
						]) ])
					]),
				]),
				E('div', { 'class': 'cbi-section e5-sms-panel' }, [
					E('div', { 'class': 'e5-sms-toolbar' }, [ E('h3', {}, '短信转发') ]),
					E('p', { 'class': 'e5-sms-description' }, '可让两张卡共用转发配置，也可分别启用并设置不同目标。转发按短信来源卡选择配置，不受当前上网卡影响。保存后可对相应卡发送测试消息。'),
					E('details', { 'class': 'e5-sms-template-help' }, [
						E('summary', {}, '模板变量与重试说明'),
						E('p', {}, '支持 {from}（发件号码）、{text}（内容）、{time}（时间）、{sim}（SIM1/SIM2）和 {device}（设备名）。网址、表单和 JSON 中的变量会自动转义；JSON 模板中的引号需要保留。'),
						E('p', {}, 'HTTP 2xx 表示成功；失败后分别等待 10 秒和 30 秒重试。')
					]),
					mapEl
				]),
				E('div', { 'class': 'cbi-section e5-sms-panel' }, [
					E('div', { 'class': 'e5-sms-toolbar' }, [ E('h3', {}, '最近的转发') ]),
					E('div', { 'id': 'e5-sms-log', 'class': 'e5-sms-list' }, this.renderLog(log))
				])
			]);
		}, this));
	}
});
