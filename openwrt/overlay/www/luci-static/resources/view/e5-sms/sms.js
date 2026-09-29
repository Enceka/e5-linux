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
var callTest = rpc.declare({ object: 'e5-sms', method: 'forward_test' });
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

// the segments a text takes: 70 characters a message (67 each when split),
// 160 (153) for plain ASCII
function segments(text) {
	var n = Array.from(text).length;
	if (n == 0) return 0;
	var ascii = /^[\x20-\x7e\n\r]*$/.test(text);
	var one = ascii ? 160 : 70, part = ascii ? 153 : 67;
	return n <= one ? 1 : Math.ceil(n / part);
}

function notify(ok, text) {
	ui.addNotification(null, E('p', text), ok ? 'info' : 'danger');
}

return view.extend({
	load: function() {
		return Promise.all([ callList(), callLog(), uci.load('e5-notify') ]);
	},

	reloadList: function() {
		return callList().then(L.bind(function(r) {
			if (r && r.sim) this.sim = r.sim;
			var sim = document.getElementById('e5-sms-sim');
			if (sim) sim.replaceChildren(this.renderSim(this.sim));
			var box = document.getElementById('e5-sms-list');
			if (box) box.replaceChildren(this.renderList(r));
		}, this));
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
		if (num) num.value = msg.number || '';
		if (text) { text.focus(); text.dispatchEvent(new Event('input')); }
		num && num.scrollIntoView({ behavior: 'smooth', block: 'center' });
	},

	// the other card: ModemManager has only the card in use, so its messages
	// are listed (and its new ones seen) once it is the card in use
	handleSwitch: function(card) {
		if (!confirm('切换到 SIM' + (card + 1) + '？\n\n数据连接也会切到这张卡，断开几十秒。'))
			return;
		return callSwitch(card).then(L.bind(function(r) {
			if (!(r && r.ok)) { notify(false, '切换失败：' + ((r && r.error) || '?')); return; }
			notify(true, '正在切换到 SIM' + (card + 1) + '，约半分钟到一分钟后刷新');
			window.setTimeout(L.bind(function() { location.reload(); }, this), 45000);
		}, this));
	},

	// the card to send from: the other one than the card in use is switched to
	// first, and waited for (ModemManager has the new card's modem registered
	// some 20-60 s later) -- step by step here, as one rpc call would outlast
	// LuCI's rpc timeout
	waitCard: function(card, until) {
		return callSim().then(L.bind(function(sim) {
			var up = sim && sim.card == card && /^(registered|connected|connecting)$/.test(sim.state || '');
			if (up) { this.sim = sim; return true; }
			if (Date.now() > until) return false;
			return new Promise(function(res) { window.setTimeout(res, 3000); })
				.then(L.bind(this.waitCard, this, card, until));
		}, this));
	},

	handleSend: function(ev) {
		var num = document.getElementById('e5-sms-number').value.trim();
		var text = document.getElementById('e5-sms-text').value;
		var card = +document.getElementById('e5-sms-card').value;
		var inUse = this.sim ? this.sim.card : card;
		if (!/^\+?[0-9 -]{3,24}$/.test(num)) { notify(false, '号码不对'); return; }
		if (!text.length) { notify(false, '没有内容'); return; }
		if (card != inUse && !confirm('要先切换到 SIM' + (card + 1) + ' 再发送：数据连接也会切到这张卡，断开几十秒。继续？'))
			return;
		var btn = ev.currentTarget;
		btn.disabled = true;
		var ready = Promise.resolve(true);
		if (card != inUse) {
			btn.textContent = '切换到 SIM' + (card + 1) + '…';
			ready = callSwitch(card).then(L.bind(function(r) {
				if (!(r && r.ok)) return false;
				return this.waitCard(card, Date.now() + 120000);
			}, this));
		}
		return ready.then(L.bind(function(ok) {
			if (!ok) { notify(false, 'SIM' + (card + 1) + ' 没有在 2 分钟内注册上网络，没有发送'); return; }
			btn.textContent = '发送中…';
			return callSend(num, text).then(L.bind(function(r) {
				if (r && r.ok) {
					notify(true, '已从 ' + (r.sim || ('SIM' + (card + 1))) + ' 发送到 ' + num);
					document.getElementById('e5-sms-text').value = '';
					document.getElementById('e5-sms-text').dispatchEvent(new Event('input'));
				} else {
					notify(false, '发送失败：' + ((r && r.error) || '?'));
				}
				return this.reloadList();
			}, this));
		}, this)).finally(function() {
			btn.disabled = false;
			btn.textContent = '发送';
		});
	},

	handleTest: function(ev) {
		var btn = ev.currentTarget;
		btn.disabled = true;
		return callTest().then(function(r) {
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
		var other = sim.card ? 0 : 1;
		return E('p', {}, [
			'当前是 ', E('strong', {}, sim.name + (sim.operator ? '（' + sim.operator + '）' : '')), ' 的短信。',
			'另一张卡的短信要切换到那张卡才能看到（它收到的新短信这边收不到通知，存在卡里）。 ',
			E('button', { 'class': 'btn cbi-button', 'click': L.bind(this.handleSwitch, this, other) }, '切换到 SIM' + (other + 1))
		]);
	},

	renderList: function(r) {
		var msgs = (r && r.messages) || [];
		if (r && r.error && !msgs.length)
			return E('p', { 'class': 'cbi-section-descr' }, '读不到短信：' + r.error + '（没有 SIM 卡或调制解调器还没就绪）');
		if (!msgs.length)
			return E('p', { 'class': 'cbi-section-descr' }, '没有短信');
		var rows = msgs.map(L.bind(function(m) {
			return E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td', 'style': 'white-space:nowrap' }, mmTime(m.time)),
				E('td', { 'class': 'td', 'style': 'white-space:nowrap' }, (m.direction == 'out' ? '发往 ' : '') + (m.number || '')),
				E('td', { 'class': 'td', 'style': 'white-space:pre-wrap;word-break:break-word' },
					m.text + (m.state == 'receiving' ? '（接收中…）' : '')),
				E('td', { 'class': 'td', 'style': 'white-space:nowrap' }, [
					m.direction == 'in' ? E('button', { 'class': 'btn cbi-button', 'click': L.bind(this.handleReply, this, m) }, '回复') : '',
					' ',
					E('button', { 'class': 'btn cbi-button cbi-button-remove', 'click': L.bind(this.handleDelete, this, m) }, '删除')
				])
			]);
		}, this));
		return E('table', { 'class': 'table' }, [
			E('tr', { 'class': 'tr table-titles' }, [
				E('th', { 'class': 'th' }, '时间'), E('th', { 'class': 'th' }, '号码'),
				E('th', { 'class': 'th' }, '内容'), E('th', { 'class': 'th' }, '')
			])
		].concat(rows));
	},

	renderLog: function(log) {
		if (!log || !log.length)
			return E('p', { 'class': 'cbi-section-descr' }, '还没有转发过');
		return E('table', { 'class': 'table' }, [
			E('tr', { 'class': 'tr table-titles' }, [
				E('th', { 'class': 'th' }, '时间'), E('th', { 'class': 'th' }, '来自'), E('th', { 'class': 'th' }, '结果')
			])
		].concat(log.slice(0, 20).map(function(e) {
			return E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td', 'style': 'white-space:nowrap' }, new Date(e.time * 1000).toLocaleString()),
				E('td', { 'class': 'td' }, (e.test ? '（测试）' : '') + (e.from || '')),
				E('td', { 'class': 'td', 'style': 'word-break:break-word' },
					e.ok ? '成功 HTTP ' + e.code : '失败：' + (e.error || ('HTTP ' + e.code)))
			]);
		})));
	},

	render: function(data) {
		var list = data[0], log = data[1];
		this.sim = (list && list.sim) || null;

		var m = new form.Map('e5-notify', '短信转发',
			'收到新短信时，用 curl 把它发到一个 webhook（HTTP 请求）。网址和正文里可以写 ' +
			'{from}（发件号码）、{text}（内容）、{time}（时间）、{sim}（SIM1/SIM2）、{device}（设备名），' +
			'会按所在位置自动转义：网址和表单里做 URL 编码，JSON 里做 JSON 转义（引号自己写在模板里）。' +
			'2xx 算成功，失败会在 10 秒和 30 秒后各重试一次。');
		var s = m.section(form.NamedSection, 'forward', 'forward');
		s.addremove = false;
		var o;

		o = s.option(form.Flag, 'enabled', '启用转发');

		o = s.option(form.ListValue, '_preset', '套用预设', '选一个会填好下面的网址、方式和正文，把其中的 Key / Token 换成你自己的');
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
		o.placeholder = 'https://example.com/sms';
		o.validate = function(section_id, v) {
			return (v == '' || /^https?:\/\/\S+$/.test(v)) ? true : '要以 http:// 或 https:// 开头';
		};

		o = s.option(form.ListValue, 'method', '方式');
		o.value('POST');
		o.value('GET');
		o.default = 'POST';

		o = s.option(form.ListValue, 'content_type', '正文类型');
		o.value('application/json', 'JSON (application/json)');
		o.value('application/x-www-form-urlencoded', '表单 (x-www-form-urlencoded)');
		o.value('text/plain', '纯文本 (text/plain)');
		o.default = 'application/json';
		o.depends('method', 'POST');

		o = s.option(form.TextValue, 'body', '正文模板');
		o.rows = 5;
		o.monospace = true;
		o.default = JSON_BODY;
		o.depends('method', 'POST');

		o = s.option(form.DynamicList, 'header', '额外的请求头', '例如 Authorization: Bearer xxx');
		o.placeholder = 'Name: value';

		o = s.option(form.Value, 'timeout', '超时（秒）');
		o.datatype = 'range(1,120)';
		o.default = '10';

		o = s.option(form.Button, '_test', '测试');
		o.inputtitle = '发一条测试消息';
		o.inputstyle = 'apply';
		o.onclick = L.bind(this.handleTest, this);

		var counter = E('span', { 'class': 'cbi-value-description' }, '0 字');
		var textarea = E('textarea', {
			'id': 'e5-sms-text', 'class': 'cbi-input-textarea', 'rows': 4, 'style': 'width:100%',
			'maxlength': 700, 'placeholder': '内容',
			'input': function(ev) {
				var t = ev.target.value, n = Array.from(t).length, k = segments(t);
				counter.textContent = n + ' 字' + (k > 1 ? '，按 ' + k + ' 条发送' : '');
			}
		});

		return m.render().then(L.bind(function(mapEl) {
			return E([], [
				E('h2', {}, '短信'),
				E('div', { 'class': 'cbi-section' }, [
					E('h3', {}, '收件箱'),
					E('div', { 'style': 'margin-bottom:.5em' }, [
						E('button', { 'class': 'btn cbi-button', 'click': L.bind(this.reloadList, this) }, '刷新')
					]),
					E('div', { 'id': 'e5-sms-sim' }, this.renderSim(this.sim)),
					E('div', { 'id': 'e5-sms-list' }, this.renderList(list))
				]),
				E('div', { 'class': 'cbi-section' }, [
					E('h3', {}, '发短信'),
					E('div', { 'class': 'cbi-value' }, [
						E('label', { 'class': 'cbi-value-title', 'for': 'e5-sms-card' }, '用哪张卡发'),
						E('div', { 'class': 'cbi-value-field' }, [
							E('select', { 'id': 'e5-sms-card', 'class': 'cbi-input-select' }, [0, 1].map(L.bind(function(c) {
								var cur = this.sim && this.sim.card == c;
								return E('option', { 'value': c, 'selected': (this.sim ? cur : c == 0) ? '' : null },
									'SIM' + (c + 1) + (cur ? '（当前' + (this.sim.operator ? '，' + this.sim.operator : '') + '）' : '（需要切换）'));
							}, this))),
							E('div', { 'class': 'cbi-value-description' }, '不是当前的卡时，会先切换过去（数据连接也跟着切），注册上网络后再发')
						])
					]),
					E('div', { 'class': 'cbi-value' }, [
						E('label', { 'class': 'cbi-value-title', 'for': 'e5-sms-number' }, '号码'),
						E('div', { 'class': 'cbi-value-field' },
							E('input', { 'id': 'e5-sms-number', 'type': 'tel', 'class': 'cbi-input-text', 'placeholder': '例如 10086' }))
					]),
					E('div', { 'class': 'cbi-value' }, [
						E('label', { 'class': 'cbi-value-title', 'for': 'e5-sms-text' }, '内容'),
						E('div', { 'class': 'cbi-value-field' }, [ textarea, counter ])
					]),
					E('div', { 'class': 'cbi-value' }, [
						E('label', { 'class': 'cbi-value-title' }, ''),
						E('div', { 'class': 'cbi-value-field' },
							E('button', { 'class': 'btn cbi-button cbi-button-apply', 'click': L.bind(this.handleSend, this) }, '发送'))
					])
				]),
				mapEl,
				E('div', { 'class': 'cbi-section' }, [
					E('h3', {}, '最近的转发'),
					E('div', { 'id': 'e5-sms-log' }, this.renderLog(log))
				])
			]);
		}, this));
	}
});
