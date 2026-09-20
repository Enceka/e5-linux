/*
 * UFI-TOOLS for Linux -- frontend shim.
 *
 * The web UI that ships with UFI-TOOLS was written for a ZTE hotspot: it logs in
 * with a vendor password and offers panels for features a Linux device does not
 * have (APK updates, wireless adb, NFC, SMS, band/cell lock, vendor APN).
 *
 * This file adapts that UI in place, without forking it:
 *
 *   1. the vendor password field is filled and hidden, so the UFI-TOOLS token is
 *      the only credential;
 *   2. panels that cannot work here are hidden, so nothing is a dead button;
 *   3. a self-contained "E5 控制台" panel is added, wired to the native
 *      /api/linux/* endpoints that actually drive this device.
 *
 * It is injected by ufitools.app into index.html and served as a static overlay,
 * so the upstream frontend stays untouched and can be updated independently.
 */
(function () {
    'use strict';

    // Vendor password the login form insists on; the backend accepts anything
    // here because the request is already authenticated by the UFI-TOOLS token.
    var PLACEHOLDER_PASSWORD = 'e5-linux';

    // Panels that have no counterpart on this device.  Hiding them beats
    // leaving buttons that can only fail.
    var HIDDEN_BUTTONS = [
        'ADB',            // 有线 ADB（Android 专有）
        'ADB_NET',        // 无线 ADB 自启（Android 专有）
        'APNManagement',  // APN 由 modem 承载，走 AT+CGDCONT
        'CHANGEPWD',      // 厂商后台密码不存在
        'LANManagement',  // 内网地址由 systemd-networkd 拥有（状态仍在首页显示）
        'NFC',            // 本机无 NFC
        'OTA',            // 无 APK 更新通道
        'SMS'             // 本机无短信栈（转发功能仍可用）
    ];

    var CSS = [
        '#ufi-linux-fab{position:fixed;right:16px;bottom:16px;z-index:99998;width:52px;height:52px;',
        'border-radius:50%;border:none;background:linear-gradient(135deg,#3d5afe,#00bfa5);color:#fff;',
        'font-size:13px;font-weight:700;box-shadow:0 6px 20px rgba(0,0,0,.45);cursor:pointer}',
        '#ufi-linux-fab:hover{filter:brightness(1.1)}',
        '#ufi-linux-panel{position:fixed;right:16px;bottom:80px;z-index:99999;width:min(420px,calc(100vw - 32px));',
        'max-height:min(72vh,720px);overflow:auto;background:var(--bg-color,#16181d);color:var(--font-color,#eee);',
        'border:1px solid rgba(255,255,255,.15);border-radius:14px;padding:14px;display:none;',
        'box-shadow:0 12px 40px rgba(0,0,0,.5);font-size:13px;line-height:1.5}',
        '#ufi-linux-panel.ufi-open{display:block}',
        '#ufi-linux-panel h3{margin:0 0 10px;font-size:15px;display:flex;justify-content:space-between;align-items:center}',
        '#ufi-linux-panel h4{margin:14px 0 6px;font-size:13px;opacity:.75;font-weight:600}',
        '.ufi-row{display:flex;justify-content:space-between;gap:10px;padding:2px 0}',
        '.ufi-row span:first-child{opacity:.7}',
        '.ufi-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}',
        '.ufi-actions button{padding:6px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.2);',
        'background:rgba(255,255,255,.08);color:inherit;cursor:pointer;font-size:12px}',
        '.ufi-actions button:hover{background:rgba(255,255,255,.16)}',
        '.ufi-actions button.ufi-danger{border-color:rgba(255,90,90,.6);color:#ff8a80}',
        '.ufi-field{display:flex;align-items:center;gap:6px;margin:4px 0}',
        '.ufi-field label{flex:0 0 84px;opacity:.75}',
        '.ufi-field input{flex:1;min-width:0;padding:5px 8px;border-radius:6px;border:1px solid rgba(255,255,255,.2);',
        'background:rgba(0,0,0,.25);color:inherit}',
        '.ufi-list{margin-top:6px;font-size:12px}',
        '.ufi-list div{padding:3px 0;border-bottom:1px solid rgba(255,255,255,.08);display:flex;gap:8px}',
        '.ufi-list span:first-child{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        '.ufi-hint{opacity:.6;font-size:12px;margin-top:8px}',
        '.ufi-badge{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;',
        'background:rgba(255,255,255,.12)}',
        '.ufi-badge.ufi-on{background:rgba(0,200,120,.25);color:#7CFFC4}',
        '.ufi-badge.ufi-off{background:rgba(255,90,90,.2);color:#ffb0b0}',
        '#ufi-linux-toast{position:fixed;left:50%;bottom:96px;transform:translateX(-50%);z-index:100000;',
        'padding:8px 16px;border-radius:8px;background:rgba(0,0,0,.82);color:#fff;font-size:13px;display:none}'
    ].join('');

    function injectCss() {
        if (document.getElementById('ufi-linux-style')) { return; }
        var style = document.createElement('style');
        style.id = 'ufi-linux-style';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function toast(message, isError) {
        var el = document.getElementById('ufi-linux-toast');
        if (!el) {
            el = document.createElement('div');
            el.id = 'ufi-linux-toast';
            document.body.appendChild(el);
        }
        el.textContent = message;
        el.style.background = isError ? 'rgba(150,20,20,.9)' : 'rgba(0,0,0,.82)';
        el.style.display = 'block';
        clearTimeout(el._timer);
        el._timer = setTimeout(function () { el.style.display = 'none'; }, 3200);
    }

    function authorization() {
        try {
            // main.js stores the SHA-256 of the token, which is exactly what the
            // Authorization header expects.
            return localStorage.getItem('kano_sms_token') || '';
        } catch (e) {
            return '';
        }
    }

    // requests.js wraps window.fetch globally and adds kano-t / kano-sign, so the
    // shim only has to supply the token.
    function api(path, options) {
        options = options || {};
        var headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
        var token = authorization();
        if (token) { headers.authorization = token; }
        return fetch(path, Object.assign({}, options, { headers: headers })).then(function (response) {
            if (response.status === 401) {
                throw new Error('未登录：请先在上方登录一次');
            }
            return response.json().then(function (data) {
                if (!response.ok) {
                    throw new Error((data && data.error) || ('HTTP ' + response.status));
                }
                return data;
            });
        });
    }

    // -- 1. make the login form work with the UFI-TOOLS token only -----------
    function adaptLoginForm() {
        var input = document.querySelector('#PWDINPUT');
        if (input) {
            if (!input.value) { input.value = PLACEHOLDER_PASSWORD; }
            input.setAttribute('placeholder', '无需填写（Linux 端无厂商密码）');
        }
        var label = document.querySelector('#token_div_label2');
        if (label) { label.style.display = 'none'; }
        var block = document.querySelector('#PWD_BLK');
        if (block) { block.style.display = 'none'; }
    }

    // -- 2. hide what cannot work ------------------------------------------
    function hideUnsupported(capabilities) {
        HIDDEN_BUTTONS.forEach(function (id) {
            var el = document.getElementById(id);
            if (el) { el.style.display = 'none'; }
        });
        // File sharing only exists when a samba unit is configured.
        var smb = document.getElementById('SMB');
        if (smb && !capabilities.samba_unit) { smb.style.display = 'none'; }
    }

    function loadCapabilities() {
        return api('/api/platform').catch(function () {
            return { samba_unit: '' };
        });
    }

    // -- 3. the native console ---------------------------------------------
    var refreshTimer = null;

    function badge(on, textOn, textOff) {
        return '<span class="ufi-badge ' + (on ? 'ufi-on' : 'ufi-off') + '">' +
            (on ? textOn : textOff) + '</span>';
    }

    function humanBytes(value) {
        var units = ['B', 'KB', 'MB', 'GB', 'TB'];
        var size = Number(value) || 0;
        var index = 0;
        while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
        return (index === 0 ? size : size.toFixed(2)) + ' ' + units[index];
    }

    function humanUptime(seconds) {
        var total = Number(seconds) || 0;
        var days = Math.floor(total / 86400);
        var hours = Math.floor((total % 86400) / 3600);
        var minutes = Math.floor((total % 3600) / 60);
        if (days) { return days + ' 天 ' + hours + ' 小时'; }
        if (hours) { return hours + ' 小时 ' + minutes + ' 分'; }
        return minutes + ' 分';
    }

    function row(label, value) {
        return '<div class="ufi-row"><span>' + label + '</span><span>' + value + '</span></div>';
    }

    function render(data) {
        var panel = document.getElementById('ufi-linux-body');
        if (!panel) { return; }
        var mobile = data.mobile_data || {};
        var hotspot = data.hotspot || {};
        var perf = data.performance || {};
        var led = data.led || {};
        var rate = (data.traffic || {}).rate || { rx_bps: 0, tx_bps: 0 };
        var clients = data.clients || [];
        var battery = data.battery || {};
        var thermal = data.thermal || {};
        var modem = data.modem || {};

        var html = '';
        html += '<h4>本机</h4>';
        html += row('型号', data.model || '-');
        html += row('开机时长', humanUptime(data.uptime));
        html += row('内存占用', ((data.memory || {}).used_percent || 0) + ' %');
        html += row('温度', (thermal.max >= 0 ? (thermal.max / 1000).toFixed(1) + ' °C' : '-'));
        html += row('电量', (battery.percent >= 0 ? battery.percent + ' %' :
            '-') + (battery.status ? ' (' + battery.status + ')' : ''));

        html += '<h4>蜂窝网络</h4>';
        html += row('数据链接', badge(mobile.connected, '已连接', '未连接') +
            ' <span class="ufi-badge">' + (mobile.interface || '-') + '</span>');
        html += row('地址', mobile.lan_ipaddr || '-');
        html += row('网络制式', (modem.network_type || '-') +
            (modem.network_provider ? ' / ' + modem.network_provider : ''));
        html += row('信号', (modem.lte_rsrp ? modem.lte_rsrp + ' dBm' : '-') +
            (modem.network_signalbar !== undefined ? ' (' + modem.network_signalbar + '/5)' : ''));
        html += row('实时速率', '↓ ' + humanBytes(rate.rx_bps) + '/s ↑ ' + humanBytes(rate.tx_bps) + '/s');
        html += row('当日 / 本月', humanBytes((data.traffic || {}).daily_bytes) + ' / ' +
            humanBytes((data.traffic || {}).monthly_bytes));
        html += '<div class="ufi-actions">' +
            '<button onclick="ufiLinux.mobileData(' + (mobile.connected ? 'false' : 'true') + ')">' +
            (mobile.connected ? '断开数据' : '连接数据') + '</button>' +
            '<button onclick="ufiLinux.show("api/at/status")">AT 通道状态</button>' +
            '</div>';

        html += '<h4>Wi-Fi 热点</h4>';
        html += row('状态', badge(hotspot.active, '运行中', '已停止'));
        html += row('SSID', hotspot.ssid || '-');
        html += row('信道 / 模式', (hotspot.channel || '-') + ' / ' + (hotspot.hw_mode || '-'));
        html += row('加密', hotspot.auth || '-');
        html += row('客户端', clients.length + ' 台');
        html += '<div class="ufi-field"><label>SSID</label><input id="ufi-ssid" value="' +
            escapeAttr(hotspot.ssid || '') + '"></div>';
        html += '<div class="ufi-field"><label>密码</label><input id="ufi-psk" value="' +
            escapeAttr(hotspot.psk || '') + '"></div>';
        html += '<div class="ufi-field"><label>信道</label><input id="ufi-channel" value="' +
            escapeAttr(hotspot.channel || '') + '"></div>';
        html += '<div class="ufi-field"><label>最大接入</label><input id="ufi-max" value="' +
            escapeAttr(hotspot.max_clients || '') + '"></div>';
        html += '<div class="ufi-actions">' +
            '<button onclick="ufiLinux.hotspotToggle(' + (hotspot.active ? 'false' : 'true') + ')">' +
            (hotspot.active ? '停止热点' : '启动热点') + '</button>' +
            '<button onclick="ufiLinux.hotspotSave()">保存并重启热点</button>' +
            '</div>';

        if (clients.length) {
            html += '<h4>接入设备</h4><div class="ufi-list">';
            clients.forEach(function (client) {
                html += '<div><span>' + escapeHtml(client.hostname || client.mac_addr) + '</span>' +
                    '<span>' + escapeHtml(client.ip_addr || '-') + '</span>' +
                    '<span>' + escapeHtml(client.mac_addr || '') + '</span></div>';
            });
            html += '</div>';
        }

        html += '<h4>系统</h4>';
        html += row('性能模式', badge(perf.performance, '已开启', '已关闭') +
            (perf.governor ? ' <span class="ufi-badge">' + perf.governor + '</span>' : ''));
        html += row('指示灯', badge(led.supported, '可控', '本机不可控'));
        html += '<div class="ufi-actions">' +
            '<button onclick="ufiLinux.performance(' + (!perf.performance) + ')">' +
            (perf.performance ? '关闭性能模式' : '开启性能模式') + '</button>' +
            '<button onclick="ufiLinux.led(' + (true) + ')">点亮指示灯</button>' +
            '<button onclick="ufiLinux.led(false)">关闭指示灯</button>' +
            '<button class="ufi-danger" onclick="ufiLinux.power(\'reboot\')">重启设备</button>' +
            '<button class="ufi-danger" onclick="ufiLinux.power(\'poweroff\')">关闭电源</button>' +
            '</div>';
        html += '<div class="ufi-hint">数据来自本机 /proc、/sys、systemd 与 modem；' +
            '信号类字段按 AT 轮询间隔（默认 60 秒）刷新，以免压垮基带。</div>';

        panel.innerHTML = html;
    }

    function escapeHtml(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function escapeAttr(text) {
        return escapeHtml(text).replace(/"/g, '&quot;');
    }

    function reload() {
        return api('/api/linux/overview').then(render).catch(function (error) {
            toast(error.message, true);
        });
    }

    function buildConsole() {
        if (document.getElementById('ufi-linux-fab')) { return; }
        var fab = document.createElement('button');
        fab.id = 'ufi-linux-fab';
        fab.type = 'button';
        fab.title = 'E5 设备控制台';
        fab.textContent = 'E5';
        fab.onclick = function () {
            var panel = document.getElementById('ufi-linux-panel');
            var open = panel.classList.toggle('ufi-open');
            if (open) {
                reload();
                refreshTimer = setInterval(reload, 3000);
            } else {
                clearInterval(refreshTimer);
                refreshTimer = null;
            }
        };
        document.body.appendChild(fab);

        var panel = document.createElement('div');
        panel.id = 'ufi-linux-panel';
        panel.innerHTML = '<h3>E5 设备控制台' +
            '<button class="btn" style="padding:2px 10px" onclick="ufiLinux.close()">关闭</button></h3>' +
            '<div id="ufi-linux-body">正在读取…</div>';
        document.body.appendChild(panel);
    }

    function showRaw(title, payload) {
        var panel = document.getElementById('ufi-linux-body');
        if (!panel) { return; }
        panel.innerHTML = '<h4>' + escapeHtml(title) + '</h4><pre style="white-space:pre-wrap;' +
            'font-size:11px;max-height:50vh;overflow:auto">' +
            escapeHtml(JSON.stringify(payload, null, 2)) + '</pre>' +
            '<div class="ufi-actions"><button onclick="ufiLinux.refresh()">返回</button></div>';
    }

    window.ufiLinux = {
        refresh: reload,
        close: function () {
            var panel = document.getElementById('ufi-linux-panel');
            if (panel) { panel.classList.remove('ufi-open'); }
            clearInterval(refreshTimer);
            refreshTimer = null;
        },
        power: function (action) {
            if (!window.confirm(action === 'reboot' ? '确认重启设备？' : '确认关闭电源？')) { return; }
            api('/api/linux/power', { method: 'POST', body: JSON.stringify({ action: action }) })
                .then(function () { toast(action === 'reboot' ? '正在重启…' : '正在关机…'); })
                .catch(function (error) { toast(error.message, true); });
        },
        mobileData: function (enabled) {
            api('/api/linux/mobile-data', { method: 'POST', body: JSON.stringify({ enabled: enabled }) })
                .then(function () { toast(enabled ? '正在连接数据…' : '正在断开数据…'); return reload(); })
                .catch(function (error) { toast(error.message, true); });
        },
        hotspotToggle: function (enabled) {
            api('/api/linux/hotspot', { method: 'POST', body: JSON.stringify({ enabled: enabled }) })
                .then(function () { toast(enabled ? '正在启动热点…' : '热点已停止'); return reload(); })
                .catch(function (error) { toast(error.message, true); });
        },
        hotspotSave: function () {
            var body = {
                ssid: value('ufi-ssid'),
                psk: value('ufi-psk'),
                channel: value('ufi-channel'),
                max_clients: value('ufi-max')
            };
            if (!body.ssid) { toast('SSID 不能为空', true); return; }
            if (body.psk && body.psk.length < 8) { toast('密码至少 8 位', true); return; }
            api('/api/linux/hotspot', { method: 'POST', body: JSON.stringify(body) })
                .then(function () { toast('已保存，热点正在重启'); return reload(); })
                .catch(function (error) { toast(error.message, true); });
        },
        performance: function (enabled) {
            api('/api/linux/performance', { method: 'POST', body: JSON.stringify({ performance: enabled }) })
                .then(function () { toast(enabled ? '已切到性能模式' : '已切回省电调速'); return reload(); })
                .catch(function (error) { toast(error.message, true); });
        },
        led: function (enabled) {
            api('/api/linux/led', { method: 'POST', body: JSON.stringify({ enabled: enabled }) })
                .then(function () { toast('已下发指示灯状态'); return reload(); })
                .catch(function (error) { toast(error.message, true); });
        },
        show: function (path) {
            api('/api/' + path.replace(/^\/?api\//, ''))
                .then(function (payload) { showRaw(path, payload); })
                .catch(function (error) { toast(error.message, true); });
        }
    };

    function value(id) {
        var el = document.getElementById(id);
        return el ? el.value.trim() : '';
    }



    function boot() {
        injectCss();
        adaptLoginForm();
        loadCapabilities().then(hideUnsupported);
        buildConsole();
        // The login dialog is re-rendered when the language changes, so keep the
        // form adapted afterwards too.
        setInterval(adaptLoginForm, 2000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
