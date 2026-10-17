// The info screen's settings ("高级"): categories of declarative items the page
// draws by type, and what reading and changing each one does.  Loaded by
// api.uc (loadfile) for every settings request and handed `ctx` -- the same
// helpers a plugin backend gets (docs/API.md, "Backend context").
//
// An item, as the page receives it:
//   { id, type, label, value, ... }
//   type toggle   value true|false
//        choice   value, options: [ { value, label } ]
//        number   value, min, max, step, unit
//        multi    value: [ ... ], options: [ { value, label } ] (none chosen = no lock)
//        action   no value; confirm: true -> the page asks for a second press
//        info     value is text, read-only
//        image    src: a picture the page shows full screen when the row is pressed
//   confirm      the change asks for a second press (it can cut the connection)
//   note         a line under the item (why, or what it does)
//   reload       after a change the page reads the category again (it shows in other items)
// label and note are { zh, en }.  A change is POST /api/settings/<category>
// { id, value } or { id } for an action; the reply is the item again, read back.

'use strict';

return function(ctx) {

const L = (zh, en) => ({ zh, en });

/* ---------- network: same verified jobs and per-SIM replay as LuCI ---------- */
function control_slot() {
    let slot = ctx.uci().get('e5-infoscreen','main','control_slot');
    return slot == '0' || slot == '1' ? slot : `${ctx.sim_card()}`;
}
function lock_call(method,args) { return ctx.ubus('mu300dash',method,args) ?? {error:'Network service unavailable'}; }
function band_list(text) { return filter(map(split(text ?? '',','),b=>int(b)),b=>b>0); }
function band_selection(locked, candidates) {
    let values = band_list(locked), caps = band_list(candidates);
    // Same as LuCI: zero mask or all supported bands means automatic. Raw
    // mask bits outside the candidate list must never be resubmitted by UI.
    if (!length(values) || (length(caps) && !length(filter(caps,b=>index(values,b)<0)))) return [];
    return filter(values,b=>index(caps,b)>=0);
}
function band_summary(locked, candidates, prefix) {
    let values = band_list(locked), caps = band_list(candidates);
    if (!length(caps)) return L('频段能力暂不可用，请刷新','Band capabilities unavailable; refresh');
    if (!length(values) || !length(filter(caps,b=>index(values,b)<0)))
        return L(`自动（支持 ${length(caps)} 个）`,`Auto (${length(caps)} supported)`);
    let bands = join(' ',map(values,b=>prefix+b));
    return L(`已锁 ${length(values)} 个：${bands}`,`Locked ${length(values)}: ${bands}`);
}


const network = {
    id:'network',label:L('网络','Network'),
    items:function() {
        let slot = control_slot(), data = lock_call('lock_get',{slot}), caps = data.caps ?? {};
        // Missing caches stay unknown; never manufacture an unlocked state.
        let state = data.mode != null && !data.error;
        let c = ctx.uci(), cells = data.cells ?? [];
        let radio_policy = lock_call('sim_radio_get',{});
        let opts = [{value:'off',label:L('解除所有小区锁定','Unlock all cells')},
                    {value:'auto',label:L('锁定当前服务小区','Lock serving cell')}];
        for (let cell in cells) push(opts,{value:cell,label:cell});
        let radio = lock_call('cells',{slot}).cell ?? {};
        let candidates = [...(radio.neigh ?? [])];
        for (let rat in ['lte','nr']) if (radio[rat])
            push(candidates,{...radio[rat],rat,arfcn:radio[rat].arfcn ?? radio[rat].earfcn});
        for (let cell in candidates) {
            if (cell.arfcn == null || cell.pci == null || index(['lte','nr'],cell.rat)<0) continue;
            let value=cell.rat+':'+cell.arfcn+','+cell.pci;
            if (!length(filter(opts,o=>o.value==value))) push(opts,{value,label:uc(cell.rat)+' PCI '+cell.pci+' · '+cell.arfcn});
        }
        let items = [
            {id:'control_slot',type:'choice',label:L('查看 / 控制卡槽','View / control SIM'),
             value:c.get('e5-infoscreen','main','control_slot') ?? 'data',reload:true,
             options:[{value:'data',label:L('跟随数据卡','Follow data SIM')},{value:'0',label:'SIM 1'},{value:'1',label:'SIM 2'}],
             note:L('仅选择设置对象，不切换上网卡','Selects the control target without switching the data SIM')},
            {id:'sim_card',type:'choice',label:L('上网 SIM 卡','Data SIM'),confirm:true,
             value:c.get('e5-sim','main','card') ?? `${ctx.sim_card()}`,
             options:[{value:'0',label:'SIM 1'},{value:'1',label:'SIM 2'}],
             note:L('切换后重新连接网络','Reconnects after switching')},
            {id:'apn',type:'category',category:'apn',label:L('接入点 APN','Access points (APN)'),
             note:L('与网页共用，按当前上网卡保存','Shared with the web; saved for the current data SIM')},
            ...map([0,1], n=>({id:'sim_radio'+n,type:radio_policy.ok?'toggle':'info',confirm:true,slot:`${n}`,
                label:L(`SIM ${n+1} 射频`,`SIM ${n+1} radio`),value:radio_policy.ok?radio_policy.enabled[n]:'--',
                note:L('重启后保留；关闭后该卡无法通话、收短信或上网','Saved across reboots; off disables calls, SMS and data for this SIM')})),
            {id:'lock_state',type:'info',label:L('锁定状态','Lock status'),value:'SIM '+(int(slot)+1),
             note:data.error ?? L('与网页共用设置和开机回放','Shares settings and boot replay with the web dashboard')},
            {id:'lock_refresh',type:'action',label:L('刷新锁定状态','Refresh lock state')},
            {id:'net_mode',type:state ? 'choice':'info',label:L('网络模式','Network mode'),confirm:true,slot,
             value:data.mode?.label ?? '--',options:map([['auto',L('自动','Auto')],['5g4g','5G/4G'],['4g',L('仅 4G','4G only')],['sa','5G SA'],['nsa','5G NSA']],m=>({value:m[0],label:m[1]}))},
            {id:'nr_mode',type:state?'choice':'info',label:L('5G 组网','5G access'),confirm:true,slot,
             value:state?(data.mode.gran=='1'?'sa':'nsa'):'--',options:[{value:'sa',label:'SA + NSA'},{value:'nsa',label:L('仅 NSA','NSA only')}]},
            {id:'endc',type:state ? 'toggle':'info',label:'EN-DC',confirm:true,slot,value:state ? data.endc == '1' : '--'},
            {id:'auto_apply',type:'toggle',label:L('开机自动应用','Apply on boot'),slot,value:!!data.auto_apply,
             note:L('AT 就绪、首次拨号前应用，与网页共用一份设置','Apply after AT is ready, before initial dialing; shared with the web')},
            {id:'lte_bands',type:state ? 'multi':'info',label:L('LTE 频段锁定','LTE band lock'),confirm:true,slot,
             value:state ? band_selection(data.lte?.locked,caps.lte) : null,options:map(band_list(caps.lte),b=>({value:b,label:'B'+b})),
             display_value:state ? band_summary(data.lte?.locked,caps.lte,'B') : null,
             none_label:L('自动','Auto'),
             note:L('都不选 = 不锁定','None selected = unlocked')},
            {id:'nr_bands',type:state ? 'multi':'info',label:L('NR 频段锁定','NR band lock'),confirm:true,slot,
             value:state ? band_selection(data.nr?.locked,caps.nr) : null,options:map(band_list(caps.nr),b=>({value:b,label:'n'+b})),
             display_value:state ? band_summary(data.nr?.locked,caps.nr,'n') : null,
             none_label:L('自动','Auto'),
             note:length(band_list(caps.nr)) ? L('都不选 = 不锁定','None selected = unlocked') : L('未获取到 NR 能力，请刷新；仍可解除锁定','NR capabilities unavailable; refresh or clear the lock')},
            {id:'bands_default',type:'action',label:L('恢复默认频段','Default bands'),confirm:true,slot},
            {id:'cell_lock',type:state ? 'choice':'info',label:L('锁定小区','Cell lock'),confirm:true,slot,
             value:state ? (cells[0] ?? 'off') : '--',options:opts,
             note:length(cells) ? join(' · ',cells) : L('候选与网页共用；尚未加载时可刷新','Candidates are shared with the web; refresh if still loading')},
            {id:'reconnect',type:'action',label:L('重新连接网络','Reconnect'),confirm:true}
        ];
        return items;
    },
    set:function(id,value,slot) {
        if (id == 'control_slot') {
            if (index(['data','0','1'],value)<0) return 'Invalid SIM slot';
            let c=ctx.uci();c.set('e5-infoscreen','main','control_slot',value);
            return c.commit('e5-infoscreen') ? null : 'Cannot save SIM selection';
        }
        if (id == 'sim_card') {
            if (value != '0' && value != '1') return 'unknown card';
            ctx.forget('modem');
            let r=lock_call('sim_set',{slot:value,current:`${ctx.sim_card()}`,confirm:true});
            return r.ok ? (r.id?{job:r.id,slot:value,service:'sim'}:null) : r.error ?? 'Cannot start SIM switch';
        }
        if (id == 'sim_radio0' || id == 'sim_radio1') {
            if (type(value)!='bool') return 'Invalid radio state';
            let target=id=='sim_radio1'?'1':'0',r=lock_call('sim_radio_set',{slot:target,enabled:value,confirm:true});
            return r.ok && r.id ? {job:r.id,slot:target,service:'sim'} : r.error ?? 'Cannot start radio operation';
        }
        if (id == 'reconnect') {ctx.forget('modem');ctx.run('(ifup wan) >/dev/null 2>&1 &');return null;}
        slot ??= control_slot();
        if (slot != '0' && slot != '1') return 'Invalid SIM slot';
        if (id == 'lock_refresh') {
            let r=lock_call('lock_get',{slot,fresh:'1'});return r.error ?? null;
        }
        let kind, val;
        if (id == 'net_mode' && index(['auto','4g','sa','nsa','5g4g'],value)>=0) {kind='mode';val=value;}
        else if (id == 'nr_mode' && index(['sa','nsa'],value)>=0) {kind='gran';val=value;}
        else if (index(['endc','auto_apply'],id)>=0 && type(value)=='bool') {kind=id;val=value?'on':'off';}
        else if (id == 'lte_bands' || id == 'nr_bands') {
            if (type(value)!='array' || length(filter(value,b=>type(b)!='int' || b<1 || b>256))) return 'Invalid band list';
            kind=id=='lte_bands'?'lte':'nr';val=join(',',value);
        } else if (id == 'bands_default') {kind='bands_default';val='';}
        else if (id == 'cell_lock' && type(value)=='string') {kind='cell';val=value;}
        else return 'Invalid network setting';
        let r=lock_call('lock_set',{slot,kind,val});
        return r.ok && r.started && r.id ? {job:r.id,slot} : r.error ?? 'Cannot start network operation';
    }
};

/* ---------- charging, notifications, screen: uci-backed ---------- */

// a setting that is a uci option: `apply` runs after a change
function uci_item(def) {
	let u = split(def.uci, '.');
	let raw = ctx.uci().get(u[0], u[1], u[2]) ?? def.default;
	let v = raw;
	if (def.type == 'toggle') v = (raw == '1');
	else if (def.type == 'number') v = +raw;
	// what the page sees: not the uci name, the apply command or the converters
	let out = { value: (def.to_page ? def.to_page(v) : v) };
	for (let k in [ 'id', 'type', 'label', 'note', 'confirm', 'options', 'min', 'max', 'step', 'unit' ])
		if (def[k] != null) out[k] = def[k];
	return out;
}

function uci_set(def, value) {
	let u = split(def.uci, '.');
	if (def.from_page) value = def.from_page(value);
	let v;
	if (def.type == 'toggle') v = value ? '1' : '0';
	else if (def.type == 'number') {
		v = +value;
		if (v != v || v < def.raw_min || v > def.raw_max) return 'out of range';
		v = `${int(v)}`;
	}
	else if (def.type == 'choice') {
		let ok = false;
		for (let o in def.options) if (`${o.value}` == `${value}`) ok = true;
		if (!ok) return 'not a choice';
		v = `${value}`;
	}
	let c = ctx.uci();
	if (u[0] == 'e5-charge' && index(['start','stop'],u[2]) >= 0) {
		let start=u[2]=='start' ? +v : +(c.get('e5-charge','main','start') ?? 70);
		let stop=u[2]=='stop' ? +v : +(c.get('e5-charge','main','stop') ?? 80);
		if (start>=stop) return 'Charge start must be lower than stop';
	}
	if (!c.set(u[0], u[1], u[2], v) || !c.commit(u[0])) return 'Cannot save setting';
	if (def.apply && ctx.run(def.apply) != 0) return 'Setting saved but apply failed';
	return null;
}

function uci_category(id, label, defs, extra_items, extra_set) {
	return {
		id, label,
		items: function() {
			let out = map(defs, uci_item);
			if (extra_items) out = [ ...extra_items(), ...out ];
			return out;
		},
		set: function(item, value) {
			for (let d in defs)
				if (d.id == item) return uci_set(d, value);
			return extra_set ? extra_set(item, value) : 'no such setting';
		}
	};
}

const charge = uci_category('charge', L('充电', 'Charging'), [
	{ id: 'power_on', type:'toggle', uci:'e5-charge.main.power_on', default:'0',
	  label:L('插电直接启动','Start when plugged in'),
	  note:L('关机后插电跳过充电动画，下次启动生效','Skip the charging screen on the next charger boot') },
	{ id: 'enabled', type: 'toggle', uci: 'e5-charge.main.enabled', default: '0',
	  label: L('充电上限', 'Charge limit'), apply: '/etc/init.d/e5-charge reload',
	  note: L('到上限停止充电，降到下限再充', 'Stop at the upper limit, charge again at the lower') },
	{ id: 'stop', type: 'number', uci: 'e5-charge.main.stop', default: '80', min: 50, max: 100, step: 5, unit: '%',
	  raw_min: 50, raw_max: 100, label: L('停止充电于', 'Stop at'), apply: '/etc/init.d/e5-charge reload' },
	{ id: 'start', type: 'number', uci: 'e5-charge.main.start', default: '70', min: 20, max: 95, step: 5, unit: '%',
	  raw_min: 20, raw_max: 95, label: L('恢复充电于', 'Charge again at'), apply: '/etc/init.d/e5-charge reload' }
], function() {
	let st = ctx.sh('/usr/libexec/e5-charge status 2>/dev/null') ?? '';
	let m = match(st, /capacity=([0-9]+) status=([^ ]+)/);
	let once = match(st, /full_once=1/);
	let paused = match(st, /stopped=1/);
	// (as the status bar has it, app.js chargeState: "Not charging" while current
	// flows in is charging, and only 100 % is full)
	let ma = +(trim(ctx.sh('cat /sys/class/power_supply/battery/current_now 2>/dev/null') ?? '') || '0') / 1000;
	let word = !m ? null : paused ? L('已暂停充电', 'paused')
		: (m[2] == 'Full' || +m[1] >= 100) ? L('已充满', 'full')
		: (m[2] == 'Charging' || (m[2] == 'Not' && ma > 20)) ? L('充电中', 'charging')
		: (m[2] == 'Discharging') ? L('使用电池', 'on battery')
		: (m[2] == 'Not') ? L('未充电', 'not charging') : L(m[2], m[2]);
	return [
		{ id: 'state', type: 'info', label: L('当前', 'Now'),
		  value: m ? L(`${m[1]}% · ${word.zh}`, `${m[1]}% · ${word.en}`) : '--' },
		{ id: 'full_once', type: 'action', label: once ? L('正在临时充满…', 'Charging to full…') : L('临时充满一次', 'Charge to full once'),
		  note: L('充到 100% 后回到上限', 'Back to the limit at 100 %') }
	];
}, function(item, value) {
	if (item != 'full_once') return 'no such setting';
	let c = ctx.uci();
	c.set('e5-charge', 'main', 'full_once', '1');
	c.commit('e5-charge');
	ctx.run('/etc/init.d/e5-charge reload');
	return null;
});

const notify = uci_category('notify', L('通知', 'Notifications'), [
	{ id: 'vibrate', type: 'toggle', uci: 'e5-notify.sms.vibrate', default: '1', label: L('短信震动', 'Vibrate on SMS') },
	{ id: 'screen', type: 'toggle', uci: 'e5-notify.sms.screen', default: '1', label: L('短信亮屏', 'Light up on SMS') },
	{ id: 'sound', type: 'toggle', uci: 'e5-notify.sms.sound', default: '1', label: L('短信提示音', 'Sound on SMS'),
	  note: L('按“声音”里的音量播放', 'At the volume set under Sound') }
], function() {
	return [ { id: 'test', type: 'action', label: L('测试短信提醒', 'Test SMS notification') } ];
}, function(item, value) {
	if (item != 'test') return 'no such setting';
	ctx.run('(e5-sms-notify test) >/dev/null 2>&1 &');
	return null;
});

// the speaker (e5-linux's e5-audio and e5-volume): shown when it is there
const sound = uci_category('sound', L('声音', 'Sound'), [
	{ id: 'volume', type: 'number', uci: 'e5-audio.main.volume', default: '10', min: 0, max: 15, step: 1,
	  raw_min: 0, raw_max: 15, label: L('媒体音量', 'Media volume'), apply: '/usr/libexec/e5-volume apply',
	  note: L('非通话时音量键调节此项；0 为静音', 'Volume keys adjust this outside calls; 0 is mute') },
	{ id: 'call_volume', type: 'number', uci: 'e5-audio.main.call_volume', default: '15', min: 0, max: 15, step: 1,
	  raw_min: 0, raw_max: 15, label: L('通话音量', 'Call volume'),
	  note: L('通话时音量键调节此项；0 仅静音接听声音', 'Volume keys adjust this during calls; 0 mutes received audio only') }
], function() {
	return [ { id: 'test', type: 'action', label: L('播放测试音', 'Play a test sound') } ];
}, function(item, value) {
	if (item != 'test') return 'no such setting';
	ctx.run('/usr/libexec/e5-volume play beep >/dev/null 2>&1');
	return null;
});
const has_sound = ctx.run('[ -x /usr/libexec/e5-volume ]') == 0;

const screen = uci_category('screen', L('屏幕', 'Screen'), [
	// shown in percent, stored as the backlight level 1-255
	{ id: 'brightness', type: 'number', uci: 'e5-infoscreen.main.brightness', default: '120',
	  min: 5, max: 100, step: 5, unit: '%', raw_min: 1, raw_max: 255, label: L('亮度', 'Brightness'),
	  to_page: (v) => int((v * 100 + 127) / 255), from_page: (p) => int((+p * 255 + 50) / 100) },
	{ id: 'idle', type: 'choice', uci: 'e5-infoscreen.main.idle', default: '60', label: L('自动息屏', 'Screen off after'),
	  options: [ { value: '15', label: L('15 秒', '15 s') }, { value: '30', label: L('30 秒', '30 s') },
	             { value: '60', label: L('1 分钟', '1 min') }, { value: '120', label: L('2 分钟', '2 min') },
	             { value: '300', label: L('5 分钟', '5 min') }, { value: '0', label: L('从不', 'Never') } ] },
	{ id: 'touch', type: 'toggle', uci: 'e5-infoscreen.main.touch', default: '1', label: L('触摸', 'Touch'),
	  note: L('关闭后只用按键操作', 'Off: the keys only') },
	{ id: 'lang', type: 'choice', uci: 'e5-infoscreen.main.lang', default: 'zh', label: L('语言', 'Language'),
	  options: [ { value: 'zh', label: L('中文', '中文') }, { value: 'en', label: L('English', 'English') } ] }
]);

/* ---------- system ---------- */

// zonename -> the POSIX TZ string OpenWrt keeps in system.timezone
const ZONES = [
	[ 'Asia/Shanghai', 'CST-8', L('中国 (北京时间)', 'China (Beijing)') ],
	[ 'Asia/Hong_Kong', 'HKT-8', L('中国香港', 'China (Hong Kong)') ],
	[ 'Asia/Taipei', 'CST-8', L('中国台湾', 'China (Taiwan)') ],
	[ 'Asia/Singapore', '<+08>-8', L('新加坡', 'Singapore') ],
	[ 'Asia/Tokyo', 'JST-9', L('东京', 'Tokyo') ],
	[ 'Asia/Seoul', 'KST-9', L('首尔', 'Seoul') ],
	[ 'Asia/Kolkata', 'IST-5:30', L('印度', 'India') ],
	[ 'Asia/Dubai', '<+04>-4', L('迪拜', 'Dubai') ],
	[ 'Europe/Moscow', 'MSK-3', L('莫斯科', 'Moscow') ],
	[ 'Europe/Berlin', 'CET-1CEST,M3.5.0,M10.5.0/3', L('中欧 (柏林)', 'Central Europe (Berlin)') ],
	[ 'Europe/London', 'GMT0BST,M3.5.0/1,M10.5.0', L('伦敦', 'London') ],
	[ 'America/New_York', 'EST5EDT,M3.2.0,M11.1.0', L('美国东部', 'US Eastern') ],
	[ 'America/Chicago', 'CST6CDT,M3.2.0,M11.1.0', L('美国中部', 'US Central') ],
	[ 'America/Los_Angeles', 'PST8PDT,M3.2.0,M11.1.0', L('美国西部', 'US Pacific') ],
	[ 'UTC', 'UTC0', L('UTC', 'UTC') ]
];

function system_section() {
	let name = null;
	ctx.uci().foreach('system', 'system', (s) => { name ??= s['.name']; });
	return name;
}

// when the image was built, in the device's time zone: /etc/e5/build-time
// (e5-linux's build-rootfs.sh writes it), else when its version file was
// written -- the same moment, for an image from before the file
function build_time() {
	let t = +(ctx.read_trim('/etc/e5/build-time') ?? '');
	if (!t) t = require('fs').stat('/etc/e5/image-version')?.mtime;
	if (!t) return null;
	let lt = localtime(t);
	return sprintf('%04d-%02d-%02d %02d:%02d', lt.year, lt.mon, lt.mday, lt.hour, lt.min);
}

// what the next reboot boots (e5-linux's e5-next-boot: the slots in misc as they
// stand -- a trial boot of Linux goes back to Android unless Linux is the default)
function next_boot() {
	let t = trim(ctx.sh('e5-next-boot next 2>/dev/null') ?? '');
	if (t == 'linux') return { value: t, label: L('Linux', 'Linux') };
	if (t == 'android') return { value: t, label: L('Android', 'Android') };
	return null;
}

// the default e5-next-boot keeps (/etc/e5linux/default-boot: linux re-arms slot b
// on every boot that comes up).  A trial image (e5.openwrt= on the command line,
// the mainline kernel's) is never the default: boot/init writes android there
function default_boot() {
	return ctx.read_trim('/etc/e5linux/default-boot') == 'linux' ? 'linux' : 'android';
}
function trial_image() {
	if (ctx.read_trim('/etc/e5/t551m-persistent') != null && ctx.read_trim('/etc/e5/device-profile') == 't551m') return false;
	return match(ctx.read_trim('/proc/cmdline') ?? '', /(^| )e5\.openwrt=/) != null;
}

// the screen's own online update (/usr/libexec/e5-infoscreen/update): what the last check found,
// and whether an update or a rollback is running
const UPDATES = loadfile('/usr/share/e5-infoscreen/updates.uc', { raw_mode: true })()(ctx);
function update_state() {
	let s = UPDATES.state();
	let note;
	if (s.busy) note = L('正在更新，完成后屏幕会重新载入', 'Updating; the screen reloads when it is done');
	else if (s.checking) note = L('正在检查更新', 'Checking for updates');
	else if (s.incompatible) note = L('上游版本尚未包含设备适配，请使用适配固件或更新包','Upstream release lacks device integration; use a compatible firmware or update package');
	else if (s.available) note = L(`有新版本 ${s.latest.version}`, `${s.latest.version} is out`);
	else if (s.error) note = L(`检查失败：${s.error}`, `The check failed: ${s.error}`);
	else if (s.checked_at) note = L('已是最新版本', 'Up to date');
	else note = L('从 GitHub 获取最新的信息屏版本', 'Asks GitHub for the latest info screen');
	return { ...s, cur: s.current, note, newer: s.available && !s.busy && !s.checking };
}

const traffic_records = {
	id:'traffic_clear',parent:'system',label:L('清空流量记录','Clear traffic records'),
	items:function() {
		return map(['0','1','all'],slot=>({
			id:'clear_' + slot,type:'action',confirm:true,reload:true,
			label:slot == 'all' ? L('清空两张卡记录','Clear both SIMs') : L(`清空 SIM ${int(slot)+1} 记录`,`Clear SIM ${int(slot)+1}`),
			note:L('今日、本月、历史和周期校准清零；保留套餐设置。不可撤销。','Clear daily, monthly, historical usage and cycle adjustments; keep plan settings. Cannot be undone.')
		}));
	},
	set:function(id) {
		let slot = id == 'clear_0' ? '0' : id == 'clear_1' ? '1' : id == 'clear_all' ? 'all' : null;
		if (slot == null) return 'invalid_slot';
		let r = ctx.ubus('unisoc.traffic','clear',{slot,confirm:true});
		return r?.ok ? null : r?.error ?? 'traffic_unavailable';
	}
};

const system_cat = {
	id: 'system', label: L('系统', 'System'),
	items: function() {
		let sec = system_section();
		let zone = sec ? ctx.uci().get('system', sec, 'zonename') : null;
		let next = next_boot();
		let u = update_state();
		return filter([
			{ id: 'timezone', type: 'choice', label: L('时区', 'Time zone'), value: zone ?? 'UTC',
			  options: map(ZONES, (z) => ({ value: z[0], label: z[2] })),
			  note: L('屏幕会重新载入', 'The screen reloads') },
			{ id: 'clock_seconds', type: 'toggle', label: L('时间显示秒', 'Clock with seconds'),
			  value: ctx.uci().get('e5-infoscreen', 'main', 'clock_seconds') == '1' },
			{ id: 'version', type: 'info', label: L('镜像版本', 'Image'), value: ctx.read_trim('/etc/e5/image-version') ?? '--' },
			{ id: 'built', type: 'info', label: L('构建时间', 'Built'), value: build_time() ?? '--' },
			{ id: 'screen_version', type: 'info', label: L('信息屏版本', 'Info screen'), value: u.cur },
			{ id: 'update_check', type: 'action', label: L('检查更新', 'Check for an update'), note: u.note },
			u.newer && u.latest ? { id: 'update_apply', type: 'action', confirm: true,
			  label: L(`更新到 ${u.latest.version}`, `Update to ${u.latest.version}`),
			  note: u.latest.notes ?? L('只更新信息屏，设置和已装应用保留', 'The screen only; settings and apps stay') } : null,
			u.backup && !u.busy ? { id: 'update_rollback', type: 'action', confirm: true,
			  label: L('回退信息屏', 'Roll the screen back'),
			  note: L('回到上一次更新之前的版本', 'Back to the version before the last update') } : null,
			{ id: 'traffic_clear', type: 'category', category:'traffic_clear', label: L('清空流量记录', 'Clear traffic records'),
			  note: L('选择 SIM 卡，与网页共用流量记录','Choose a SIM; history is shared with the web dashboard') },
			{ id: 'next_boot', type: 'info', label: L('下次重启进入', 'Next reboot boots'),
			  value: next ? next.label : '--' },
			trial_image()
			? { id: 'default_boot', type: 'info', label: L('默认启动', 'Default boot'), value: L('Android', 'Android'),
			    note: L('试用镜像不能设为默认启动', 'A trial image is never the default boot') }
			: { id: 'default_boot', type: 'choice', label: L('默认启动', 'Default boot'), value: default_boot(),
			    options: [ { value: 'linux', label: L('Linux', 'Linux') }, { value: 'android', label: L('Android', 'Android') } ],
			    confirm: true, reload: true,
			    note: L('Linux：每次开机后都回到 Linux；Android：下次重启起进入 Android',
			            'Linux: every reboot comes back to Linux; Android: reboots go to Android') },
			{ id: 'reboot', type: 'action', label: L('重启', 'Reboot'), confirm: true,
			  note: next ? L(`重启后进入 ${next.label.zh}`, `Boots ${next.label.en}`) : null },
			{ id: 'poweroff', type: 'action', label: L('关机', 'Power off'), confirm: true,
			  note: L('插着 USB 时可能会进入充电模式', 'With USB plugged in it may start in charging mode') },
			{ id: 'android_once', type: 'action', label: L('切换到 Android', 'Switch to Android'), confirm: true,
			  note: L('设为默认启动系统并重启','Set as default and reboot') }
		], (i) => i != null);
	},
	set: function(id, value) {
		if (id == 'timezone') {
			let z = null;
			for (let e in ZONES) if (e[0] == value) z = e;
			let sec = system_section();
			if (!z || !sec) return 'unknown time zone';
			let c = ctx.uci();
			c.set('system', sec, 'zonename', z[0]);
			c.set('system', sec, 'timezone', z[1]);
			c.commit('system');
			// /etc/TZ for the system; the screen's WebKit reads TZ at its start
			ctx.run('/etc/init.d/system reload >/dev/null 2>&1');
			ctx.run('(sleep 2; /etc/init.d/e5-infoscreen restart) >/dev/null 2>&1 &');
			return null;
		}
		if (id == 'clock_seconds') {
			let c = ctx.uci();
			c.set('e5-infoscreen', 'main', 'clock_seconds', value ? '1' : '0');
			c.commit('e5-infoscreen');
			return null;
		}
		if (id == 'traffic_clear') {
			return 'Choose a SIM in Clear traffic records';
		}
		if (id == 'default_boot') {
			if (value != 'linux' && value != 'android') return 'linux or android';
			if (trial_image()) return 'a trial image is never the default boot';
			return ctx.run(`e5-next-boot ${value} >/dev/null 2>&1`) == 0 ? null : 'e5-next-boot failed';
		}
		if (id == 'update_check') {
			return UPDATES.start('check');
		}
		if (id == 'update_apply' || id == 'update_rollback') {
			return UPDATES.start(id == 'update_apply' ? 'apply' : 'rollback');
		}
		if (id == 'reboot') { ctx.run('(sleep 2; reboot) >/dev/null 2>&1 &'); return null; }
		if (id == 'poweroff') { ctx.run('(sleep 2; poweroff) >/dev/null 2>&1 &'); return null; }
		// (booting Debian is e5-os on the command line: e5-os debian --once)
		if (id == 'android_once') {
            if (ctx.run('e5-next-boot android >/dev/null 2>&1') != 0) return 'Cannot select Android';
            ctx.run('(sleep 2; reboot) >/dev/null 2>&1 &');return null;
        }
		return 'no such setting';
	}
};

const usb_cat = {
	id: 'usb', label: L('USB', 'USB'),
	items: function() {
		let u = ctx.usb_status(), r = u.reset;
		let s = ctx.sh_json('/usr/libexec/unisoc-modem/device-usb get') ?? {};
		let roles = { auto:L('自动识别','Automatic'), host:L('主机 · OTG','Host · OTG'), device:L('设备模式','Device mode'), none:L('未连接','Disconnected') };
		let diagnosis = ctx.network_check_status();
		let labels = {
			no_controller:L('USB 控制器缺失','USB controller missing'),
			usb_not_enumerated:L('电脑尚未识别 USB','USB not enumerated by computer'),
			gadget_unbound:L('USB 设备尚未绑定','USB gadget not bound'),
			usb_interface_missing:L('USB 网卡缺失','USB network interface missing'),
			lan_missing:L('LAN 网桥缺失','LAN bridge missing'),
			usb_not_bridged:L('USB 未加入 LAN','USB not attached to LAN'),
			lan_no_ipv4:L('LAN 没有 IPv4 地址','LAN has no IPv4 address'),
			dhcp_not_running:L('DHCP 服务未运行','DHCP server not running'),
			wifi_not_running:L('热点尚未运行','Hotspot not running'),
			wifi_firmware_missing:L('Wi-Fi 固件缺失','Wi-Fi firmware missing'),
			regulatory_missing:L('无线管制数据库缺失','Regulatory database missing')
		};
		let checks = map(diagnosis?.checks ?? [], code => labels[code] ?? L(code,code));
		let hardware_errors = filter(split(diagnosis?.details?.kernel_log ?? '', '\n'), line=>match(lc(line), /(failed|error|not found|timeout|wrong nth|power on wcn)/));
		return [
			{ id:'usb_role_state', type:'info', label:L('当前角色','Current role'), busy:!!s.pending,
			  value:roles[s.role ?? 'none'], note:s.last_error || (s.pending ? L('正在切换…','Switching…') : null) },
			{ id:'usb_role', type:s.host_supported ? 'choice' : 'info', label:L('USB 角色','USB role'),
			  value:s.policy ?? 'auto', confirm:true, reload:true,
			  options:map(['auto','device','host'], value=>({ value, label:roles[value] })),
			  note:L('切换可能中断 USB 网络；自动模式按接入设备识别','Switching can interrupt USB networking; automatic mode follows the connected device') },
			{ id:'usb_host_boot', type:'toggle', label:L('开机启用主机模式','Start in host mode'), value:!!s.role_auto, confirm:true, reload:true,
			  note:L('开启会切到主机策略；关闭恢复自动识别','Enabling selects host mode; disabling restores automatic detection') },
			{ id:'usb_net_current', type:'info', label:L('当前共享协议','Current sharing protocol'), value:uc(s.net_current || 'ncm'),
			  note:s.net_boot?.error || L('主机模式下不使用共享协议','Sharing protocol is unused in host mode') },
			{ id:'usb_net_mode', type:s.net_available ? 'choice' : 'info', label:L('USB 共享协议','USB sharing protocol'), value:s.net_mode ?? 'ncm', reload:true,
			  options:map(s.net_supported ?? ['ncm'], value=>({value,label:uc(value)})),
			  note:L('下次重启生效；ECM 主要用于 Linux/macOS','Applies at next boot; ECM is mainly for Linux/macOS') },
			{ id:'usb_net_scope', type:'choice', label:L('生效期限','Apply for'), value:s.net_scope ?? 'permanent', reload:true,
			  options:[{value:'permanent',label:L('永久','Every boot')},{value:'once',label:L('仅下次重启','Next boot only')}] },
			{ id:'usb_net_auto', type:'toggle', label:L('启用所选协议','Use selected protocol'), value:!!s.net_auto, reload:true,
			  note:L('关闭后下次启动使用默认 NCM','When off, the next boot uses NCM') },
			{ id:'usb_lan_auto', type:'toggle', label:L('USB 网卡自动加入 LAN','Add USB Ethernet to LAN'), value:!!s.lan_auto, reload:true },
			{ id: 'check', type: 'action', label:L('一键检查连接','Check connections'), reload:true,
			  note:L('检查 USB、热点、网桥和 DHCP 并保存报告，不改变网络配置','Check USB, Wi-Fi, LAN and DHCP; save a report without changing network settings') },
			{ id: 'diagnosis', type:'info', label:L('检查结论','Check result'),
			  value:diagnosis ? length(checks) ? L(join('；',map(checks,l=>l.zh)),join('; ',map(checks,l=>l.en))) : L('未发现异常','No issue detected') : '--',
			  note:diagnosis?.report ?? null },
			{ id: 'wireless_error', type:'info', label:L('热点原始报错','Wireless error'),
			  value:join('; ',map(type(diagnosis?.details?.native_errors)=='array' ? diagnosis.details.native_errors : [], e=>type(e)=='object' ? e.code ?? e.message ?? sprintf('%J',e) : `${e}`)) || '--',
			  note:L('无法联网时可拍下本页的检查结论和报错','If networking is unavailable, photograph the check result and error on this page') },
			{ id:'hardware_error', type:'info', label:L('硬件原始报错','Hardware error'), value:length(hardware_errors) ? hardware_errors[length(hardware_errors)-1] : '--' },
			{ id: 'controller', type: 'info', label: L('控制器状态', 'Controller state'), value: u.state ?? '--' },
			{ id: 'host_address', type: 'info', label: L('电脑地址', 'Computer address'), value: u.ip ?? L('尚未获取地址', 'No address yet') },
			{ id: 'reset_status', type: 'info', label: L('USB 重置结果', 'USB reset status'),
			  busy: r.busy,
			  value: r.busy ? L('正在修复…', 'Recovering…') : r.state == 'done' ? L('已重新枚举', 'Re-enumerated') : r.state == 'failed' ? L('修复失败', 'Recovery failed') : '--',
			  note: r.message ? `${r.stage ?? ''}: ${r.message}` : null },
			{ id: 'reset', type: 'action', label: L('重置 USB 连接', 'Reset USB connection'), confirm: true, reload: true,
			  note: L('电脑的 USB 网络会短暂断开；重新识别设备并恢复 LAN/DHCP，保留网络设置', 'USB networking disconnects briefly; re-enumerate and restore LAN/DHCP while keeping network settings') }
		];
	},
	set: function(id, value) {
		if (id == 'reset') return ctx.usb_reset_start();
		if (id == 'check') return ctx.network_check();
		let s = ctx.sh_json('/usr/libexec/unisoc-modem/device-usb get');
		if (!s?.ok) return 'USB status unavailable';
		let args;
		if (id == 'usb_role' && index(['auto','host','device'], value) >= 0)
			args = `set-role ${value} ${value == 'host' && s.role_auto ? '1' : '0'}`;
		else if (id == 'usb_host_boot' && type(value) == 'bool') args = `set-role ${value ? 'host 1' : 'auto 0'}`;
		else if (id == 'usb_lan_auto' && type(value) == 'bool') args = `set-lan-auto ${value ? '1' : '0'}`;
		else if (index(['usb_net_mode','usb_net_scope','usb_net_auto'], id) >= 0) {
			let mode = id == 'usb_net_mode' ? value : s.net_mode;
			let scope = id == 'usb_net_scope' ? value : s.net_scope;
			if (index(['ncm','ecm','rndis'], mode) < 0 || index(['once','permanent'], scope) < 0 ||
			    (id == 'usb_net_auto' && type(value) != 'bool')) return 'Invalid USB setting';
			args = `set-net ${mode} ${scope} ${(id == 'usb_net_auto' ? value : s.net_auto) ? '1' : '0'}`;
		} else return 'Invalid USB setting';
		let result = ctx.sh_json('/usr/libexec/unisoc-modem/device-usb ' + args);
		return result?.ok ? null : result?.error ?? 'USB operation failed';
	}
};

/* ---------- about ---------- */

const about = {
	id: 'about', label: L('关于', 'About'),
	items: function() {
		return [
			{ id: 'name', type: 'info', label: L('信息屏', 'Info screen'), value: 'e5-infoscreen' },
			{ id: 'maintainer', type: 'info', label: L('维护者', 'Maintainer'), value: 'Enceka <enceka@yeah.net>' },
			{ id: 'copyright', type: 'info', label: L('版权', 'Copyright'), value: '© 2026 Enceka' },
			{ id: 'license', type: 'info', label: L('许可', 'License'), value: 'MIT' },
			{ id: 'donate', type: 'image', label: L('赞赏', 'Donate'), src: '/donate.jpg',
			  caption: L('觉得好用，可以微信扫码赞赏作者', 'If it is of use to you: the author\'s WeChat tip code') },
			{ id: 'disclaimer', type: 'info', label: L('免责声明', 'Disclaimer'),
			  value: L('按“原样”提供，不作任何担保', 'Provided "as is", without warranty'),
			  note: L('非官方软件，与荣悦及设备、芯片厂商无关。修改网络模式、频段、AT 指令和充电设置可能导致断网、设备异常或失去保修，风险由使用者自行承担。',
			          'Unofficial software, not affiliated with Rongyue or the device and chip makers.  Changing the network mode, bands, AT commands or charging can cut the connection, upset the device or void its warranty; at your own risk.') }
		];
	},
	set: function(id, value) {
		return 'read-only';
	}
};

// (the devices category is its own view: /api/devices)
// (the AT page is its own view as well: /api/at, /api/at/presets)
return [ network, {id:'apn',parent:'network',label:L('接入点 APN','Access points (APN)'),view:'apn'},
         { id: 'at', label: L('AT 指令', 'AT commands'), view: 'at' },
         { id: 'devices', label: L('设备管理', 'Devices'), view: 'devices' },
         { id: 'appmgr', label: L('应用管理', 'Apps'), view: 'apps' },
         ...(ctx.run('command -v bluetoothctl >/dev/null 2>&1') == 0
             ? [ { id: 'bluetooth', label: L('蓝牙', 'Bluetooth'), view: 'bluetooth' } ] : []),
         charge, notify, ...(has_sound ? [ sound ] : []), screen, usb_cat, system_cat, traffic_records, about ];

};
