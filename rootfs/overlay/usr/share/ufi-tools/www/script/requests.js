function SHA256(e) { function t(e, t) { var n = (65535 & e) + (65535 & t); return (e >> 16) + (t >> 16) + (n >> 16) << 16 | 65535 & n } function n(e, t) { return e >>> t | e << 32 - t } function r(e, t) { return e >>> t } function o(e, t, n) { return e & t ^ ~e & n } function i(e, t, n) { return e & t ^ e & n ^ t & n } function a(e) { return n(e, 2) ^ n(e, 13) ^ n(e, 22) } function s(e) { return n(e, 6) ^ n(e, 11) ^ n(e, 25) } function c(e) { return n(e, 7) ^ n(e, 18) ^ r(e, 3) } function u(e) { return n(e, 17) ^ n(e, 19) ^ r(e, 10) } var l = 8, d = 1; return e = function (e) { e = e.replace(/\\r\\n/g, "\\n"); for (var t = "", n = 0; n < e.length; n++) { var r = e.charCodeAt(n); r < 128 ? t += String.fromCharCode(r) : r > 127 && r < 2048 ? (t += String.fromCharCode(r >> 6 | 192), t += String.fromCharCode(63 & r | 128)) : (t += String.fromCharCode(r >> 12 | 224), t += String.fromCharCode(r >> 6 & 63 | 128), t += String.fromCharCode(63 & r | 128)) } return t }(e), function (e) { for (var t = d ? "0123456789ABCDEF" : "0123456789abcdef", n = "", r = 0; r < 4 * e.length; r++)n += t.charAt(e[r >> 2] >> 8 * (3 - r % 4) + 4 & 15) + t.charAt(e[r >> 2] >> 8 * (3 - r % 4) & 15); return n }(function (e, n) { var r, l, d, p, h, f, m, g, _, b, v, $, S = new Array(1116352408, 1899447441, 3049323471, 3921009573, 961987163, 1508970993, 2453635748, 2870763221, 3624381080, 310598401, 607225278, 1426881987, 1925078388, 2162078206, 2614888103, 3248222580, 3835390401, 4022224774, 264347078, 604807628, 770255983, 1249150122, 1555081692, 1996064986, 2554220882, 2821834349, 2952996808, 3210313671, 3336571891, 3584528711, 113926993, 338241895, 666307205, 773529912, 1294757372, 1396182291, 1695183700, 1986661051, 2177026350, 2456956037, 2730485921, 2820302411, 3259730800, 3345764771, 3516065817, 3600352804, 4094571909, 275423344, 430227734, 506948616, 659060556, 883997877, 958139571, 1322822218, 1537002063, 1747873779, 1955562222, 2024104815, 2227730452, 2361852424, 2428436474, 2756734187, 3204031479, 3329325298), y = new Array(1779033703, 3144134277, 1013904242, 2773480762, 1359893119, 2600822924, 528734635, 1541459225), C = new Array(64); e[n >> 5] |= 128 << 24 - n % 32, e[15 + (n + 64 >> 9 << 4)] = n; for (var _ = 0; _ < e.length; _ += 16) { r = y[0], l = y[1], d = y[2], p = y[3], h = y[4], f = y[5], m = y[6], g = y[7]; for (var b = 0; b < 64; b++)C[b] = b < 16 ? e[b + _] : t(t(t(u(C[b - 2]), C[b - 7]), c(C[b - 15])), C[b - 16]), v = t(t(t(t(g, s(h)), o(h, f, m)), S[b]), C[b]), $ = t(a(r), i(r, l, d)), g = m, m = f, f = h, h = t(p, v), p = d, d = l, l = r, r = t(v, $); y[0] = t(r, y[0]), y[1] = t(l, y[1]), y[2] = t(d, y[2]), y[3] = t(p, y[3]), y[4] = t(h, y[4]), y[5] = t(f, y[5]), y[6] = t(m, y[6]), y[7] = t(g, y[7]) } return y }(function (e) { for (var t = Array(), n = (1 << l) - 1, r = 0; r < e.length * l; r += l)t[r >> 5] |= (e.charCodeAt(r / l) & n) << 24 - r % 32; return t }(e), e.length * l)) }
function gsmEncode(text) { function encodeText(text) { let encoded = []; for (let i = 0; i < text.length; i++) { const char = text[i]; const codePoint = char.codePointAt(0); if (codePoint <= 0xFFFF) { encoded.push((codePoint >> 8) & 0xFF); encoded.push(codePoint & 0xFF) } else { const highSurrogate = 0xD800 + ((codePoint - 0x10000) >> 10); const lowSurrogate = 0xDC00 + ((codePoint - 0x10000) & 0x3FF); encoded.push((highSurrogate >> 8) & 0xFF); encoded.push(highSurrogate & 0xFF); encoded.push((lowSurrogate >> 8) & 0xFF); encoded.push(lowSurrogate & 0xFF) } } return encoded } function toHexString(byteArray) { return byteArray.map(byte => byte.toString(16).padStart(2, '0')).join('') } const encodedBytes = encodeText(text); return toHexString(encodedBytes) }
// 本机 API 前缀：前端与后台同源，固定用相对路径。
let KANO_baseURL = '/api'
let KANO_TOKEN = null
let ACCEPT_TERMS = false

const originFetch = window.fetch;

// 包装fetch
(() => {
    const of = window.fetch;

    function hmacSignature(secret, data) {
        const hmacMd5 = CryptoJS.HmacMD5(data, secret);
        const hmacMd5Bytes = CryptoJS.enc.Hex.parse(hmacMd5.toString());

        const mid = Math.floor(hmacMd5Bytes.sigBytes / 2);
        const part1 = CryptoJS.lib.WordArray.create(hmacMd5Bytes.words.slice(0, mid / 4), mid);
        const part2 = CryptoJS.lib.WordArray.create(hmacMd5Bytes.words.slice(mid / 4), mid);

        const sha1 = CryptoJS.SHA256(part1);
        const sha2 = CryptoJS.SHA256(part2);
        const finalHash = CryptoJS.SHA256(sha1.concat(sha2));

        return finalHash.toString(CryptoJS.enc.Hex);
    }

    window.fetch = async (input, init = {}) => {
        const headers = new Headers(init.headers || {});
        const t = Date.now();
        const method = (init.method || 'GET').toUpperCase();

        //无感验证anyProxy
        if (input.startsWith('/api/proxy')) {
            let _token = common_headers.authorization
            if (!_token) {
                _token = localStorage.getItem('kano_sms_token')
            }
            if (_token) {
                headers.set('authorization', _token)
            }
        }

        // 提取纯路径（不含 query）
        let urlPath = '';
        try {
            const url = new URL(input, window.location.origin);
            urlPath = url.pathname;
        } catch (e) {
            console.warn('无效的URL:', input);
            urlPath = input; // fallback
        }
        // 没啥用，只是起到混淆作用
        const signature = hmacSignature('minikano_kOyXz0Ciz4V7wR0IeKmJFYFQ20jd', 'minikano' + method + urlPath + t);

        headers.set('kano-t', t);
        headers.set('kano-sign', signature);

        const newInit = {
            ...init,
            headers,
        };
        return of(input, newInit);
    };
})();

// 请求头：唯一凭据是 UFI-TOOLS 口令（Authorization），
// 不存在厂商后台，也不存在会话 Cookie。
const common_headers = {
    "referer": KANO_baseURL + '/index.html',
    "host": KANO_baseURL,
    "origin": KANO_baseURL,
    "authorization": KANO_TOKEN
}

// 确保已授权。返回真值表示可以继续请求，null 表示没有口令或口令不被接受。
// 调用方（main.js）把它当作“确保已登录”，名字沿用 login()。
const login = async () => {
    const TOKEN = KANO_TOKEN || localStorage.getItem('kano_sms_token') || ''
    if (isNeedToken && !TOKEN) return null
    KANO_TOKEN = TOKEN || ''
    common_headers.authorization = KANO_TOKEN
    try {
        // 任意一个需要鉴权的接口都能当探针；这里用最轻的一个。
        const res = await fetchWithTimeout(KANO_baseURL + '/is_weak_token', {}, 5000)
        return res.ok ? true : null
    } catch {
        return null
    }
}

// 字段读取：后端按前端沿用的字段名返回本机真实状态。
const getData = async (data = new URLSearchParams({})) => {
    data.append('_', Date.now())
    const res = await fetchWithTimeout(KANO_baseURL + "/ui/fields?" + data.toString(), {}, 5000)
    return await res.json()
}

// 动作下发：action 名由后端路由到 systemd / hostapd / sysfs。
// 第一个参数保留给调用方传“登录结果”，这里只用来判断是否已授权。
const postData = async (session, data = {}) => {
    if (!session) {
        return new Response(JSON.stringify({ error: '未登录或口令无效' }), {
            status: 401,
            headers: { 'Content-Type': 'application/json' }
        })
    }
    const body = new URLSearchParams(data)
    return await fetchWithTimeout(KANO_baseURL + "/ui/action", {
        method: "POST",
        body
    })
}

const reboot = async (session) => {
    return await postData(session, {
        action: 'REBOOT_DEVICE',
    })
}

// 短信：本机没有短信栈，后端会明确返回“本机不支持短信”。
// 保留调用入口是为了让面板给出真实原因，而不是静默失败。
const sendSms_UFI = async ({ content, number }) => {
    if (!content) throw new Error('请提供短信内容')
    if (!number) throw new Error('请提供手机号')
    const res = await postData(await login(), {
        action: 'SEND_SMS',
        Number: number,
        MessageBody: gsmEncode(content)
    })
    return await res.json()
}

//删除短信
const removeSmsById = async (id) => {
    if (!id) throw new Error('请提供短信id')
    const res = await postData(await login(), {
        action: 'DELETE_SMS',
        msg_id: id,
        notCallback: true,
    })
    return await res.json()
}

// 已读短信
const readSmsByIds = async (ids) => {
    if (!ids || !Array.isArray(ids) || ids.length === 0) {
        throw new Error('请提供短信id数组');
    }

    const session = await login();
    const results = [];

    for (const id of ids) {
        try {
            const response = await postData(session, {
                action: 'SET_MSG_READ',
                msg_id: id,
                notCallback: true,
            });

            const data = await response.json();
            results.push({ id, success: data?.result == 'success', data });
        } catch (err) {
            console.error(`处理短信 ID ${id} 时出错:`, err);
            results.push({ id, success: false, error: err.message || String(err) });
        }
    }

    return results;
};

// 短信列表：本机没有短信栈，后端返回空列表。
const getSmsInfo = async () => {
    return await getData(new URLSearchParams({
        cmd: 'sms_data_total',
        multi_data: 1
    }))
}

const getUFIData = async () => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000); // 5秒超时

    try {
        const params = new URLSearchParams();
        params.append('_', Date.now().toString());

        const cmd = 'usb_port_switch,battery_charging,sms_received_flag,sms_unread_num,sms_sim_unread_num,sim_msisdn,dual_sim_support,sim_slot,data_volume_limit_switch,battery_value,battery_vol_percent,network_signalbar,network_rssi,cr_version,iccid,imei,imsi,ipv6_wan_ipaddr,lan_ipaddr,mac_address,msisdn,network_information,Lte_ca_status,rssi,Z5g_rsrp,lte_rsrp,wifi_access_sta_num,loginfo,data_volume_alert_percent,data_volume_limit_size,realtime_rx_thrpt,realtime_tx_thrpt,realtime_time,monthly_tx_bytes,monthly_rx_bytes,monthly_time,network_type,network_provider,ppp_status';

        const res = await fetch(`${KANO_baseURL}/ui/fields?multi_data=1&cmd=${cmd}&${params.toString()}`, {
            headers: {
                ...common_headers
            },
            signal: controller.signal
        });

        const resData = await res.json()

        //本机自身信息（CPU/内存/温度/存储/流量等）
        let deviceInfo = {}
        try {
            deviceInfo = await (await fetch(`${KANO_baseURL}/baseDeviceInfo`, { headers: { ...common_headers } })).json()
        } catch {/*没有，不处理*/ }

        //部分实现只上报 sim_msisdn
        if (!resData.msisdn) {
            resData.msisdn = resData.sim_msisdn
        }

        return {
            ...resData,
            ...deviceInfo,
            //电量字段二选一
            battery: resData?.battery_value ? resData.battery_value : resData?.battery_vol_percent ? resData.battery_vol_percent : deviceInfo.battery,
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            console.warn('请求超时');
        } else {
            console.error('请求失败', error);
        }
        return null;
    } finally {
        clearTimeout(timeoutId); // 清理定时器
    }
};


function originFetchWithTimeout(url = '', options = {}, timeout = 10000) {
    const controller = new AbortController()
    const tid = setTimeout(() => controller.abort(), timeout);
    return originFetch(url, {
        ...options,
        signal: controller.signal,
    })
        .then(response => {
            // 处理响应
            return response
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                console.error('请求超时')
            } else {
                console.error('请求失败', err)
            }
            throw err
        }).finally(() => {
            clearTimeout(tid)
        })
}




function fetchWithTimeout(url = '', options = {}, timeout = 10000) {
    const controller = new AbortController()
    const tid = setTimeout(() => controller.abort(), timeout);
    return fetch(url, {
        ...options,
        signal: controller.signal,
        headers: { ...common_headers }
    })
        .then(response => {
            // 处理响应
            return response
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                console.error('请求超时')
            } else {
                console.error('请求失败', err)
            }
            throw err
        }).finally(() => {
            clearTimeout(tid)
        })
}

//查流量使用情况
async function getDataUsage() {
    try {
        const res = await getData(new URLSearchParams({
            cmd: 'flux_data_volume_limit_switch,data_volume_limit_switch,data_volume_limit_unit,data_volume_limit_size,data_volume_alert_percent,monthly_tx_bytes,monthly_rx_bytes,monthly_time,wan_auto_clear_flow_data_switch,traffic_clear_date,',
            multi_data: 1
        }))
        return res
    } catch {
        return null
    }
}

//自定义头部
const getCustomHead = async () => {
    try {
        const { text } = await (await fetchWithTimeout(`${KANO_baseURL}/get_custom_head`, {
            headers: { ...common_headers }
        })).json()
        return text || ''
    } catch (e) {
        return '';
    }
}
const setCustomHead = async (text = "") => {
    try {
        const { result, error } = await (await fetchWithTimeout(`${KANO_baseURL}/set_custom_head`, {
            headers: { ...common_headers },
            method: "POST",
            body: JSON.stringify({
                text: text
            })
        })).json()
        return {
            result, error
        }
    } catch (e) {
        return false
    }
}

//rootShell
const runShellWithRoot = async (cmd = '', timeout = 10000) => {
    try {
        const res = await fetchWithTimeout(`${KANO_baseURL}/root_shell`, {
            method: "POST",
            headers: common_headers,
            body: JSON.stringify({
                command: cmd.trim(),
                timeout
            })
        }, timeout)
        const { result, error } = await res.json()
        return error ? { success: false, content: error } : { success: true, content: result }
    } catch (e) {
        return { success: false, content: e.message }
    }
}

//userShell
const runShellWithUser = async (cmd = '', timeout = 10000) => {
    try {
        const res = await fetchWithTimeout(`${KANO_baseURL}/user_shell`, {
            method: "POST",
            headers: common_headers,
            body: JSON.stringify({
                command: cmd.trim()
            })
        }, timeout)
        const { result, error } = await res.json()
        return error ? { success: false, content: error } : { success: true, content: result }
    } catch (e) {
        return { success: false, content: e.message }
    }
}

// apn
const getAPNData = async () => {
    try {
        const res = await getData(new URLSearchParams({
            cmd: 'apn_interface_version,APN_config0,APN_config1,APN_config2,APN_config3,APN_config4,APN_config5,APN_config6,APN_config7,APN_config8,APN_config9,APN_config10,APN_config11,APN_config12,APN_config13,APN_config14,APN_config15,APN_config16,APN_config17,APN_config18,APN_config19,ipv6_APN_config0,ipv6_APN_config1,ipv6_APN_config2,ipv6_APN_config3,ipv6_APN_config4,ipv6_APN_config5,ipv6_APN_config6,ipv6_APN_config7,ipv6_APN_config8,ipv6_APN_config9,ipv6_APN_config10,ipv6_APN_config11,ipv6_APN_config12,ipv6_APN_config13,ipv6_APN_config14,ipv6_APN_config15,ipv6_APN_config16,ipv6_APN_config17,ipv6_APN_config18,ipv6_APN_config19,apn_m_profile_name,profile_name,apn_wan_dial,apn_select,apn_pdp_type,apn_pdp_select,apn_pdp_addr,index,apn_Current_index,apn_auto_config,apn_ipv6_apn_auto_config,apn_mode,apn_wan_apn,apn_ppp_auth_mode,apn_ppp_username,apn_ppp_passwd,dns_mode,prefer_dns_manual,standby_dns_manual,apn_ipv6_wan_apn,apn_ipv6_pdp_type,apn_ipv6_ppp_auth_mode,apn_ipv6_ppp_username,apn_ipv6_ppp_passwd,ipv6_dns_mode,ipv6_prefer_dns_manual,ipv6_standby_dns_manual,apn_num_preset,wan_apn_ui,profile_name_ui,pdp_type_ui,ppp_auth_mode_ui,ppp_username_ui,ppp_passwd_ui,dns_mode_ui,prefer_dns_manual_ui,standby_dns_manual_ui,ipv6_wan_apn_ui,ipv6_ppp_auth_mode_ui,ipv6_ppp_username_ui,ipv6_ppp_passwd_ui,ipv6_dns_mode_ui,ipv6_prefer_dns_manual_ui,ipv6_standby_dns_manual_ui',
            multi_data: 1
        }))
        return res
    } catch {
        return null
    }
}

//deleteAPNProfile
const deleteAPNProfile = async (index) => {
    if (index == undefined || index == null) throw new Error('请提供index')
    const res = await postData(await login(), {
        action: "APN_PROC_EX",
        index,
        apn_mode: "manual",
        apn_action: "delete"
    })
    return res.json()
}

//saveAPNProfile
const saveAPNProfile = async (data) => {
    const res = await postData(await login(), {
        action: "APN_PROC_EX",
        apn_mode: "manual",
        apn_action: "save",
        ...data
    })
    return res.json()
}

//switchAPNAuto
const switchAPNAuto = async ({ isAuto = true, index = 0 }) => {
    const formData = {
        action: "APN_PROC_EX",
        apn_mode: isAuto ? "auto" : "manual",

    }
    const manualData = {
        apn_action: "set_default",
        set_default_flag: '1',
        apn_pdp_type: '',
        index
    }
    const data = isAuto ? formData : { ...formData, ...manualData }
    const res = await postData(await login(), data)
    return res.json()
}

// check Terms acceptance
const getTermsAcceptance = async () => {
    const res = await (await fetchWithTimeout(`${KANO_baseURL}/version_info`)).json()
    ACCEPT_TERMS = res.accept_terms && res.accept_terms.toString() == 'true'
    if (ACCEPT_TERMS) {
        return true
    }
    return false
}

const getNetConnInfo = async () => {
    try {
        const res = await (await fetchWithTimeout(`${KANO_baseURL}/connInfo`)).json()
        if (res.result == 'success') {
            return res.data
        }
    } catch (e) {
        console.error("getNetConnInfo Error:", e)
    }
    return null
}

//seConntHostName
const seConntHostName = async (mac, hostname) => {
    const formData = {
        action: "EDIT_HOSTNAME",
        mac,
        hostname
    }
    const res = await postData(await login(), formData)
    return res.json()
}

const getDailyUsageRange = async (start, endTime, method = 'date-range') => {
    if (method == 'date-range') {
        const startTime = new Date(start)
        const end = new Date(endTime)
        startTime.setHours(0, 0, 0, 0)
        end.setHours(23, 59, 59, 999)
        const res = await fetchWithTimeout(
            `${KANO_baseURL}/cellularUsage?startTime=${startTime.getTime()}&endTime=${end.getTime()}&method=${method}`
        );

        const data = await res.json();
        return data.usage
    }

    const result = [];

    for (let d = new Date(start); d <= endTime; d.setDate(d.getDate() + 1)) {
        const dayStart = new Date(d);
        dayStart.setHours(0, 0, 0, 0);

        const dayEnd = new Date(d);
        dayEnd.setHours(23, 59, 59, 999);

        if (dayEnd > endTime) {
            dayEnd.setTime(endTime.getTime());
        }

        const res = await fetchWithTimeout(
            `${KANO_baseURL}/cellularUsage?startTime=${dayStart.getTime()}&endTime=${dayEnd.getTime()}&method=${method}`
        );

        const data = await res.json();

        result.push({
            date: formatLocalDate(dayStart),
            usage: data.usage
        });
    }

    return result;
};