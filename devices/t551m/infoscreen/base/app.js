'use strict';
// The E5 info screen: six pages (overview, signal, SMS, hotspot, device,
// advanced) fed
// by /api/status, driven by touch (tap, swipe) and the keypad (arrows,
// confirm, back, digits, power).  The backlight goes off after the configured
// idle time; only the power key wakes the dark screen. A new
// SMS (e5-sms-notify's unread list) lights the screen and opens the message.
// Power, then * within 2 s, locks the keys: the screen stays dark until the
// same again (keyLock).  The first start after an install shows the 赞赏码
// once (picOpen); after that it is under 高级 -> 关于.

const I18N = {
	zh: {
		sms_delete_note:'删除本地记录，与网页同步；SIM 原件保留。',
		traffic_view:'查看流量',traffic_data_sim:'跟随数据卡',traffic_unavailable:'流量统计暂不可用',traffic_history:'网卡离线 · 历史记录仍可查看',traffic_clock:'系统时间尚未同步',traffic_storage:'流量记录保存失败',traffic_session_note:'网卡累计独立计数，清空历史不会重置网卡',traffic_cleared:'流量记录已清空',
		call_volume: '通话音量',
		overview: '概览', signal: '信号', sms: '短信', hotspot: '热点', device: '设备',
		back: '返回', delete: '删除', delete_confirm: '再按一次删除', deleted: '已删除',
		no_sms: '没有短信', unknown_sender: '未知号码', new_sms: '新短信', unread_sms: '未读短信',
		advanced: '高级', adv_info: '高级信息', model: '型号',
		traffic: '流量', today: '今日', this_month: '本月', last_days: '最近 7 天', counting_since: '开始统计于',
		notifications: '应用通知', notification_open: '查看', notification_later: '稍后', settings: '高级', apps: '应用', no_apps: '没有安装应用', press_again: '再按一次确认', unlocked: '已解锁', pic_close: '按任意键或点一下关闭', app_store: '应用商店', store_install: '安装', store_update: '更新到', store_have: '已安装', store_backend: '含后台（以 root 运行）', store_refresh: '刷新', store_empty: '商店里还没有应用', store_fail: '无法获取应用商店', store_installing: '正在安装…', store_note: '应用来自 github.com/Enceka/infoscreen-plugins，经检查后发布；含后台的应用以 root 运行，只装你信任的', usb_none: '未连接', usb_charger: '仅充电（充电器）', usb_host: '已接电脑，未识别', usb_enumerated: '已连接电脑', usb_lease: '电脑已获取地址', usb_online: '电脑正通过 E5 上网', donate_note: '关闭后不再弹出，以后如有意愿，可以在“高级 → 关于 → 赞赏”里赞赏',
		apply: '应用', clear: '全部取消', save: '保存', saved: '已保存', failed: '失败',
		network_deferred: '设置已保存，模组未就绪或射频已关闭，已跳过重连', network_reconnect_failed: '设置已接受，但重连失败', network_refresh_pending: '设置已应用，请稍后刷新状态',
		online: '在线', offline: '离线', blocked: '已禁止上网', block: '禁止上网', unblock: '允许上网',
		kick: '踢下 Wi-Fi', kicked: '已踢下线', mac: 'MAC', via: '连接', no_devices: '没有设备',
		loading: '读取中…', app_settings: '应用设置', app_config: '设置', current_voltage: '电流 / 电压',
		charge_paused: '已暂停充电', limit: '上限', wan: '外网', lan: '内网',
		at_running: '执行中…', at_again: '再执行一次', at_note: '任意指令可通过 SSH 的 e5-at 或插件的 /api/at 发送', at_risky: '该指令可能让基带直到重启前不再响应 AT 或识别不到 SIM 卡', system: '系统', image: '镜像版本', kernel: '内核',
		storage: '存储', temperature: '温度', baseband: '基带', modes: '网络模式',
		temperatures: '温度详情', cpu_temp: 'CPU', gpu_temp: 'GPU', modem_temp: '基带',
		board_temp: '主板', battery_temp: '电池', pa_temp: '射频功放', estimated: '估算', unverified: '待核实',
		soc_temp: 'SoC', lte_temp: '4G 基带', nr_temp: '5G 基带', mm_temp: '多媒体', show_more: '查看更多', show_less: '收起',
		update_found: '信息屏有更新', update_now: '立即更新', update_later: '推迟更新',
		update_logs: '查看更新日志', update_hide_logs: '收起更新日志', update_scope: '只更新信息屏，设置和应用保留',
		update_later_hint: '推迟后 24 小时再提醒', update_busy: '正在更新…', update_retry: '重试更新', update_deferred: '已推迟更新',
		locks: '锁定', lte_bands: 'LTE 频段', nr_bands: 'NR 频段', cell_lock: '锁小区',
		not_locked: '未锁定', slot: '卡槽', operator: '运营商', registration: '注册',
		number: '本机号码', show_ids: '显示识别码', hide_ids: '隐藏识别码',
		allowed: '允许', nsa_only: '仅 NSA', card: '卡', home: '本地网', roaming_reg: '漫游',
		idle_reg: '未注册', denied: '被拒绝',
		since_boot: '本次开机', network: '网络', clients: '在线设备', battery: '电池',
		bandwidth: '带宽', neighbours: '邻区', uptime: '开机时长', wan_uptime: '联网时长',
		load: '负载', memory: '内存', subscribed: '签约速率', volume: '音量', muted: '静音', paused_short: '暂停', app_builtin: '内置', app_user: '已安装', app_version: '版本', app_kind: '来源', app_desc: '说明', app_open: '打开', app_remove: '卸载', app_removed: '已卸载', app_builtin_note: '内置应用卸载后，下次更新系统镜像时会回来', app_install_note: '安装新应用：在电脑浏览器打开 http://192.168.9.1 → 服务 → 信息屏应用，上传应用包（.tar.gz 或 .zip）',
		bluetooth: '蓝牙', bt_none: '没有蓝牙适配器', bt_autostart: '开机启动', bt_scan: '搜索设备', bt_scanning: '正在搜索…', bt_name: '本机名称', bt_mine: '我的设备', bt_found: '附近的设备', bt_none_found: '没有找到设备，点“搜索设备”', bt_note: '耳机或音箱请先进入配对模式；连接后声音从蓝牙播放', bt_state: '状态', bt_connect: '连接', bt_pair: '配对并连接', bt_disconnect: '断开', bt_remove: '忘记此设备', bt_connected: '已连接', bt_paired: '已配对', bt_pairing: '配对中…', bt_connecting: '连接中…', bt_failed: '连接失败', bt_notfound: '没有找到设备：请让它进入配对模式后再试', bt_forgot: '设备已忘记配对：请让它进入配对模式后再连接', bt_noanswer: '设备没有响应：请打开耳机盒、戴上耳机，并确认它没有连着手机', brightness: '亮度', reconnect: '重新连接网络',
		show_key: '显示密码', hide_key: '隐藏密码', hs_off: '热点已关闭', hs_down: '热点未启动', on: '开', off: '关',
		connected: '已连接', connecting: '连接中', disconnected: '未连接',
		no_modem: '无模组', no_sim: '无 SIM 卡', searching: '搜索网络',
		charging: '充电中', full: '已充满', discharging: '使用电池', not_charging: '未充电',
		none: '无', wifi: 'Wi-Fi', usb: 'USB', unnamed: '未命名',
		hotspot_on: '已开启', hotspot_off: '已关闭', hotspot_starting: '启动中', hotspot_failed: '未启动', usb_resetting: 'USB 修复已启动',
		reconnecting: '正在重新连接…', turning_on: '正在开启热点…', turning_off: '正在关闭热点…',
		roaming: '漫游', devices: '台',
		excellent: '极好', good: '好', fair: '一般', weak: '弱', poor: '差'
	},
	en: {
		sms_delete_note:'Deletes the shared local record; keeps the SIM copy.',
		traffic_view:'View usage',traffic_data_sim:'Follow data SIM',traffic_unavailable:'Usage unavailable',traffic_history:'Interface offline · History is available',traffic_clock:'Clock not synchronized',traffic_storage:'Could not save usage',traffic_session_note:'Live interface counters are separate from usage history',traffic_cleared:'Traffic history cleared',
		call_volume: 'Call volume',
		overview: 'Overview', signal: 'Signal', sms: 'Messages', hotspot: 'Hotspot', device: 'Device',
		back: 'Back', delete: 'Delete', delete_confirm: 'Press again to delete', deleted: 'Deleted',
		no_sms: 'No messages', unknown_sender: 'Unknown', new_sms: 'New message', unread_sms: 'Unread messages',
		advanced: 'Advanced', adv_info: 'Details', model: 'Model',
		traffic: 'Traffic', today: 'Today', this_month: 'This month', last_days: 'Last 7 days', counting_since: 'Counting since',
		notifications: 'App notification', notification_open: 'Open', notification_later: 'Later', settings: 'Settings', apps: 'Apps', no_apps: 'No apps installed', press_again: 'Press again', unlocked: 'Unlocked', pic_close: 'Any key or a tap closes this', app_store: 'App store', store_install: 'Install', store_update: 'Update to', store_have: 'Installed', store_backend: 'with a backend (runs as root)', store_refresh: 'Refresh', store_empty: 'No apps in the store yet', store_fail: 'Cannot reach the app store', store_installing: 'Installing…', store_note: 'Apps from github.com/Enceka/infoscreen-plugins, checked before they are published; an app with a backend runs as root: install what you trust', usb_none: 'Not connected', usb_charger: 'Charging only (a charger)', usb_host: 'A computer, not enumerated', usb_enumerated: 'Connected to a computer', usb_lease: 'The computer has an address', usb_online: 'The computer is online through the E5', donate_note: 'This is not shown again; it stays under Settings -> About -> Donate',
		apply: 'Apply', clear: 'Clear all', save: 'Save', saved: 'Saved', failed: 'Failed',
		network_deferred: 'Settings saved; modem not ready or radio off, reconnect skipped', network_reconnect_failed: 'Settings accepted, but reconnect failed', network_refresh_pending: 'Settings applied; refresh status later',
		online: 'Online', offline: 'Offline', blocked: 'Blocked', block: 'Block internet', unblock: 'Allow internet',
		kick: 'Kick off Wi-Fi', kicked: 'Kicked', mac: 'MAC', via: 'Via', no_devices: 'No devices',
		loading: 'Loading…', app_settings: 'App settings', app_config: 'Settings', current_voltage: 'Current / voltage',
		charge_paused: 'Charging paused', limit: 'limit', wan: 'WAN', lan: 'LAN',
		at_running: 'Running…', at_again: 'Run again', at_note: 'Any command: e5-at over SSH, or /api/at from a plugin', at_risky: 'This command may leave the baseband unresponsive to AT or unaware of the SIM until a reboot', system: 'System', image: 'Image', kernel: 'Kernel',
		storage: 'Storage', temperature: 'Temperature', baseband: 'Baseband', modes: 'Modes',
		temperatures: 'Temperatures', cpu_temp: 'CPU', gpu_temp: 'GPU', modem_temp: 'Modem',
		board_temp: 'Board', battery_temp: 'Battery', pa_temp: 'RF PA', estimated: 'Estimated', unverified: 'Unverified',
		soc_temp: 'SoC', lte_temp: '4G modem', nr_temp: '5G modem', mm_temp: 'Media', show_more: 'Show more', show_less: 'Show less',
		update_found: 'Info screen update', update_now: 'Update now', update_later: 'Later',
		update_logs: 'Release notes', update_hide_logs: 'Hide release notes', update_scope: 'Settings and apps stay; the screen only',
		update_later_hint: 'Remind me in 24 hours', update_busy: 'Updating…', update_retry: 'Retry update', update_deferred: 'Update postponed',
		locks: 'Locks', lte_bands: 'LTE bands', nr_bands: 'NR bands', cell_lock: 'Cell lock',
		not_locked: 'Not locked', slot: 'Slot', operator: 'Operator', registration: 'Registration',
		number: 'Number', show_ids: 'Show identifiers', hide_ids: 'Hide identifiers',
		allowed: 'Allowed', nsa_only: 'NSA only', card: 'SIM ', home: 'Home', roaming_reg: 'Roaming',
		idle_reg: 'Not registered', denied: 'Denied',
		since_boot: 'Since boot', network: 'Network', clients: 'Clients', battery: 'Battery',
		bandwidth: 'Bandwidth', neighbours: 'Neighbours', uptime: 'Uptime', wan_uptime: 'Online',
		load: 'Load', memory: 'Memory', subscribed: 'Subscribed rate', volume: 'Volume', muted: 'Muted', paused_short: 'paused', app_builtin: 'built in', app_user: 'installed', app_version: 'Version', app_kind: 'Source', app_desc: 'About', app_open: 'Open', app_remove: 'Uninstall', app_removed: 'Uninstalled', app_builtin_note: 'A built-in app comes back with the next image update', app_install_note: 'To install an app: open http://192.168.9.1 in a browser -> Services -> Info screen apps, and upload its package (.tar.gz or .zip)',
		bluetooth: 'Bluetooth', bt_none: 'No Bluetooth adapter', bt_autostart: 'On at boot', bt_scan: 'Search', bt_scanning: 'Searching…', bt_name: 'Name', bt_mine: 'My devices', bt_found: 'Nearby', bt_none_found: 'Nothing found; press Search', bt_note: 'Put headphones or a speaker in pairing mode first; once connected the sound plays there', bt_state: 'State', bt_connect: 'Connect', bt_pair: 'Pair and connect', bt_disconnect: 'Disconnect', bt_remove: 'Forget', bt_connected: 'Connected', bt_paired: 'Paired', bt_pairing: 'Pairing…', bt_connecting: 'Connecting…', bt_failed: 'Failed', bt_notfound: 'Not found: put it in pairing mode and try again', bt_forgot: 'The device forgot the pairing: put it in pairing mode and connect again', bt_noanswer: 'No answer: take the earbuds out of the case and make sure no phone is connected to them', brightness: 'Brightness', reconnect: 'Reconnect',
		show_key: 'Show key', hide_key: 'Hide key', hs_off: 'Hotspot off', hs_down: 'Hotspot not up', on: 'On', off: 'Off',
		connected: 'Connected', connecting: 'Connecting', disconnected: 'Offline',
		no_modem: 'No modem', no_sim: 'No SIM', searching: 'Searching',
		charging: 'Charging', full: 'Full', discharging: 'On battery', not_charging: 'Not charging',
		none: 'None', wifi: 'Wi-Fi', usb: 'USB', unnamed: 'unnamed',
		hotspot_on: 'On', hotspot_off: 'Off', hotspot_starting: 'Starting', hotspot_failed: 'Not running', usb_resetting: 'USB recovery started',
		reconnecting: 'Reconnecting…', turning_on: 'Turning the hotspot on…', turning_off: 'Turning the hotspot off…',
		roaming: 'Roaming', devices: '',
		excellent: 'Excellent', good: 'Good', fair: 'Fair', weak: 'Weak', poor: 'Poor'
	}
};

const POLL_AWAKE = 2000;
const POLL_BLANK = 5000;     // (still quick to notice a new SMS)
const KEY_LOG_MAX = 200;
const TEMP_FIELDS = ['cpu', 'gpu', 'soc', 'lte', 'nr', 'mm', 'board', 'pa', 'battery'];
let extraTemps = false;
let updateState = null;
let updateExpanded = false;
let updateRequest = false;
let updateLastPoll = -Infinity;

let lang = 'zh';
let page = 0;
let last = null;           // the last /api/status
let blank = false;
let locked = false;                 // the key lock (keyLock)
let picShown = false;               // a picture over everything (picOpen)
let idleTimer = null;
let pollTimer = null;
let keyLogged = 0;
let showKey = false;
let wifiPending = null;    // the state asked for, until the status shows it
let qrFor = null;          // the SSID the QR code was made for
let brightness = 120;
let smsList = [];          // the last /api/sms
let smsOpen = null;        // the id of the message on screen
let smsUnread = null;      // the unread ids at the last poll
let smsReading = false;
let notificationList = [], notificationSeen = new Set(), notificationDismissed = new Set(), notificationCurrent = null;
let smsArmed = null;       // the delete button's second-press timer

// the pages, in order (the digit keys count from 1)
const P = { overview: 0, signal: 1, traffic: 2, sms: 3, hotspot: 4, device: 5, adv_info: 6, settings: 7, apps: 8 };
let adv = null;            // the last /api/advanced
let advTimer = null;
let showIds = false;

const $ = (id) => document.getElementById(id);
// handlers by element id: an element this page does not have (an index.html
// older than this script) is logged, not a TypeError that stops the script
function on(id, ev, fn) {
	const el = $(id);
	if (el) el.addEventListener(ev, fn);
	else console.log('no element #' + id);
}
const pages = Array.from(document.querySelectorAll('.page'));
const t = (k) => (I18N[lang] && I18N[lang][k]) ?? I18N.zh[k] ?? k;

function applyLang() {
	document.documentElement.lang = lang;
	for (const el of document.querySelectorAll('[data-t]'))
		el.textContent = t(el.dataset.t);
	$('foot-title').textContent = t(pages[page].dataset.title);
}

/* ---------- formatting ---------- */

function fmtBytes(n) {
	if (n == null) return ['--', ''];
	const u = ['B', 'KB', 'MB', 'GB', 'TB'];
	let i = 0;
	while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
	return [n >= 100 || i == 0 ? n.toFixed(0) : n.toFixed(1), u[i]];
}

function fmtRate(n) {
	const [v, u] = fmtBytes(n);
	return [v, u ? u + '/s' : ''];
}

function fmtDuration(s) {
	if (s == null) return '--';
	const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
	if (lang == 'zh')
		return (d ? d + '天' : '') + (d || h ? h + '小时' : '') + m + '分';
	return (d ? d + 'd ' : '') + (d || h ? h + 'h ' : '') + m + 'm';
}

function techName(tech) {
	return { '5gnr': '5G', lte: '4G', umts: '3G', hsdpa: '3G', hsupa: '3G', hspa: '3G',
		'hspa-plus': '3G', gsm: '2G', edge: '2G', gprs: '2G' }[tech] ?? (tech ? tech.toUpperCase() : '--');
}

// quality of a measurement, 0..1 and a word, from the usual thresholds
function grade(kind, v) {
	if (v == null) return null;
	const T = {
		rsrp: [-80, -90, -100, -110, -140, -44],
		rsrq: [-10, -12, -15, -18, -25, -3],
		sinr: [20, 13, 5, 0, -10, 30]
	}[kind];
	const [ex, gd, fr, wk, min, max] = T;
	const frac = Math.max(0, Math.min(1, (v - min) / (max - min)));
	const word = v >= ex ? 'excellent' : v >= gd ? 'good' : v >= fr ? 'fair' : v >= wk ? 'weak' : 'poor';
	return { frac, word };
}

const GRADE_COLOR = { excellent: 'var(--good)', good: 'var(--good)', fair: 'var(--fair)', weak: 'var(--poor)', poor: 'var(--poor)' };

function setText(id, s) {
	const el = $(id);
	if (el && el.textContent !== s) el.textContent = s;
}

function setHTML(id, html) {
	const el = $(id);
	if (el && el.innerHTML !== html) el.innerHTML = html;
}

function esc(s) {
	return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------- rendering ---------- */

function wanWord(st) {
	const m = st.modem, w = st.wan;
	if (!m.present) return [t('no_modem'), 'bad'];
	if (!m.sim) return [t('no_sim'), 'bad'];
	if (w.up) return [t('connected'), 'ok'];
	if (w.pending || m.state == 'connecting') return [t('connecting'), 'warn'];
	if (m.registration == 'searching') return [t('searching'), 'warn'];
	return [t('disconnected'), 'bad'];
}

function renderBar(st) {
	const m = st.modem;
	setText('bar-sim', m.sim_card == null ? '' : String(m.sim_card + 1));
	setText('bar-op', m.operator ?? (!m.present ? t('no_modem') : !m.sim ? t('no_sim') : t('searching')));
	const tech = $('bar-tech');
	setText('bar-tech', m.tech ? techName(m.tech) : '--');
	tech.classList.toggle('off', !st.wan.up);

	const inserted = (st.sims || []).filter(s => s.present === true);
	const single = inserted.length === 1 ? inserted[0] : null;
	const q = single ? (single.stale || single.error || single.signal?.rsrp == null ? 0 : Math.max(0, Math.min(100, (single.signal.rsrp + 120) * 2.5))) : (m.quality ?? 0);
	const n = q >= 75 ? 4 : q >= 50 ? 3 : q >= 25 ? 2 : q > 0 ? 1 : 0;
	$('bar-bars').querySelectorAll('i').forEach((el, i) => el.classList.toggle('on', i < n));

	const b = st.battery, bat = $('bar-bat');
	const cap = b.capacity ?? 0;
	bat.querySelector('b').style.width = Math.round(cap / 100 * 17) + 'px';
	bat.classList.toggle('low', cap <= 15 && chargeState(b) != 'charging');
	bat.classList.toggle('charging', chargeState(b) == 'charging');
	setText('bar-batpct', b.capacity == null ? '--' : cap + '%');
	tickClock();
	renderSmsIndicator(st.sms?.unread);
	setText('bar-notifications', notificationList.length ? '• ' + notificationList.length : '');
}

// What the battery does, from the current as much as from the status: the
// charger-manager reports "Not charging" whenever it has stopped charging --
// a JEITA temperature zone, a health check, the charge limit -- while the
// AW322xx chip may go on charging (it writes its CE bit only from its own
// flag), and "Full" only at 100 %.  So "Not charging" is not "full", and
// current into the battery is charging whatever the status says.
function chargeState(b) {
	if (!b.online)
		return 'discharging';
	if (b.status == 'Full' || (b.capacity ?? 0) >= 100)
		return 'full';
	if (b.status == 'Charging' || (b.current_ma ?? 0) > 20)
		return 'charging';
	return 'not_charging';
}

function batteryText(b) {
	if (b.capacity == null) return '--';
	// stopped by the charge limit: say so -- the gauge itself reads "Full" at
	// 100 % or "Not charging", neither of which tells why
	if (b.paused && b.online)
		return `${b.capacity}% · ${t('paused_short')}${b.limit != null ? ` · ${t('limit')} ${b.limit}%` : ''}`;
	return b.capacity + '%' + ' · ' + t(chargeState(b));
}

function renderOverview(st) {
	const [rx, rxu] = fmtRate(st.traffic.rx_rate);
	const [tx, txu] = fmtRate(st.traffic.tx_rate);
	setText('ov-rx', rx); setText('ov-rx-u', rxu);
	setText('ov-tx', tx); setText('ov-tx-u', txu);
	const [rt, rtu] = fmtBytes(st.traffic.rx_total), [tt, ttu] = fmtBytes(st.traffic.tx_total);
	setText('ov-total', `↓ ${rt} ${rtu}  ↑ ${tt} ${ttu}`);

	const [word, cls] = wanWord(st);
	const fam = st.wan.up ? [st.wan.ipv4 ? 'IPv4' : null, st.wan.ipv6 ? 'IPv6' : null].filter(Boolean).join(' ') : '';
	setHTML('ov-wan', `<span class="${cls}">${esc(word)}</span>` + (st.modem.tech && st.wan.up ? ` · ${techName(st.modem.tech)}` : '') + (fam ? ` · ${fam}` : ''));

	const w = st.wifi;
	const ws = w.enabled ? (w.up ? t('hotspot_on') : t(w.state == 'failed' ? 'hotspot_failed' : 'hotspot_starting')) : t('hotspot_off');
	setHTML('ov-wifi', `<span class="${w.enabled && w.up ? 'ok' : w.enabled ? 'warn' : ''}">${esc(ws)}</span>` + (w.ssid ? ` · ${esc(w.ssid)}` : ''));

	const nw = st.clients.filter((c) => c.via == 'wifi').length, nu = st.clients.filter((c) => c.via == 'usb').length;
	setText('ov-clients', st.clients.length ? `${st.clients.length}${t('devices')}` + (nw ? ` · ${t('wifi')} ${nw}` : '') + (nu ? ` · ${t('usb')}` : '') : t('none'));
	const batteryTemp = st.system.temperatures?.battery;
	setText('ov-bat', batteryText(st.battery) + (batteryTemp == null ? '' : ` · ${batteryTemp.toFixed(1)}°C`));
	// + charging, - discharging (the fuel gauge's sign)
	const b = st.battery, ma = b.current_ma;
	// within ±20 mA it is the gauge's idle offset (on USB, not charging): no colour, no +
	const flow = ma == null ? 0 : ma >= 20 ? 1 : ma <= -20 ? -1 : 0;
	setHTML('ov-power', (ma == null ? '--' : `<span class="${flow > 0 ? 'ok' : flow < 0 ? 'warn' : ''}">${flow > 0 ? '+' : ''}${ma} mA</span>`) +
		(b.voltage_mv == null ? '' : ` · ${(b.voltage_mv / 1000).toFixed(2)} V`));

	const sy = st.system;
	usage('ov-mem', sy.mem_total == null ? null : sy.mem_total - sy.mem_available, sy.mem_total);
	usage('ov-disk', sy.disk_used, sy.disk_total);
	setHTML('ov-temps', temperatureSummary(sy.temperatures, TEMP_FIELDS.filter((name) => name != 'battery')));
}

function temperatureSummary(values, fields = TEMP_FIELDS) {
	const temps = values ?? {};
	return fields.map((name) =>
		`<div class="temperature"><span class="label">${esc(t(name + '_temp'))}</span>` +
		`<span class="value">${fmtTemp(temps[name])}</span></div>`).join('');
}

function fmtTemp(value) {
	return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} °C` : '--';
}

// "used / total · n%" and a bar: green, yellow from 75 %, red from 90 %
function usage(id, used, total) {
	const bar = $(id + '-bar');
	if (used == null || !total) { setText(id, '--'); if (bar) bar.style.width = '0'; return; }
	const pct = Math.min(100, Math.round(used / total * 100));
	const [u, uu] = fmtBytes(used), [tt, tu] = fmtBytes(total);
	setText(id, `${u} ${uu} / ${tt} ${tu} · ${pct}%`);
	if (bar) {
		bar.style.width = pct + '%';
		bar.style.background = pct >= 90 ? 'var(--poor)' : pct >= 75 ? 'var(--fair)' : 'var(--good)';
	}
}

function renderSignal(st) {
	const m = st.modem, c = m.cell;
	setText('sg-tech', m.radio_label || (m.tech ? techName(m.tech) : '--'));
	setText('sg-band', c?.band ?? '');
	setText('sg-op', [m.operator, m.registration == 'roaming' ? t('roaming') : null].filter(Boolean).join(' · ') || '--');
	const sig = m.signal ?? {};
	for (const [kind, v, unit] of [['rsrp', sig.rsrp, ' dBm'], ['sinr', sig.snr, ' dB'], ['rsrq', sig.rsrq, ' dB']]) {
		const g = grade(kind, v);
		setText('sg-' + kind, v == null ? '--' : `${v.toFixed(1)}${unit} · ${t(g.word)}`);
		const bar = $('sg-' + kind + '-bar');
		bar.style.width = g ? Math.round(g.frac * 100) + '%' : '0';
		bar.style.background = g ? GRADE_COLOR[g.word] : '';
	}
	setText('sg-pci', c?.pci == null ? '--' : String(c.pci));
	setText('sg-arfcn', c?.arfcn == null ? '--' : String(c.arfcn));
	setText('sg-bw', c?.bandwidth_mhz == null ? '--' : `${c.bandwidth_mhz} MHz`);
	setText('sg-nb', m.present ? String(m.neighbours ?? 0) : '--');
	// the network's aggregate maximum bit rate for the data context
	const q = m.qos;
	setText('sg-qos', q ? `↓${fmtKbps(q.dl_kbps)} ↑${fmtKbps(q.ul_kbps)} · ${q.nr ? '5QI' : 'QCI'} ${q.qci}` : '--');
}

function fmtKbps(k) {
	if (k >= 1000000) return +(k / 1000000).toFixed(1) + ' Gbps';
	if (k >= 1000) return +(k / 1000).toFixed(1) + ' Mbps';
	return k + ' kbps';
}

async function renderHotspot(st) {
	const w = st.wifi;
	setText('hs-ssid', w.ssid ?? '--');
	const on = wifiPending ?? w.enabled;
	const btn = $('hs-toggle');
	setText('hs-toggle', on ? t('on') : t('off'));
	btn.classList.toggle('on', on);
	if (wifiPending != null && wifiPending == w.enabled && (!w.enabled || w.up || w.state == 'failed'))
		wifiPending = null;

	$('hs-qr').classList.toggle('off', !(w.enabled && w.up));
	$('hs-qr').dataset.off = w.error || (w.enabled ? t('hs_down') : t('hs_off'));
	const qrKey = JSON.stringify([w.ssid, w.secured, w.hidden, w.qr_revision]);
	if (w.ssid && qrFor !== qrKey) {
		qrFor = qrKey;
		try {
			setHTML('hs-qr', await pageRead('/api/qr', P.hotspot, 'text'));
		} catch (e) { qrFor = null; }
	}

	setText('hs-count', `(${st.clients.length})`);
	setHTML('hs-list', st.clients.length ? st.clients.map((c) =>
		`<div class="client"><span>${esc(c.name ?? c.ip ?? c.mac ?? t('unnamed'))}</span>` +
		`<span class="via">${esc(c.ip ?? '')} · ${esc(t(c.via))}${c.signal != null ? ' ' + c.signal + ' dBm' : ''}</span></div>`
	).join('') : `<div class="sub">${esc(t('none'))}</div>`);
}

function usbDeviceName(d) {
	const name = d.name || 'USB';
	if (d.kind !== 'ethernet') return name;
	const label = lang == 'zh' ? 'USB 网卡' : 'USB Ethernet';
	return name === 'USB' ? label : `${label} · ${name}`;
}

// the USB row: what the link is, the host's address, its traffic while it uses the E5
function usbText(u) {
	if (u?.role == 'host') return (u.devices || []).map(usbDeviceName).join(' · ') || (lang == 'zh' ? 'OTG 主机，等待设备' : 'OTG host, waiting for device');
	if (!u) return '--';
	if (u.link == 'host') return lang == 'zh' ? 'USB 供电，未建立数据连接' : 'USB power, no data connection';
	let s = t('usb_' + u.link);
	if ((u.link == 'lease' || u.link == 'online') && u.ip) s += ` · ${u.ip}`;
	// (the host's down is what the E5 sends on usb0)
	if (u.link == 'online') s += ` · ↓${fmtRate(u.tx_rate ?? 0).join(' ')} ↑${fmtRate(u.rx_rate ?? 0).join(' ')}`;
	return s;
}

function renderDevice(st) {
	setText('dv-bat', batteryText(st.battery));
	setText('dv-up', fmtDuration(st.system.uptime));
	setText('dv-wanup', st.wan.up ? fmtDuration(st.wan.uptime) : '--');
	setText('dv-load', st.system.load == null ? '--' : st.system.load.toFixed(2));
	const used = st.system.mem_total - st.system.mem_available;
	const [u, uu] = fmtBytes(used), [tt, tu] = fmtBytes(st.system.mem_total);
	setText('dv-mem', `${u} ${uu} / ${tt} ${tu}`);
	setText('dv-usb', usbText(st.usb));
	setText('dv-lan', st.system.lan_ip);
	setText('dv-v4', st.wan.ipv4 ?? '--');
	setText('dv-v6', st.wan.ipv6_prefix ?? st.wan.ipv6 ?? '--');
	setText('dv-bl', String(Math.round(brightness / 255 * 100)) + '%');
}

function render(st) {
	renderBar(st);
	renderUpdateNotice();
	if (window.T551M?.isLocked() || appOpen) return;
	if (page == P.overview) renderOverview(st);
	else if (page == P.signal) renderSignal(st);
	else if (page == P.hotspot) renderHotspot(st);
	else if (page == P.device) renderDevice(st);
}

/* ---------- clock ---------- */

// a time in the device's time zone: the API's offset from UTC, not WebKit's
// zone (it has no zoneinfo on OpenWrt, so it would be UTC)
function localParts(ms) {
	const d = new Date((ms ?? Date.now()) + (last?.tz_offset ?? 0) * 1000);
	return { y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(),
	         h: d.getUTCHours(), mi: d.getUTCMinutes(), s: d.getUTCSeconds() };
}

// the status bar's clock ticks here, every second: the page has the device's
// time zone (the session passes TZ) and the time is NTP's
function tickClock() {
	const d = localParts(), p2 = (n) => String(n).padStart(2, '0');
	setText('bar-clock', `${p2(d.h)}:${p2(d.mi)}` + (last?.screen?.clock_seconds ? `:${p2(d.s)}` : ''));
}
setInterval(() => { if (!blank) tickClock(); }, 1000);

/* ---------- data ---------- */

const pageLoads = new Map(), pageRequests = new Map();
function loadState(index) {
	if (!pageLoads.has(index)) pageLoads.set(index, { count: 0, pending: false, error: false, timer: null, shown: false });
	return pageLoads.get(index);
}
function paintPageLoad(index) {
	const state = loadState(index), root = pages[index];
	if (!root) return;
	let node = root.querySelector(':scope > .screen-load-error');
	if (!node && state.error) {
		node = document.createElement('div'); node.className = 'screen-load-error'; node.hidden = true;
		node.setAttribute('role', 'status');
		const path = root.querySelector(':scope > .stpath');
		root.insertBefore(node, path ? path.nextSibling : root.firstChild);
	}
	const waiting = state.count > 0 || state.pending;
	root.setAttribute('aria-busy', String(waiting && !state.error));
	if (node) {
		node.hidden = !state.error;
		node.textContent = lang == 'zh' ? '加载失败，请重新进入页面重试' : 'Could not load. Reopen this page to retry.';
	}
	// A late reply from another page must not change the current title bar.
	const indicator = $('mobile-loading');
	if (index === page && indicator) {
		indicator.hidden = !!appOpen || state.error || !waiting || !state.shown;
		indicator.setAttribute('aria-label', t('loading'));
	}
}
function beginPageLoad(index) {
	const state = loadState(index);
	state.count++; state.error = false;
	paintPageLoad(index);
	if (!state.timer && !state.shown) state.timer = setTimeout(() => {
		state.timer = null; state.shown = true; paintPageLoad(index);
	}, 150);
	let ended = false;
	return error => {
		if (ended) return; ended = true;
		state.count--; state.error ||= !!error;
		if (!state.count && !state.pending) {
			clearTimeout(state.timer); state.timer = null; state.shown = false;
		}
		paintPageLoad(index);
	};
}
function pageLoadPending(index, pending) {
	const state = loadState(index); state.pending = !!pending;
	if (pending) state.shown = true;
	else if (!state.count) {
		clearTimeout(state.timer); state.timer = null; state.shown = false;
	}
	paintPageLoad(index);
}
function pageRead(path, index, type = 'json') {
	const key = index + ':' + path;
	if (pageRequests.has(key)) return pageRequests.get(key);
	const done = beginPageLoad(index), controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), 25000);
	let failed = false;
	const request = fetch(path, { cache: 'no-store', signal: controller.signal }).then(async response => {
		if (!response.ok) throw new Error('HTTP ' + response.status);
		return type == 'text' ? await response.text() : await response.json();
	}).catch(error => { failed = true; throw error; }).finally(() => {
		clearTimeout(timer); pageRequests.delete(key); done(failed);
	});
	pageRequests.set(key, request);
	return request;
}

async function poll() {
	clearTimeout(pollTimer);
	const done = last == null ? beginPageLoad(P.overview) : () => {};
	const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 25000);
	let failed = false;
	try {
		const r = await fetch('/api/status', { cache: 'no-store', signal: controller.signal });
		if (!r.ok) throw new Error('HTTP ' + r.status);
		if (r.ok) {
			const st = await r.json();
			const first = last == null;
			last = st;
			applyTouch();
			if (first) {
				lang = st.screen.lang in I18N ? st.screen.lang : 'zh';
				brightness = st.screen.brightness || 120;
				applyLang();
				resetIdle();
				if (!st.screen.donate_seen) donateOnce();
			}
			if (!blank) render(st);
			smsCheck(st);
			notificationCheck(st.notifications ?? []);
			pollUpdate();
		}
	} catch (e) {
		failed = true;
		console.log('poll: ' + e);
	}
	clearTimeout(timeout);
	done(failed);
	pollTimer = setTimeout(poll, blank ? POLL_BLANK : POLL_AWAKE);
}

function post(path, body) {
	return fetch('/api/' + path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	}).then((r) => r.json()).catch(() => null);
}

/* ---------- overview update notification ---------- */

function renderUpdateNotice() {
	renderNotification();
	const u = updateState, card = $('update-card');
	if (!card) return;
	card.hidden = page != P.overview || blank || locked || picShown || appOpen ||
		!u || (!u.busy && (!u.available || u.deferred));
	if (card.hidden) return;
	setText('update-version', `${u.current} → ${u.latest?.version ?? ''}`);
	setText('update-details', t(updateExpanded ? 'update_hide_logs' : 'update_logs'));
	$('update-details').setAttribute('aria-expanded', String(updateExpanded));
	const notes = lbl(u.latest?.notes) || t('update_scope');
	if ($('update-notes').textContent != notes) setText('update-notes', notes);
	$('update-notes').hidden = !updateExpanded;
	const error = u.action == 'apply' && u.result == 'failed' ? u.error : null;
	$('update-error').hidden = !error;
	setText('update-error', errorText(error, lang));
	const busy = u.busy || u.checking || updateRequest;
	setText('update-now', t(u.busy ? 'update_busy' : error ? 'update_retry' : 'update_now'));
	$('update-now').disabled = busy;
	$('update-later').disabled = busy;
}

async function pollUpdate(force = false) {
	const now = performance.now(), fast = updateState?.checking || updateState?.busy;
	if (updateRequest || (!force && now - updateLastPoll < (fast ? 2000 : 30000))) return;
	updateLastPoll = now;
	updateRequest = true;
	try {
		const r = await fetch('/api/update' + (last?.wan?.up ? '?check=1' : ''), { cache: 'no-store' });
		if (r.ok) {
			const u = await r.json();
			if (u.latest?.version != updateState?.latest?.version) updateExpanded = false;
			updateState = u;
		}
	} catch (e) { console.log('update: ' + e); }
	updateRequest = false;
	renderUpdateNotice();
}

on('update-details', 'click', () => {
	updateExpanded = !updateExpanded;
	renderUpdateNotice();
});

async function updateAction(action) {
	if (!updateState || updateRequest || updateState.busy || updateState.checking) return;
	updateRequest = true;
	renderUpdateNotice();
	const result = await post('update', { action, version: updateState.latest?.version });
	updateRequest = false;
	if (result?.ok) {
		updateState = result;
		if (action == 'apply') updateState.busy = true;
		else toast(t('update_deferred'));
	} else toast(`${t('failed')}${result?.error ? ': ' + errorText(result.error, lang) : ''}`);
	renderUpdateNotice();
	setTimeout(() => pollUpdate(true), 500);
}
on('update-now', 'click', () => updateAction('apply'));
on('update-later', 'click', () => updateAction('defer'));

// the volume keys: one step, silently, and with the screen lit the level over
// the page for a moment
let volTimer = null, volBusy = false;
async function volumeKey(step) {
	if (volBusy) return;                 // (held down: one request at a time)
	volBusy = true;
	const r = await post('volume', { step });
	volBusy = false;
	if (!r || !r.available) return;
	if (blank) return;
	resetIdle();
	const osd = $('vol-osd');
	setText('vol-label', r.kind === 'call' ? t('call_volume') : t('volume'));
	setText('vol-n', r.level > 0 ? String(r.level) : t('muted'));
	$('vol-bar').style.width = Math.round(r.level / (r.max || 15) * 100) + '%';
	osd.classList.add('show');
	clearTimeout(volTimer);
	volTimer = setTimeout(() => osd.classList.remove('show'), 1500);
}

function toast(msg) {
	const el = $('toast');
	el.textContent = msg;
	el.classList.add('show');
	clearTimeout(toast.timer);
	toast.timer = setTimeout(() => el.classList.remove('show'), 2000);
}

/* ---------- screen power ---------- */

function setBlank(on) {
	if (on == blank) return;
	if (!on && locked) return;          // locked: nothing lights the screen
	blank = on;
	document.body.classList.toggle('blank', on);
	post('backlight', { level: on ? 0 : brightness });
	if (!on) {
		if (last) render(last);
		poll();
	}
	resetIdle();
}

function resetIdle() {
	clearTimeout(idleTimer);
	const idle = last?.screen?.idle ?? 60;
	if (!blank && idle > 0 && !(appOpen && appKeepAwake))
		idleTimer = setTimeout(() => setBlank(true), idle * 1000);
}

/* ---------- a picture, full screen ---------- */

// an image item (高级 -> 关于 -> 赞赏), or the 赞赏码 the first time: over the
// pages until a key or a tap
function picOpen(src, caption, onClose, note) {
	$('pic-img').src = src;
	setText('pic-caption', caption ?? '');
	setText('pic-note', note ?? '');
	$('pic-note').hidden = !note;
	setText('pic-close', t('pic_close'));
	$('pic').hidden = false;
	picShown = true;
	picOpen.onClose = onClose;
	renderUpdateNotice();
}

function picClose() {
	$('pic').hidden = true;
	picShown = false;
	const f = picOpen.onClose;
	picOpen.onClose = null;
	if (f) f();
	renderUpdateNotice();
}

// the first start after an install (screen.donate_seen false): the About
// item's picture, once; closing it records that (POST /donate-seen)
async function donateOnce() {
	const r = await fetch('/api/settings/about', { cache: 'no-store' }).then((r) => r.json()).catch(() => null);
	const it = r?.items?.find((x) => x.id == 'donate');
	if (it) picOpen(it.src, lbl(it.caption), () => post('donate-seen'), t('donate_note'));
}

on('pic', 'click', () => picClose());

/* ---------- key lock ---------- */

// power (the screen goes dark), then * within 2 s: the keys are locked -- no
// key, touch or new message lights the screen until power, then * again, which
// unlocks and lights it.  The volume keys work on, dark, as always.  The
// motor says "locked", since the screen cannot.
const LOCK_WINDOW = 2000;
let lastPower = -Infinity;

function setLocked(on) {
	locked = on;
	if (on) {
		setBlank(true);
		post('vibrate', { ms: 80 });
	} else {
		setBlank(false);
		toast(t('unlocked'));
	}
	applyTouch();
	toApp({ e5: 'blank', on: blank });
	toIme({ e5: 'blank', on: blank });
}

// a key, as far as the lock is concerned: true when it is the lock's (the *
// that completes power-then-*, or any key while locked)
function keyLock(power, star) {
	const now = performance.now();
	if (star && now - lastPower < LOCK_WINDOW) {
		lastPower = -Infinity;
		setLocked(!locked);
		return true;
	}
	if (power) lastPower = now;
	return locked;
}

/* ---------- navigation ---------- */

function showPage(n) {
	page = (n + pages.length) % pages.length;
	pages.forEach((node, index) => node.classList.toggle('is-current', index == page));
	$('pages').style.transform = `translateX(${-100 * page}%)`;
	$('dots').innerHTML = pages.map((_, i) => `<i class="${i == page ? 'on' : ''}"></i>`).join('');
	$('foot-title').textContent = t(pages[page].dataset.title);
	if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
	pages[page].scrollTop = 0;
	if (last) render(last);
	if (page == P.hotspot) {
		qrFor = null;
		if (last) renderHotspot(last);
	}
	if (page == P.sms) {
		loadSms();
		markSmsRead();
	} else if (smsOpen != null) {
		closeSms();
	}
	clearInterval(advTimer);
	if (page == P.traffic) {
		loadTraffic();
		advTimer = setInterval(() => { if (!blank) loadTraffic(); }, 30000);
	} else if (page == P.adv_info) {
		loadAdvanced();
		advTimer = setInterval(() => { if (!blank) loadAdvanced(); }, 30000);
	} else if (showIds) {
		hideIds();
	}
	if (page == P.settings) stOpen();
	if (page == P.apps) loadApps();
	renderUpdateNotice();
}

function focusables() {
	if (!$('notification-card').hidden) return Array.from($('notification-card').querySelectorAll('button'));
	const list = Array.from(pages[page].querySelectorAll('button'));
	if (page == P.overview && $('update-card'))
		list.push(...$('update-card').querySelectorAll('button, [tabindex="0"]'));
	return list.filter((b) => b.offsetParent !== null && !b.disabled);
}

function moveFocus(dir) {
	if (document.activeElement === $('update-notes')) {
		const notes = $('update-notes'), before = notes.scrollTop;
		notes.scrollTop += dir * 60;
		if (notes.scrollTop != before) return;
	}
	const list = focusables();
	const pg = pages[page];
	if (!list.length) {
		pg.scrollBy({ top: dir * 80, behavior: 'smooth' });
		return;
	}
	let i = list.indexOf(document.activeElement);
	i = i < 0 ? (dir > 0 ? 0 : list.length - 1) : i + dir;
	if (i < 0 || i >= list.length) {
		// past the ends: scroll the page instead
		document.activeElement.blur();
		pg.scrollBy({ top: dir * 80, behavior: 'smooth' });
		return;
	}
	list[i].focus();
	list[i].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

// The session's E5 XKB map gives menu, call, confirm and # distinct names.
// Unidentified is never confirmation: WPE uses it for several evdev keys.
// GPIO F1 remains the hotspot side key; F13 is the keypad's call key.
function keyKind(e) {
	const k = e.key, c = e.keyCode;
	if (k == 'ContextMenu' || k == 'Menu') return 'menu';
	if (k == 'F13' || k == 'Phone' || k == 'PickupPhone' || k == 'Call') return 'call';
	if (k == 'F1' || c == 112) return 'hotspot';
	if (k == 'AudioVolumeUp' || c == 175) return 'volup';
	if (k == 'AudioVolumeDown' || c == 174) return 'voldown';
	if (k == 'ArrowLeft' || c == 37) return 'left';
	if (k == 'ArrowRight' || c == 39) return 'right';
	if (k == 'ArrowUp' || c == 38) return 'up';
	if (k == 'ArrowDown' || c == 40) return 'down';
	if (k == 'Enter' || k == 'Select' || k == 'Accept' || c == 13) return 'ok';
	if (k == 'BrowserBack' || k == 'GoBack' || k == 'Backspace' || k == 'Escape' || c == 8 || c == 27 || c == 166) return 'back';
	if (k == 'Power' || k == 'PowerOff' || k == 'Standby' || k == 'Sleep') return 'power';
	if (k >= '1' && k <= '9' && k.length == 1) return 'page' + k;
	return null;
}

// the keypad's back key reports KEY_BACK and BackSpace (kernel 0004) in one
// press: the second of the two, within 150 ms, is the same press
let lastBack = 0;

document.addEventListener('keydown', (e) => {
	if (keyLogged < KEY_LOG_MAX) {
		keyLogged++;
		post('key', { key: e.key, code: e.code, keyCode: e.keyCode, repeat: e.repeat });
	}
	const kind = keyKind(e);
	if (blank && !['power','volup','voldown'].includes(kind)) {
		e.preventDefault(); e.stopImmediatePropagation();
		return;
	}
	if (kind == 'back') {
		const now = performance.now();
		if (now - lastBack < 150) {
			e.preventDefault();
			return;
		}
		lastBack = now;
	}
	e.preventDefault();
	// the volume works with the screen dark too, and does not light it
	if (kind == 'volup' || kind == 'voldown') {
		volumeKey(kind == 'volup' ? 1 : -1);
		return;
	}
	if (keyLock(kind == 'power' && !e.repeat, e.key == '*')) return;
	if (blank) {
		if (kind == 'power' && !e.repeat) setBlank(false);
		return;
	}
	resetIdle();
	if (!$('notification-card').hidden && notificationKey(kind)) return;
	if (picShown) {
		picClose();
		return;
	}
	if (kind == 'menu') {
		if (!e.repeat) { if (appOpen) closeApp(); showPage(P.apps); }
		return;
	}
	if (appOpen) {                       // (a plugin frame lost the focus)
		(imeOpen ? $('ime-frame') : $('app-frame')).focus();
		return;
	}
	if (page == P.settings && stKey(kind)) return;
	switch (kind) {
	case 'left': showPage(page - 1); break;
	case 'right': showPage(page + 1); break;
	case 'up': moveFocus(-1); break;
	case 'down': moveFocus(1); break;
	case 'ok':
		if (document.activeElement && document.activeElement.tagName == 'BUTTON')
			pressKey(document.activeElement);
		break;
	case 'back':
		if (page == P.sms && smsOpen != null)
			closeSms();
		else if (document.activeElement && document.activeElement.tagName == 'BUTTON')
			document.activeElement.blur();
		else
			showPage(P.overview);
		break;
	case 'power':
		if (!e.repeat) setBlank(true);
		break;
	case 'hotspot': showPage(P.hotspot); break;
	default:
		if (kind && kind.startsWith('page')) showPage(+kind.slice(4) - 1);
	}
}, true);

// touch off, or the keys locked: every touch, tap and swipe is dropped here,
// before anything else sees it, and it does not wake the screen either.  WebKit follows a
// tap with a click it synthesises itself -- isTrusted false -- and its touch
// hit-testing ignores pointer-events: so every click is dropped, except the
// ones the keypad's confirm key makes (keyClick).
function touchOff() { return locked || last?.screen?.touch === false; }
let keyClick = false;
for (const ev of ['touchstart', 'touchmove', 'touchend', 'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'])
	window.addEventListener(ev, (e) => {
		if (touchOff() && !(ev == 'click' && keyClick)) {
			e.preventDefault();
			e.stopImmediatePropagation();
		}
	}, { capture: true, passive: false });

function pressKey(el) {
	keyClick = true;
	try { el.click(); } finally { keyClick = false; }
}

function applyTouch() {
	document.body.classList.toggle('notouch', touchOff());
	toApp({ e5: 'touch', on: !touchOff() });
	toIme({ e5: 'touch', on: !touchOff() });
}

// Ignore touch while dark; a horizontal swipe changes the page while awake.
let touch = null;
document.addEventListener('touchstart', (e) => {
	if (blank) {
		e.preventDefault();
		e.stopPropagation();
		touch = null;
		return;
	}
	resetIdle();
	const p = e.touches[0];
	touch = { x: p.clientX, y: p.clientY, t: Date.now() };
}, { capture: true, passive: false });

document.addEventListener('touchend', (e) => {
	if (!touch) return;
	const p = e.changedTouches[0];
	const dx = p.clientX - touch.x, dy = p.clientY - touch.y;
	if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy) && Date.now() - touch.t < 800)
		showPage(page + (dx < 0 ? 1 : -1));
	touch = null;
}, true);

document.addEventListener('mousedown', () => { if (!blank) resetIdle(); }, true);


/* ---------- SMS ---------- */

// "2026-09-27T10:25:31+08:00" -> "10:25" today, "09-26 10:25" before
function fmtSmsTime(ts) {
	const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(ts ?? '');
	if (!m) return '';
	const now = localParts();
	const today = now.y == +m[1] && now.mo == +m[2] && now.d == +m[3];
	return (today ? '' : `${m[2]}-${m[3]} `) + `${m[4]}:${m[5]}`;
}

async function loadSms() {
	try {
		const data = await pageRead('/api/sms', P.sms);
		smsList = data.messages ?? [];
		renderSmsList();
	} catch (e) {
		console.log('sms: ' + e);
	}
	if (smsOpen != null) {
		const current = smsList.find(m => m.id == smsOpen);
		if (current) {
			setText('sv-time', [current.sim, fmtSmsTime(current.time)].filter(Boolean).join(' · '));
			setText('sv-text', current.text ?? '');
		} else closeSms();
	}
	return smsList;
}

function renderSmsList() {
	const unread = new Set(last?.sms?.unread ?? []);
	const focusedId = document.activeElement?.dataset?.sms;
	setHTML('sms-list', smsList.length ? smsList.map((m) =>
		`<button class="smsitem${m.unread || unread.has(m.id) ? ' unread' : ''}" data-sms="${m.id}">` +
		`<div class="top"><span class="from">${esc(m.number ?? t('unknown_sender'))}</span>` +
		`<span class="when">${esc(m.sim ?? '')} · ${esc(fmtSmsTime(m.time))}</span></div>` +
		`<div class="preview">${esc((m.text ?? '').replace(/\s+/g, ' '))}</div></button>`
	).join('') : `<div class="card sub">${esc(t('no_sms'))}</div>`);
	if (focusedId) {
		const el = document.querySelector(`[data-sms="${focusedId}"]`);
		if (el) el.focus();
	}
}

function openSms(id) {
	const m = smsList.find((x) => x.id == id);
	if (!m) return;
	smsOpen = m.id;
	setText('sv-from', m.number ?? t('unknown_sender'));
	setText('sv-time', [m.sim, fmtSmsTime(m.time)].filter(Boolean).join(' · '));
	setText('sv-text', m.text ?? '');
	disarmDelete();
	$('sms-list').hidden = true;
	$('sms-view').hidden = false;
	pages[P.sms].scrollTop = 0;
}

function closeSms() {
	const id = smsOpen;
	smsOpen = null;
	disarmDelete();
	$('sms-view').hidden = true;
	$('sms-list').hidden = false;
	renderSmsList();
	const el = id != null && document.querySelector(`[data-sms="${id}"]`);
	if (el && page == P.sms) el.focus();
}

function disarmDelete() {
	clearTimeout(smsArmed);
	smsArmed = null;
	const b = $('sv-delete');
	b.classList.remove('armed');
	b.textContent = t('delete');
}

function renderSmsIndicator(ids) {
	const count = ids?.length ?? 0, icon = $('bar-sms');
	if (icon.hidden !== !count) icon.hidden = !count;
	const label = count ? `${t('unread_sms')} (${count})` : '';
	if (icon.getAttribute('aria-label') !== label) icon.setAttribute('aria-label', label);
}

async function markSmsRead() {
	if (blank || locked || window.T551M?.isLocked() || smsReading || !(last?.sms?.unread?.length)) return;
	const ids = new Set(last.sms.unread);
	smsReading = true;
	try {
		const result = await post('sms-read');
		if (!result?.ok) return;  // Keep the indication until the shared inbox acknowledges the read.
		if (last?.sms) last.sms.unread = (last.sms.unread ?? []).filter(id => !ids.has(id));
		if (smsUnread) smsUnread = smsUnread.filter(id => !ids.has(id));
		for (const message of smsList) if (ids.has(message.id)) message.unread = false;
		renderSmsIndicator(last?.sms?.unread);
	} finally { smsReading = false; }
}

// a message in the unread list that was not there at the last poll: light
// the screen (if e5-notify.sms.screen) and show it
let smsHiddenRevision;
async function smsCheck(st) {
	const hiddenChanged=smsHiddenRevision!=null && smsHiddenRevision!==st.sms?.hidden_revision;
	smsHiddenRevision=st.sms?.hidden_revision;
	if (hiddenChanged && page==P.sms && !blank) await loadSms();
	const now = st.sms?.unread ?? [];
	const before = smsUnread;
	smsUnread = now;
	if (before == null) return;                 // the first poll: nothing is new
	const fresh = now.filter((id) => !before.includes(id));
	if (!fresh.length) {
		if (page == P.sms && !blank && smsOpen == null && now.length != before.length) loadSms();
		if (page == P.sms && !blank && smsList.find(m => m.id == smsOpen)?.state == 'receiving') loadSms();
		return;
	}
	if (!st.sms.screen || locked) return;
	if (blank) setBlank(false);
	if (page != P.sms) showPage(P.sms);
	await loadSms();
	const newest = smsList.find(m => fresh.includes(m.id));
	toast(t('new_sms') + (newest?.sim ? ' · ' + newest.sim : ''));
	if (newest) openSms(newest.id);
	markSmsRead();
}

on('sms-list', 'click', (e) => {
	const b = e.target.closest('[data-sms]');
	if (b) openSms(+b.dataset.sms);
});

on('sv-back', 'click', () => closeSms());

on('sv-delete', 'click', async () => {
	const b = $('sv-delete');
	if (!smsArmed) {
		b.classList.add('armed');
		b.textContent = t('delete_confirm');
		smsArmed = setTimeout(disarmDelete, 3000);
		return;
	}
	const id = smsOpen;
	disarmDelete();
	const r = await post('sms-delete', { id });
	toast(r?.ok ? t('deleted') : '✗');
	if (!r?.ok) return;
	smsList = smsList.filter((m) => m.id != id);
	closeSms();
	loadSms();
});

/* ---------- traffic ---------- */

let trafficRequest = 0;
function clearTrafficDisplay() {
	for (const id of ['tf-day-used','tf-mon-used','tf-day-rx','tf-day-tx','tf-mon-rx','tf-mon-tx','tf-boot-rx','tf-boot-tx']) setText(id,'—');
	for (const id of ['tf-days','tf-day-since','tf-mon-since']) setText(id,'');
}
on('tf-slot','change',()=>{clearTrafficDisplay();loadTraffic();});
async function loadTraffic() {
	const request = ++trafficRequest, slot = $('tf-slot')?.value || '';
	let u = null;
	try {
		u = await pageRead('/api/traffic' + (slot ? '?slot='+slot : ''), P.traffic);
	} catch (e) {
		console.log('traffic: ' + e);
	}
	if (request !== trafficRequest) return;
	const b = T551M.amount;
	clearTrafficDisplay();
	const warning = !u || u.error ? t('traffic_unavailable') : !u.available ? t('traffic_clock') : u.storage_error ? t('traffic_storage') : u.interface_available === false ? t('traffic_history') : '';
	setText('tf-state', (u?.slot == null ? '' : 'SIM '+(+u.slot+1)+(warning ? ' · ' : ''))+warning);
	setText('tf-boot-rx',b(u?.session?.rx));setText('tf-boot-tx',b(u?.session?.tx));
	if (!u?.available) return;
	setText('tf-day-used',b(u.today_used));setText('tf-mon-used',b(u.month_used));
	setText('tf-day-rx', b(u.today.rx)); setText('tf-day-tx', b(u.today.tx));
	setText('tf-mon-rx', b(u.month.rx)); setText('tf-mon-tx', b(u.month.tx));
	const l = u.lan?.available ? u.lan : null;
	setText('tf-day-lan-rx', l ? b(l.today.rx) : '--'); setText('tf-day-lan-tx', l ? b(l.today.tx) : '--');
	setText('tf-mon-lan-rx', l ? b(l.month.rx) : '--'); setText('tf-mon-lan-tx', l ? b(l.month.tx) : '--');
	// counting began inside this month (or today): say so, the total is partial
	const since = u.since ? localParts(u.since * 1000) : null, nowd = localParts();
	const p2 = (n) => String(n).padStart(2, '0');
	const sinceText = since ? `${t('counting_since')} ${p2(since.mo)}-${p2(since.d)} ${p2(since.h)}:${p2(since.mi)}` : '';
	const sameMonth = since && since.y == nowd.y && since.mo == nowd.mo;
	const sameDay = sameMonth && since.d == nowd.d;
	setText('tf-mon-since', sameMonth ? sinceText : '');
	setText('tf-day-since', sameDay ? sinceText : '');
	const max = Math.max(1, ...u.days.map((d) => d.rx + d.tx));
	setHTML('tf-days', u.days.length ? u.days.slice().reverse().map((d) =>
		`<div class="day"><span>${esc(d.date)}</span><span class="bar">` +
		`<i class="rx" style="width:${(d.rx / max * 100).toFixed(1)}%"></i>` +
		`<i class="tx" style="width:${(d.tx / max * 100).toFixed(1)}%"></i></span>` +
		`<span class="sum">${esc(b(d.rx + d.tx))}</span></div>`).join('')
		: `<div class="sub">${esc(t('none'))}</div>`);
}

/* ---------- advanced ---------- */

const REG_WORD = { home: 'home', roaming: 'roaming_reg', idle: 'idle_reg', denied: 'denied', searching: 'searching' };

async function loadAdvanced() {
	try {
		const r = await fetch('/api/advanced', { cache: 'no-store' });
		if (r.ok) adv = await r.json();
	} catch (e) {
		console.log('advanced: ' + e);
	}
	if (adv) renderAdvanced(adv);
}

function renderAdvanced(a) {
	const d = a.device ?? {}, b = a.baseband, s = a.sim;
	setText('ad-model', d.model ?? '--');
	setText('ad-os', d.os ?? '--');
	setText('ad-image', d.image ?? '--');
	setText('ad-kernel', d.kernel ?? '--');
	if (d.disk) {
		const [u, uu] = fmtBytes(d.disk.used), [tt, tu] = fmtBytes(d.disk.total);
		setText('ad-disk', `${u} ${uu} / ${tt} ${tu}`);
	}
	setText('ad-temp', d.thermal ? `${d.thermal.temp.toFixed(0)} °C` : '--');
	setText('ad-bat', [d.battery_mv ? (d.battery_mv / 1000).toFixed(2) + ' V' : null,
		d.battery_temp != null ? d.battery_temp.toFixed(0) + ' °C' : null].filter(Boolean).join(' · ') || '--');
	setHTML('ad-temps', temperatureSummary(d.temperatures ?? last?.system?.temperatures));
	// The overview already covers these direct zones; expansion shows the
	// individual CPU/NR readings, physical zones and unverified shell/charger.
	const directZones = ['soc-thmzone', 'gpu-thmzone', 'lte-thmzone', 'mm-thmzone', 'board-thmzone', 'pa-thmzone', 'battery'];
	setHTML('ad-extra-temps', (d.thermal_zones ?? []).filter((z) => !directZones.includes(z.zone)).map((z) =>
		`<span class="label">${esc(z.zone)}</span><span class="value">${fmtTemp(z.temp)}` +
		(z.estimated ? ` · ${esc(t('estimated'))}` : '') +
		(z.unverified ? ` · <span class="warn">${esc(t('unverified'))}</span>` : '') + '</span>').join(''));
	$('ad-extra-temps').hidden = !extraTemps;
	setText('ad-moretemps', t(extraTemps ? 'show_less' : 'show_more'));

	setText('ad-bb', b ? [b.manufacturer, b.model].filter(Boolean).join(' ') : t('no_modem'));
	setText('ad-sa', b?.sa_allowed == null ? '--' : b.sa_allowed ? t('allowed') : t('nsa_only'));
	setText('ad-modes', b?.modes?.replace(/^allowed: /, '').replace(/; preferred: none$/, '') ?? '--');
	setHTML('ad-fw', (b?.firmware ?? []).map((f) => `${esc(f.name)}: ${esc(f.value)}`).join('<br>'));

	const bands = (list, pre) => list?.length ? list.map((x) => pre + x).join(' ') : t('not_locked');
	setText('ad-lte', b ? bands(b.lte_lock, 'B') : '--');
	setText('ad-nr', b ? bands(b.nr_lock, 'n') : '--');
	const cells = [...(b?.lte_cell_lock ?? []).map((c) => `LTE ${c.arfcn}/${c.pci}`),
		...(b?.nr_cell_lock ?? []).map((c) => `NR ${c.arfcn}/${c.pci}`)];
	setText('ad-cell', b ? (cells.length ? cells.join(', ') : t('not_locked')) : '--');

	setText('ad-slot', s?.active_slot ? t('card') + s.active_slot : '--');
	setText('ad-op', s ? [s.operator, s.operator_code].filter(Boolean).join(' · ') || '--' : '--');
	setText('ad-reg', s?.registration ? t(REG_WORD[s.registration] ?? s.registration) : '--');
}

function hideIds() {
	showIds = false;
	$('ad-ids').hidden = true;
	$('ad-showids').textContent = t('show_ids');
	for (const id of ['id-imei', 'id-iccid', 'id-imsi', 'id-num']) setText(id, '--');
}

on('ad-moretemps', 'click', () => {
	extraTemps = !extraTemps;
	$('ad-extra-temps').hidden = !extraTemps;
	setText('ad-moretemps', t(extraTemps ? 'show_less' : 'show_more'));
});

on('ad-showids', 'click', async () => {
	if (showIds) return hideIds();
	const r = await pageRead('/api/identity', P.adv_info).catch(() => null);
	if (!r) return;
	showIds = true;
	setText('id-imei', r.imei ?? '--');
	setText('id-iccid', r.iccid ?? '--');
	setText('id-imsi', r.imsi ?? '--');
	setText('id-num', r.numbers?.length ? r.numbers.join(', ') : '--');
	$('ad-ids').hidden = false;
	$('ad-showids').textContent = t('hide_ids');
});

/* ---------- settings ("高级") ---------- */

// a stack of views: menu -> category -> edit (choice / number / multi),
// menu -> devices -> device
let st = [];
let stCats = null;
let stArmed = null;               // { key, timer }: the row waiting for its second press
const lbl = (l) => errorText((l && typeof l == 'object') ? (l[lang] ?? l.zh ?? '') : (l ?? ''), lang);

function stTop() { return st[st.length - 1]; }

async function stOpen() {
	if (!st.length) st = [{ view: 'menu' }];
	stRender();
	if (!stCats) {
		const r = await pageRead('/api/settings', P.settings).catch(() => null);
		if (r) stCats = r.categories ?? [];
		stRender();
	}
}

async function stLoadCat(v) {
	const r = await pageRead('/api/settings/' + v.cat.id, P.settings).catch(() => null);
	if (r) v.items = r.items ?? [];
	if (stTop() === v) stRender();
	return r != null;
}

function stDisarm() {
	if (stArmed) clearTimeout(stArmed.timer);
	stArmed = null;
}

// true when this press was the second one
function stConfirm(key, el) {
	if (stArmed && stArmed.key == key) {
		stDisarm();
		return true;
	}
	stDisarm();
	stArmed = { key, timer: setTimeout(() => { stDisarm(); stRender(); }, 3000) };
	if (el) {
		el.classList.add('armed');
		const sv = el.querySelector('.sv');
		if (sv) sv.textContent = t('press_again');
	}
	return false;
}

function stValue(it) {
	if (it.type == 'toggle') return it.value == null ? '--' : it.value ? t('on') : t('off');
	if (it.type == 'choice') {
		const o = (it.options ?? []).find((o) => String(o.value) == String(it.value));
		return o ? lbl(o.label) : (it.value ?? '--');
	}
	if (it.type == 'number') return it.value == null ? '--' : `${it.value}${it.unit ?? ''}`;
	if (it.type == 'multi') {
		if (it.display_value != null) return lbl(it.display_value);
		if (!it.value?.length) return lbl(it.none_label) || t('not_locked');
		return it.value.map((v) => lbl((it.options ?? []).find((o) => o.value == v)?.label) || v).join(' ');
	}
	if (it.type == 'info') return lbl(it.value ?? '--');
	return '';
}

function stRow(key, label, value, opts = {}) {
	const tag = opts.info ? 'div' : 'button';
	return `<${tag} class="strow${opts.info ? ' info' : ''}" data-st="${esc(key)}">` +
		`<span>${esc(label)}</span><span class="sv${opts.on ? ' on' : ''}${opts.chev ? ' chev' : ''}">${esc(value)}</span></${tag}>` +
		(opts.note ? `<div class="stnote">${esc(opts.note)}</div>` : '');
}

function stRender() {
	const v = stTop();
	if (!v) return;
	const path = st.map((x) => x.view == 'menu' ? t('settings') : x.view == 'store' ? t('app_store') : x.view == 'atres' ? x.cmd : x.view == 'app' ? (lbl(x.app.name) || x.app.id) : x.cat ? lbl(x.cat.label) : x.item ? lbl(x.item.label) : x.dev ? (x.dev.name ?? x.dev.ip ?? x.dev.mac) : x.view == 'btdev' ? (x.name ?? x.mac) : '').join(' › ');
	setText('st-path', path);
	let html = '';
	if (v.view == 'menu') {
		// Apps and their settings share the app manager; plugin categories stay
		// in the API so an app's detail view can open its own settings.
		html = stCats == null ? '' :
			stCats.map((c, i) => c.plugin || c.parent ? '' : stRow('cat:' + i, lbl(c.label), '', { chev: true })).join('');
	} else if (v.view == 'cat') {
		html = v.items == null ? '' :
			v.items.map((it) => stRow('item:' + it.id, lbl(it.label), stValue(it),
				{ info: it.type == 'info', on: it.type == 'toggle' && it.value, note: lbl(it.note),
				  chev: ['choice', 'number', 'multi', 'image', 'category'].includes(it.type) })).join('');
	} else if (v.view == 'apn' || v.view == 'apnedit') {
		html = stAPNRender(v);
	} else if (v.view == 'edit') {
		const it = v.item;
		if (it.type == 'choice') {
			html = it.options.map((o, i) => `<button class="strow opt${String(o.value) == String(it.value) ? ' on' : ''}" data-st="opt:${i}"><span>${esc(lbl(o.label))}</span><span class="sv"></span></button>`).join('');
		} else if (it.type == 'number') {
			html = `<div class="card stnum">${esc(String(v.draft))}${esc(it.unit ?? '')}</div>` +
				`<div class="stbtns"><button class="btn" data-st="num:-">−</button><button class="btn" data-st="num:+">+</button></div>` +
				`<div style="height:8px"></div><button class="strow" data-st="num:save"><span>${esc(t('save'))}</span><span class="sv"></span></button>`;
		} else if (it.type == 'multi') {
			html = it.options.map((o, i) => `<button class="strow opt check${v.draft.includes(o.value) ? ' on' : ''}" data-st="chk:${i}"><span>${esc(lbl(o.label))}</span><span class="sv"></span></button>`).join('') +
				`<button class="strow" data-st="multi:clear"><span>${esc(t('clear'))}</span><span class="sv"></span></button>` +
				`<button class="strow" data-st="multi:apply"><span>${esc(t('apply'))}</span><span class="sv">${esc(v.draft.length ? '' : t('not_locked'))}</span></button>`;
		}
		if (it.note) html += `<div class="stnote">${esc(lbl(it.note))}</div>`;
	} else if (v.view == 'at') {
		html = v.presets == null ? '' :
			stRow('atslot:',lang=='zh'?'AT 卡槽':'AT SIM','SIM '+(+(v.slot ?? last?.modem?.sim_card ?? 0)+1),{chev:true})+
			v.presets.map((p, i) => stRow('atp:' + i, lbl(p.label), p.cmd)).join('') +
			`<div class="stnote">${esc(t('at_note'))}</div>`;
	} else if (v.view == 'atres') {
		html = `<div class="card"><div class="sub">${esc(v.cmd)}</div>` +
			`<div class="smstext" style="margin-top:6px;font-size:13px">${esc(v.reply ?? t('at_running'))}</div></div>` +
			(v.warn ? `<div class="stnote">${esc(v.warn)}</div>` : '') +
			stRow('atagain:', t('at_again'), '');
	} else if (v.view == 'devices') {
		html = v.list == null ? '' : v.list.length ?
			v.list.map((d, i) => stRow('dev:' + i, d.name ?? d.ip ?? d.mac,
				d.blocked ? t('blocked') : d.online ? `${t('online')} · ${t(d.via ?? 'wifi')}` : t('offline'),
				{ on: d.online && !d.blocked, chev: true })).join('') : `<div class="sub">${esc(t('no_devices'))}</div>`;
	} else if (v.view == 'apps') {
		html = stRow('store:', t('app_store'), '', { chev: true }) + (v.list == null ? '' :
			(v.list.length ? v.list.map((m) => stRow('apm:' + m.id, lbl(m.name) || m.id,
				(m.version ? 'v' + m.version + ' · ' : '') + (m.builtin ? t('app_builtin') : t('app_user')), { chev: true })).join('')
				: `<div class="sub">${esc(t('no_apps'))}</div>`) +
			`<div class="stnote">${esc(t('app_install_note'))}</div>`);
	} else if (v.view == 'store') {
		const s = v.store;
		if (!s) html = '';
		else if (!s.available) html = `<div class="sub">${esc(t('store_fail'))}${s.error ? ': ' + esc(errorText(s.error, lang)) : ''}</div>`;
		else html = s.plugins.length ? s.plugins.map((p) => {
			const have = p.installed != null, same = have && p.installed == p.version;
			const what = same ? `${t('store_have')} v${p.version}` : have ? `${t('store_update')} v${p.version}` : `${t('store_install')} v${p.version}`;
			return stRow('stp:' + p.id, lbl(p.name) || p.id, v.busy == p.id ? t('store_installing') : what,
				{ on: same, note: [lbl(p.description), p.backend ? t('store_backend') : ''].filter(Boolean).join(' · ') });
		}).join('') : `<div class="sub">${esc(t('store_empty'))}</div>`;
		html += stRow('storerf:', t('store_refresh'), '') + `<div class="stnote">${esc(t('store_note'))}</div>`;
	} else if (v.view == 'app') {
		const m = v.app;
		html = stRow('info:appid', 'ID', m.id, { info: true }) +
			stRow('info:appver', t('app_version'), m.version ?? '--', { info: true }) +
			stRow('info:appkind', t('app_kind'), m.builtin ? t('app_builtin') : t('app_user'), { info: true }) +
			(m.description ? stRow('info:appdesc', t('app_desc'), lbl(m.description), { info: true }) : '') +
			stRow('apa:open', t('app_open'), '') +
			(m.settings?.length ? stRow('apa:settings', t('app_config'), '', { chev: true }) : '') +
			stRow('apa:remove', t('app_remove'), '') +
			(m.builtin ? `<div class="stnote">${esc(t('app_builtin_note'))}</div>` : '');
	} else if (v.view == 'bluetooth') {
		const b = v.bt;
		if (!b) html = '';
		else if (!b.adapter) html = `<div class="sub">${esc(t('bt_none'))}</div>`;
		else {
			html = stRow('bt:power', t('bluetooth'), b.powered ? t('on') : t('off'), { on: b.powered }) +
				(b.autostart != null ? stRow('bt:autostart', t('bt_autostart'), b.autostart ? t('on') : t('off'), { on: b.autostart }) : '') +
				(b.powered ? stRow('bt:scan', b.discovering ? t('bt_scanning') : t('bt_scan'), '') : '') +
				(b.name ? stRow('info:btname', t('bt_name'), b.name, { info: true }) : '');
			const mine = b.devices.filter((d) => d.paired || d.connected), found = b.devices.filter((d) => !d.paired && !d.connected);
			if (mine.length) html += `<div class="lh">${esc(t('bt_mine'))}</div>` + mine.map((d) => stRow('btd:' + d.mac, d.name, btWord(d), { on: d.connected, chev: true })).join('');
			if (b.powered) html += `<div class="lh">${esc(t('bt_found'))}</div>` + (found.length ?
				found.map((d) => stRow('btd:' + d.mac, d.name, btWord(d), { chev: true })).join('') :
				`<div class="sub">${esc(b.discovering ? t('bt_scanning') : t('bt_none_found'))}</div>`);
			html += `<div class="stnote">${esc(t('bt_note'))}</div>`;
		}
	} else if (v.view == 'btdev') {
		const d = v.parent.bt?.devices.find((x) => x.mac == v.mac) ?? { mac: v.mac, name: v.mac };
		html = stRow('info:btmac', t('mac'), d.mac, { info: true }) +
			stRow('info:btst', t('bt_state'), btWord(d), { info: true }) +
			(d.connected ? stRow('bta:disconnect', t('bt_disconnect'), '') : stRow('bta:connect', d.paired ? t('bt_connect') : t('bt_pair'), '')) +
			(d.paired ? stRow('bta:remove', t('bt_remove'), '') : '') +
			(d.state?.startsWith('failed') ? `<div class="stnote">${esc(btReason(d.state))}</div>` : '');
	} else if (v.view == 'device') {
		const d = v.dev;
		html = stRow('info:mac', t('mac'), d.mac, { info: true }) +
			stRow('info:ip', 'IP', d.ip ?? '--', { info: true }) +
			stRow('info:via', t('via'), d.online ? t(d.via ?? 'wifi') + (d.signal ? ` · ${d.signal} dBm` : '') : t('offline'), { info: true }) +
			stRow('act:' + (d.blocked ? 'unblock' : 'block'), d.blocked ? t('unblock') : t('block'), '') +
			(d.online && d.via == 'wifi' ? stRow('act:kick', t('kick'), '') : '');
	}
	const focused = document.activeElement?.dataset?.st;
	setHTML('st-view', html);
	if (v.view == 'apnedit') stAPNBind(v);
	if (focused) {
		const el = document.querySelector(`[data-st="${CSS.escape(focused)}"]`);
		if (el) el.focus();
	}
}

async function stPost(v, body) {
	const item = v.items?.find(i=>i.id===body.id);
	if (item?.slot != null) body.slot = item.slot;
	const done = beginPageLoad(P.settings);
	v.saving = true;
	let r = await fetch('/api/settings/' + v.cat.id, {
		method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
	}).then((r) => r.json()).catch(() => null);
	if (r?.pending && r.job) {
		const job=r.job, slot=r.slot, service=r.service||'lock', until=Date.now()+245000;
		try {
			while (Date.now()<until) {
				await new Promise(resolve=>setTimeout(resolve,800));
				r=await fetch('/api/network-job?id='+encodeURIComponent(job)+'&slot='+encodeURIComponent(slot)+'&service='+encodeURIComponent(service),{cache:'no-store'}).then(r=>r.json());
				if (!['queued','running'].includes(r.state)) break;
			}
			if (r.state!=='done') r={ok:false,error:r.error || (lang=='zh'?'操作尚未完成，请刷新实际状态':'Operation incomplete; refresh actual state')};
		} catch(e) {r={ok:false,error:String(e)};}
		await stLoadCat(v);
	}
	v.saving = false;done(!r?.ok);
	toast(r?.ok ? (r.reconnect == 'deferred' ? t('network_deferred') :
		r.reconnect == 'failed' ? t('network_reconnect_failed') :
		r.refresh_error ? t('network_refresh_pending') :
		v.cat.id == 'usb' && body.id == 'reset' ? t('usb_resetting') : t('saved')) : `${t('failed')}${r?.error ? ': ' + errorText(r.error, lang) : ''}`);
	if (r?.ok && v.cat.id == 'traffic_clear') {
		++trafficRequest;
		clearTrafficDisplay();
		T551M.refreshUsage();
		toast(t('traffic_cleared'));
	}
	if (r?.item) {
		const i = v.items.findIndex((x) => x.id == r.item.id);
		if (i >= 0) v.items[i] = r.item;
	}
	if (r?.ok && r.item?.reload) stLoadCat(v);
	if (r?.ok && v.cat.id == 'usb' && ['reset','usb_role','usb_host_boot'].includes(body.id)) {
		const refresh = async () => {
			if (!st.includes(v)) return;
			await stLoadCat(v);
			if (v.items?.some(i => ['reset_status','usb_role_state'].includes(i.id) && i.busy)) setTimeout(refresh, 2000);
		};
		setTimeout(refresh, 2000);
	}
	if (r?.ok && v.cat.id == 'screen') stScreenApplied(body.id, r.item?.value ?? body.value);
	if (r?.ok && v.cat.id == 'system' && body.id == 'clock_seconds' && last) {
		last.screen.clock_seconds = !!body.value;
		tickClock();
	}
	return r;
}

// the screen settings take effect on the page at once
function stScreenApplied(id, value) {
	if (!last) return;
	if (id == 'brightness') {
		brightness = Math.max(1, Math.round(+value * 255 / 100));
		last.screen.brightness = brightness;
		post('backlight', { level: brightness });
	} else if (id == 'idle') {
		last.screen.idle = +value;
		resetIdle();
	} else if (id == 'touch') {
		last.screen.touch = !!value;
		applyTouch();
	} else if (id == 'lang') {
		lang = value in I18N ? value : 'zh';
		last.screen.lang = lang;
		applyLang();
		if (last) render(last);
	}
}

async function stClick(key, el) {
	const v = stTop();
	if (v?.saving || v?.parent?.saving) return;
	if (v?.view == 'apn' || v?.view == 'apnedit') return stAPNClick(v,key,el);
	const [k, arg] = [key.slice(0, key.indexOf(':')), key.slice(key.indexOf(':') + 1)];
	if (k == 'atslot') {v.slot=String(1-+(v.slot ?? last?.modem?.sim_card ?? 0));stRender();return;}
	if (k == 'atp' || k == 'atagain') {
		const cmd = k == 'atp' ? v.presets[+arg].cmd : v.cmd;
		const nv = k == 'atp' ? { view: 'atres', cmd, reply: null, slot: v.slot ?? String(last?.modem?.sim_card ?? 0) } : v;
		if (k == 'atp') st.push(nv);
		nv.reply = null;
		stRender();
		const done = beginPageLoad(P.settings);
		const r = await fetch('/api/at', {
			method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cmd, slot:nv.slot })
		}).then((r) => r.json()).catch(() => null).finally(() => done());
		nv.reply = r?.ok ? (r.reply || 'OK') : `${t('failed')}: ${errorText(r?.error, lang)}`;
		nv.warn = r?.warning ? t('at_risky') : null;
		if (stTop() === nv) stRender();
		return;
	}
	if (k == 'cat') {
		const c = stCats[+arg];
		if (c.view == 'at') {
			const nv = { view: 'at', cat: c, presets: null };
			st.push(nv); stRender();
			const r = await pageRead('/api/at/presets', P.settings).catch(() => null);
			nv.presets = r?.presets ?? [];
			if (stTop() === nv) stRender();
			return;
		}
		if (c.view == 'apps') {
			const nv = { view: 'apps', cat: c, list: null };
			st.push(nv); stRender();
			const r = await pageRead('/api/plugins', P.settings).catch(() => null);
			nv.list = r?.plugins ?? [];
			if (stTop() === nv) stRender();
			return;
		}
		if (c.view == 'bluetooth') {
			const nv = { view: 'bluetooth', cat: c, bt: null };
			st.push(nv); stRender();
			btPoll(nv);
			return;
		}
		if (c.view == 'devices') {
			const nv = { view: 'devices', cat: c, list: null };
			st.push(nv); stRender();
			const r = await pageRead('/api/devices', P.settings).catch(() => null);
			nv.list = r?.devices ?? [];
			if (stTop() === nv) stRender();
		} else {
			const nv = { view: 'cat', cat: c, items: null };
			st.push(nv); stRender();
			stLoadCat(nv);
		}
		return;
	}
	if (k == 'item') {
		let it = v.items.find((x) => x.id == arg);
		if (!it) return;
		if (v.cat.id == 'network' && ['lte_bands','nr_bands'].includes(arg)) {
			// The web may have changed this SIM since the category was opened.
			// Read the shared cache again on entry, without adding AT polling.
			v.saving = true;
			let loaded;
			try { loaded = await stLoadCat(v); } finally { v.saving = false; }
			if (stTop() !== v || !loaded) return;
			it = v.items.find(x => x.id == arg);
			if (!it || it.type !== 'multi') return;
		}
		if (it.type == 'category') {
			const c = stCats.find(x => x.id == it.category);
			if (!c) return;
			const nv = {view:c.view == 'apn' ? 'apn':'cat',cat:c,items:null};
			st.push(nv); stRender();
			if (nv.view == 'apn') await stAPNLoad(nv);
			else await stLoadCat(nv);
			return;
		}
		if (it.type == 'toggle') {
			if (it.confirm && !stConfirm(key, el)) return;
			await stPost(v, { id: it.id, value: !it.value });
			stRender();
		} else if (it.type == 'action') {
			if (it.confirm && !stConfirm(key, el)) return;
			await stPost(v, { id: it.id });
			stLoadCat(v);
		} else if (it.type == 'image') {
			picOpen(it.src, lbl(it.caption), () => el?.focus());
		} else if (it.type == 'choice' || it.type == 'number' || it.type == 'multi') {
			st.push({ view: 'edit', cat: v.cat, item: it, parent: v,
			          draft: it.type == 'multi' ? [...(it.value ?? [])] : it.value });
			stRender();
			const first = document.querySelector('#st-view button');
			if (first) first.focus();
		}
		return;
	}
	if (v.view == 'edit') {
		const it = v.item;
		if (k == 'opt') {
			const o = it.options[+arg];
			if (it.confirm && String(o.value) != String(it.value) && !stConfirm(key, el)) return;
			if (String(o.value) != String(it.value) && !(await stPost(v.parent, { id: it.id, value: o.value }))?.ok) return;
			if (stTop()===v) st.pop(); stRender();
		} else if (k == 'num') {
			if (arg == 'save') {
				if (it.confirm && !stConfirm(key, el)) return;
				if (!(await stPost(v.parent, { id: it.id, value: v.draft }))?.ok) return;
				if (stTop()===v) st.pop(); stRender();
			} else {
				v.draft = Math.min(it.max, Math.max(it.min, +v.draft + (arg == '+' ? 1 : -1) * (it.step ?? 1)));
				stRender();
			}
		} else if (k == 'chk') {
			const o = it.options[+arg];
			v.draft = v.draft.includes(o.value) ? v.draft.filter((x) => x != o.value) : [...v.draft, o.value];
			stRender();
		} else if (k == 'multi') {
			if (arg == 'clear') { v.draft = []; stRender(); return; }
			if (it.confirm && !stConfirm(key, el)) return;
			if (!(await stPost(v.parent, { id: it.id, value: v.draft }))?.ok) return;
			if (stTop()===v) st.pop(); stRender();
		}
		return;
	}
	if (k == 'store' || k == 'storerf') {
		const nv = k == 'store' ? { view: 'store', store: null, parent: v } : v;
		if (k == 'store') st.push(nv);
		nv.store = null; stRender();
		nv.store = await pageRead('/api/store' + (k == 'storerf' ? '?refresh=1' : ''), P.settings).catch(() => ({ available: false }));
		if (stTop() === nv) stRender();
		return;
	}
	if (k == 'stp') {
		const p = v.store?.plugins.find((x) => x.id == arg);
		if (!p || v.busy || p.installed == p.version) return;
		if (!stConfirm(key, el)) return;
		v.busy = p.id; stRender();
		const r = await post('store-install', { id: p.id });
		v.busy = null;
		toast(r?.ok ? t('saved') : `${t('failed')}${r?.error ? ': ' + errorText(r.error, lang) : ''}`);
		v.store = await pageRead('/api/store', P.settings).catch(() => v.store);
		// (the apps list below it, and the Apps page, see the new one)
		if (v.parent?.view == 'apps') v.parent.list = (await pageRead('/api/plugins', P.settings).catch(() => null))?.plugins ?? v.parent.list;
		loadApps();
		if (stTop() === v) stRender();
		return;
	}
	if (k == 'apm') {
		const m = v.list.find((x) => x.id == arg);
		if (m) { st.push({ view: 'app', cat: v.cat, app: m, parent: v }); stRender(); }
		return;
	}
	if (k == 'apa') {
		if (arg == 'settings') {
			if (!v.app.settings?.length) return;
			const nv = { view: 'cat', cat: { id: 'plugin:' + v.app.id, label: { zh: '设置', en: 'Settings' } }, items: null };
			st.push(nv); stRender();
			await stLoadCat(nv);
			return;
		}
		if (arg == 'open') {
			showPage(P.apps);
			await loadApps();
			const m = apps.find((x) => x.id == v.app.id);
			if (m) openApp(m);
			return;
		}
		if (!stConfirm(key, el)) return;
		const r = await post('plugins-remove', { id: v.app.id });
		toast(r?.ok ? t('app_removed') : `${t('failed')}${r?.error ? ': ' + errorText(r.error, lang) : ''}`);
		if (r?.ok) {
			st.pop();
			v.parent.list = v.parent.list.filter((x) => x.id != v.app.id);
			apps = null;
		}
		stRender();
		return;
	}
	if (k == 'bt') {
		const b = v.bt;
		if (!b) return;
		await btPost(v, arg == 'power' ? { action: 'power', on: !b.powered } :
			arg == 'autostart' ? { action: 'autostart', on: !b.autostart } : { action: 'scan' });
		if (arg == 'scan') toast(t('bt_scanning'));
		return;
	}
	if (k == 'btd') {
		const d = v.bt.devices.find((x) => x.mac == arg);
		st.push({ view: 'btdev', cat: v.cat, mac: arg, name: d?.name, parent: v });
		stRender();
		return;
	}
	if (k == 'bta') {
		if ((arg == 'remove' || arg == 'disconnect') && !stConfirm(key, el)) return;
		const r = await btPost(v.parent, { action: arg, mac: v.mac });
		if (r?.ok && arg == 'remove') { st.pop(); }
		toast(r?.ok ? (arg == 'connect' ? t('bt_connecting') : t('saved')) : `${t('failed')}${r?.error ? ': ' + errorText(r.error, lang) : ''}`);
		stRender();
		return;
	}
	if (k == 'dev') {
		st.push({ view: 'device', cat: v.cat, dev: v.list[+arg], parent: v });
		stRender();
		return;
	}
	if (k == 'act') {
		if (!stConfirm(key, el)) return;
		const r = await fetch('/api/devices', {
			method: 'POST', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ mac: v.dev.mac, action: arg })
		}).then((r) => r.json()).catch(() => null);
		toast(r?.ok ? (arg == 'kick' ? t('kicked') : t('saved')) : `${t('failed')}${r?.error ? ': ' + errorText(r.error, lang) : ''}`);
		if (r?.devices) {
			v.parent.list = r.devices;
			v.dev = r.devices.find((d) => d.mac == v.dev.mac) ?? v.dev;
		}
		stRender();
	}
}

// Bluetooth: the view refreshes itself while it (or a device of it) is open
function btWord(d) {
	if (d.state && d.state.startsWith('failed')) return t('bt_failed');
	if (d.state == 'pairing') return t('bt_pairing');
	if (d.state == 'connecting') return t('bt_connecting');
	if (d.connected) return t('bt_connected');
	return d.paired ? t('bt_paired') : '';
}

// e5-bt-connect's "failed: <reason>"
function btReason(s) {
	const r = s.replace(/^failed:\s*/, '');
	return r == 'notfound' ? t('bt_notfound') : r == 'forgot' ? t('bt_forgot') : r == 'noanswer' ? t('bt_noanswer') : r ? `${t('bt_failed')}: ${r}` : t('bt_failed');
}

async function btPoll(v) {
	while (st.includes(v)) {
		const r = await pageRead('/api/bluetooth', P.settings).catch(() => null);
		if (!st.includes(v)) break;
		if (r) v.bt = r;
		const top = stTop();
		if (top === v || (top?.view == 'btdev' && top.parent === v)) stRender();
		await new Promise((res) => setTimeout(res, 2000));
	}
}

async function btPost(v, body) {
	const r = await fetch('/api/bluetooth', {
		method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
	}).then((r) => r.json()).catch(() => null);
	if (r && r.adapter != null) v.bt = r;
	stRender();
	return r;
}

// keys on the settings page; true = taken
function stKey(kind) {
	const v = stTop();
	if (!v) return false;
	if (kind == 'back' && st.length > 1) {
		stDisarm();
		st.pop();
		stRender();
		const first = document.querySelector('#st-view button');
		if (first) first.focus();
		return true;
	}
	if ((kind == 'left' || kind == 'right') && st.length > 1) {
		// a number being edited: left/right step it; elsewhere below the menu, nothing
		if (v.view == 'edit' && v.item.type == 'number')
			stClick(kind == 'left' ? 'num:-' : 'num:+', null);
		return true;
	}
	return false;
}

on('st-view', 'click', (e) => {
	const b = e.target.closest('button[data-st]');
	if (b) stClick(b.dataset.st, b);
});

/* ---------- apps: plugins ---------- */

let apps = null;
let appOpen = null;               // the manifest of the open plugin
let appKeepAwake = false;
let appCapturePower = false;
let inputTarget = null;           // the last host input focused before an app opened
let inputFrame = null;             // null for a host page, the app iframe for a plugin input
let imeOpen = false;
let imeClosing = false;

function isInputTarget(el) {
	if (!el || !el.tagName) return !!el?.isContentEditable;
	if (el.isContentEditable) return true;
	if (el.tagName != 'INPUT' && el.tagName != 'TEXTAREA') return false;
	const type = (el.type ?? 'text').toLowerCase();
	return ![ 'button', 'checkbox', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit' ].includes(type)
		&& !el.disabled && !el.readOnly;
}

function currentInputTarget() {
	const owner = inputFrame?.contentDocument ?? document;
	if (!isInputTarget(inputTarget) || !owner.documentElement.contains(inputTarget) || inputTarget.hidden) return null;
	if (inputTarget.getClientRects && !inputTarget.getClientRects().length) return null;
	return inputTarget;
}

function notifyInputTarget() {
	if (imeOpen) toIme({ e5: 'input-target', available: !!currentInputTarget() });
	else if (appOpen) toApp({ e5: 'input-target', available: !!currentInputTarget() });
}

function inputEvent(el, inputType, data) {
	let event;
	try { event = new InputEvent('input', { bubbles: true, inputType, data }); }
	catch (_) { event = new Event('input', { bubbles: true }); }
	el.dispatchEvent(event);
}

function insertIntoInput(el, text) {
	if (!text) return true;
	if (el.tagName == 'INPUT' || el.tagName == 'TEXTAREA') {
		const value = String(el.value ?? ''), start = Number.isInteger(el.selectionStart) ? el.selectionStart : value.length;
		const end = Number.isInteger(el.selectionEnd) ? el.selectionEnd : start;
		const room = el.maxLength > 0 ? Math.max(0, el.maxLength - value.length + end - start) : text.length;
		const added = text.slice(0, room);
		el.value = value.slice(0, start) + added + value.slice(end);
		const caret = start + added.length;
		if (el.setSelectionRange) el.setSelectionRange(caret, caret);
		inputEvent(el, 'insertText', added);
		return true;
	}
	if (!el.isContentEditable) return false;
	const selection = window.getSelection();
	if (!selection) return false;
	const range = selection.rangeCount && el.contains(selection.anchorNode)
		? selection.getRangeAt(0) : document.createRange();
	if (!range.commonAncestorContainer || !el.contains(range.commonAncestorContainer)) range.selectNodeContents(el);
	range.deleteContents();
	range.insertNode(document.createTextNode(text));
	range.collapse(false);
	selection.removeAllRanges(); selection.addRange(range);
	inputEvent(el, 'insertText', text);
	return true;
}

function backspaceInput(el) {
	if (el.tagName == 'INPUT' || el.tagName == 'TEXTAREA') {
		const value = String(el.value ?? ''), start = Number.isInteger(el.selectionStart) ? el.selectionStart : value.length;
		const end = Number.isInteger(el.selectionEnd) ? el.selectionEnd : start;
		if (!start && !end) return true;
		let from = start, to = end;
		if (from == to) {
			const before = [...value.slice(0, from)];
			if (!before.length) return true;
			from -= before[before.length - 1].length;
		}
		el.value = value.slice(0, from) + value.slice(to);
		if (el.setSelectionRange) el.setSelectionRange(from, from);
		inputEvent(el, 'deleteContentBackward', null);
		return true;
	}
	if (el.isContentEditable && document.execCommand) {
		document.execCommand('delete');
		inputEvent(el, 'deleteContentBackward', null);
		return true;
	}
	return false;
}

function pluginInput(msg) {
	if (!imeOpen && !appOpen?.input_method) return;
	const target = currentInputTarget();
	let ok = !!target;
	if (ok && msg.action == 'insert') ok = typeof msg.text == 'string' && msg.text.length <= 4096 && insertIntoInput(target, msg.text);
	else if (ok && msg.action == 'backspace') ok = backspaceInput(target);
	else if (msg.action != 'insert' && msg.action != 'backspace') ok = false;
	const result = { e5: 'input-result', ok, error: ok ? undefined : (target ? 'input target rejected the operation' : 'no input target') };
	if (imeOpen) toIme(result); else toApp(result);
}

document.addEventListener('focusin', (event) => {
	if (isInputTarget(event.target)) {
		inputTarget = event.target;
		inputFrame = null;
		notifyInputTarget();
	}
});

async function loadApps() {
	const r = await pageRead('/api/plugins', P.apps).catch(() => null);
	if (!r) return;
	apps = r?.plugins ?? [];
	setHTML('ap-list', apps.length ? apps.map((m, i) =>
		`<button class="strow" data-app="${i}"><span>${esc(lbl(m.name) || m.id)}</span><span class="sv chev">${esc(lbl(m.description) ?? '')}</span></button>`).join('')
		: `<div class="card sub">${esc(t('no_apps'))}</div>`);
}

function openApp(m) {
	if (imeOpen) closeInputMethod();
	const f = $('app-frame');
	appOpen = m;
	appKeepAwake = false;
	appCapturePower = false;
	f.src = `/plugins/${encodeURIComponent(m.id)}/${m.entry ?? 'index.html'}?lang=${lang}`;
	f.hidden = false;
	f.onload = () => { observeAppInputs(f); f.focus(); };
	setText('foot-title', lbl(m.name) || m.id);
	renderNotification();
}

function closeApp() {
	if (imeOpen) closeInputMethod();
	const f = $('app-frame');
	f.hidden = true;
	f.src = 'about:blank';
	appOpen = null;
	appKeepAwake = false;
	appCapturePower = false;
	resetIdle();
	setText('foot-title', t(pages[page].dataset.title));
	renderNotification();
	const b = document.querySelector('[data-app]');
	if (b) b.focus();
}

function toApp(msg) {
	const f = $('app-frame');
	if (appOpen && f.contentWindow) f.contentWindow.postMessage({ e5: msg.e5, ...msg }, '*');
}

function toIme(msg) {
	const f = $('ime-frame');
	if (imeOpen && f.contentWindow) f.contentWindow.postMessage({ e5: msg.e5, ...msg }, '*');
}

function observeAppInputs(frame) {
	const doc = frame.contentDocument;
	if (!doc || doc.__e5InputObserver) return;
	doc.__e5InputObserver = true;
	doc.addEventListener('focusin', (event) => {
		if (!appOpen || frame !== $('app-frame') || appOpen.input_method || imeClosing || !isInputTarget(event.target)) return;
		inputTarget = event.target;
		inputFrame = frame;
		openInputMethod();
	}, true);
}

async function openInputMethod() {
	if (imeOpen || !currentInputTarget() || appOpen?.input_method) return;
	let provider = apps?.find((m) => m.input_method === true);
	if (!provider) {
		const r = await fetch('/api/plugins', { cache: 'no-store' }).then((r) => r.json()).catch(() => null);
		apps = r?.plugins ?? apps ?? [];
		provider = apps.find((m) => m.input_method === true);
	}
	if (!provider || !currentInputTarget()) return;
	const f = $('ime-frame');
	imeOpen = true;
	f.src = `/plugins/${encodeURIComponent(provider.id)}/${provider.entry ?? 'index.html'}?lang=${lang}&ime=1`;
	f.hidden = false;
	f.onload = () => f.focus();
}

function closeInputMethod() {
	if (!imeOpen) return;
	const f = $('ime-frame');
	imeOpen = false;
	f.hidden = true;
	f.src = 'about:blank';
	const target = currentInputTarget();
	imeClosing = true;
	if (target?.focus) target.focus();
	setTimeout(() => { imeClosing = false; }, 100);
}

on('ap-list', 'click', (e) => {
	const b = e.target.closest('[data-app]');
	if (b && apps) openApp(apps[+b.dataset.app]);
});

// the plugin side of the protocol (sdk/e5.js; docs/API.md, "Frontend")
window.addEventListener('message', (e) => {
	const m = e.data;
	const fromIme = imeOpen && e.source === $('ime-frame').contentWindow;
	const fromApp = appOpen && e.source === $('app-frame').contentWindow;
	if ((!fromIme && !fromApp) || !m || typeof m != 'object') return;
	const send = (msg) => fromIme ? toIme(msg) : toApp(msg);
	switch (m.e5) {
	case 'key':                     // every key the plugin sees, for the host's own keys
		if (blank && !['power','volup','voldown'].includes(keyKind(m) || m.kind)) return;
		if (!$('notification-card').hidden && notificationKey(m.kind)) return;
		if (m.key == 'AudioVolumeUp' || m.keyCode == 175 || m.key == 'AudioVolumeDown' || m.keyCode == 174) {
			volumeKey(m.key == 'AudioVolumeUp' || m.keyCode == 175 ? 1 : -1);
			return;
		}
		if (m.kind == 'power' && appCapturePower && !blank && !locked) { resetIdle(); return; }
		if (keyLock(m.kind == 'power' && !m.repeat, m.key == '*')) return;
		if (blank) {
			if (m.kind == 'power' && !m.repeat) { setBlank(false); send({ e5: 'blank', on: false }); }
			return;
		}
		resetIdle();
		if (m.kind == 'menu' && !m.repeat) { if (fromIme) closeInputMethod(); else { closeApp(); showPage(P.apps); } return; }
		if (m.kind == 'power' && !m.repeat) { setBlank(true); send({ e5: 'blank', on: true }); }
		break;
	case 'exit': if (fromIme) closeInputMethod(); else closeApp(); break;
	case 'toast': toast(String(m.text ?? '')); break;
	case 'keep-awake':
		appKeepAwake = !!m.on;
		resetIdle();
		break;
	case 'capture-power': appCapturePower = !!m.on; break;
	case 'input': pluginInput(m); break;
	case 'ready':
		send({ e5: 'hello', lang, api_version: 2, blank, tz_offset: last?.tz_offset ?? 0, touch: !touchOff(), input_available: !!currentInputTarget() });
		break;
	}
});

/* ---------- actions ---------- */

on('hs-toggle', 'click', async () => {
	if (!last) return;
	const on = !(wifiPending ?? last.wifi.enabled);
	wifiPending = on;
	toast(on ? t('turning_on') : t('turning_off'));
	renderHotspot(last);
	const r = await post('wifi', { on });
	if (!r?.ok) {
		wifiPending = null;
		toast(`${t('failed')}${r?.error ? ': ' + errorText(r.error, lang) : ''}`);
	}
	setTimeout(poll, 1500);
});

on('hs-showkey', 'click', async () => {
	showKey = !showKey;
	$('hs-showkey').textContent = showKey ? t('hide_key') : t('show_key');
	if (!showKey) {
		setText('hs-key', '');
		return;
	}
	const r = await fetch('/api/wifi-key', { cache: 'no-store' }).then((r) => r.json()).catch(() => null);
	setText('hs-key', r?.key ?? '');
});

function stepBrightness(d) {
	brightness = Math.max(10, Math.min(255, brightness + d));
	post('backlight', { level: brightness, save: true });
	if (last) renderDevice(last);
}
on('dv-dim', 'click', () => stepBrightness(-25));
on('dv-bright', 'click', () => stepBrightness(25));

on('dv-reconnect', 'click', async () => {
	toast(t('reconnecting'));
	await post('wan-reconnect');
	setTimeout(poll, 3000);
});

/* ---------- start ---------- */

// the page and this script must be the same version: if an element the
// script needs is missing, load the page once more past the cache
if ((!$('pic') || !$('update-card')) && !sessionStorage.getItem('e5-reloaded')) {
	sessionStorage.setItem('e5-reloaded', '1');
	location.reload();
} else {
	sessionStorage.removeItem('e5-reloaded');
	applyLang();
	showPage(0);
	poll();
}


/* ---------- generic plugin notifications ---------- */
function notificationCheck(list) {
 notificationList = list;
 const keys = new Set(list.map(n => n.plugin + '/' + n.id));
 for (const k of notificationDismissed) if (!keys.has(k)) notificationDismissed.delete(k);
 const fresh = list.find(n => !notificationSeen.has(n.plugin + '/' + n.id));
 notificationSeen = keys;
 if (fresh && fresh.wake && !locked && blank) setBlank(false);
 renderNotification();
}
function renderNotification() {
 const n = notificationList.find(n => !notificationDismissed.has(n.plugin + '/' + n.id) && appOpen?.id !== n.plugin);
 notificationCurrent = n ?? null;
 $('notification-card').hidden = !n || blank || locked || picShown;
 toApp({ e5: 'input-blocked', on: !$('notification-card').hidden });
 toIme({ e5: 'input-blocked', on: !$('notification-card').hidden });
 setText('bar-notifications', notificationList.length ? '• ' + notificationList.length : '');
 if (!n) return;
 setText('notification-title', lbl(n.title) || t('notifications'));
 setText('notification-body', n.body || '');
 setText('notification-open', t('notification_open'));
 setText('notification-later', t('notification_later'));
}
function dismissNotification() {
 if (notificationCurrent) notificationDismissed.add(notificationCurrent.plugin + '/' + notificationCurrent.id);
 renderNotification();
}
function notificationKey(kind) {
 if (kind == 'up' || kind == 'left') { $('notification-open').focus(); return true; }
 if (kind == 'down' || kind == 'right') { $('notification-later').focus(); return true; }
 if (kind == 'ok') { pressKey(document.activeElement === $('notification-later') ? $('notification-later') : $('notification-open')); return true; }
 if (kind == 'back') { dismissNotification(); return true; }
 return false;
}
on('notification-later', 'click', dismissNotification);
on('notification-open', 'click', async () => {
 const n = notificationCurrent;
 if (!n) return;
 const response = await fetch('/api/plugins', { cache: 'no-store' }).then(r => r.json()).catch(() => null);
 const m = response?.plugins?.find(m => m.id === n.plugin);
 if (m) { if (appOpen) closeApp(); openApp(m); renderNotification(); }
});
