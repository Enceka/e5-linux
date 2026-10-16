"""SIM-management page with real controls/dialogs and isolated RPC fixtures."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

TOP = Path(__file__).resolve().parents[2]
BASE = TOP / 'openwrt/luci-app-t551m/htdocs/luci-static/resources'
menu = json.loads((TOP / 'openwrt/luci-app-t551m/root/usr/share/luci/menu.d/luci-app-mu300.json').read_text(encoding='utf-8'))
assert menu['admin/modem/sim']['action']['path'] == 'mu300/sim'
assert 'data-sim' not in (BASE / 'view/mu300/home.js').read_text(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
    page = browser.new_page(viewport={'width':390,'height':750})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('http://sim.test/**', lambda route: route.fulfill(body='<html lang="zh"><head><meta charset="utf-8"></head><body></body></html>', content_type='text/html'))
    page.goto('http://sim.test/')
    page.evaluate('''()=>{
        window.L={env:{lang:'zh'},resource:x=>x};
        window.baseclass={extend:x=>x};window.view={extend:x=>x};
        window.poll={add:f=>window.refreshSim=f,remove:()=>{}};
        window.state={ok:true,data_sim:0,saved_sim:0,data_up:true};window.calls=[];window.jobState='running';
        window.target='1';window.immediate=false;window.scopedCalls=[];
        window.rpc={declare:spec=>(...args)=>{
            if(spec.method==='sim_radio_get')return Promise.resolve({ok:true,enabled:[true,true]});
            if(spec.method==='sim_get')return Promise.resolve(state);
            if(spec.method==='sim_set'){
                calls.push(args);target=args[0];
                if(immediate){state={ok:true,data_sim:Number(target),saved_sim:Number(target),data_up:true};return Promise.resolve({ok:true,state:'done',target});}
                return Promise.resolve({ok:true,id:'a'.repeat(32),state:'running',target});
            }
            if(spec.method==='sim_status')return Promise.resolve({ok:jobState==='done'||jobState==='running',state:jobState,target,error:jobState==='error'?'readback mismatch':null});
            scopedCalls.push({method:spec.method,slot:args[args.length-1]});
            return Promise.resolve({});
        }};
        sessionStorage.setItem('modem-view-slot','0');
    }''')
    page.evaluate('(source)=>{window.M=new Function("rpc","baseclass",source)(rpc,baseclass);}', (BASE/'mu300/common.js').read_text(encoding='utf-8'))
    page.evaluate('(source)=>{window.DataSim=new Function("baseclass","M",source)(baseclass,M);}', (BASE/'mu300/data-sim.js').read_text(encoding='utf-8'))
    page.evaluate('(source)=>{window.SimRadio=new Function("baseclass","rpc","M",source)(baseclass,rpc,M);}', (BASE/'mu300/sim-radio.js').read_text(encoding='utf-8'))
    page.evaluate('(source)=>{window.pageView=new Function("view","poll","M","DataSim","SimRadio",source)(view,poll,M,DataSim,SimRadio);document.body.appendChild(pageView.render());}', (BASE/'view/mu300/sim.js').read_text(encoding='utf-8'))
    select = page.locator('#mud-data-sim-select')
    button = page.locator('.mud-data-sim-controls button')
    assert button.is_disabled()
    select.select_option('1')
    button.click()
    page.locator('.mud-dlg button').first.click()  # Cancel.
    assert page.evaluate('calls.length') == 0
    assert page.evaluate('M.simSlot()') == '0'
    button.click()
    page.locator('.mud-dlg button').last.click()
    page.wait_for_function('calls.length===1')
    assert page.evaluate('calls[0]') == ['1','0',True]
    assert select.is_disabled() and button.is_disabled()
    page.evaluate("jobState='error'")
    page.wait_for_function("document.querySelector('[data-result]').textContent.includes('readback mismatch')")
    assert not button.is_disabled()
    assert page.evaluate('M.simSlot()') == '0', 'Failed switch changed viewing SIM'
    page.evaluate("jobState='running'")
    button.click()
    page.locator('.mud-dlg button').last.click()
    page.wait_for_function('calls.length===2')
    page.evaluate("state={data_sim:1,saved_sim:1,data_up:true};jobState='done'")
    page.wait_for_function("document.querySelector('[data-current]').textContent.includes('当前上网卡：SIM 2')")
    assert '开机使用：SIM 2' in page.locator('[data-current]').inner_text()
    assert page.evaluate("sessionStorage.getItem('modem-view-slot')") == '1'
    assert page.evaluate("sessionStorage.getItem('modem-data-sim-job')") is None
    assert button.is_disabled()
    page.evaluate("async()=>{await M.callStatus();await M.callAtHist();await M.callLockGet();await M.callTrafficGet();}")
    assert page.evaluate("scopedCalls.every(call=>call.slot==='1')"), 'Another page still queries SIM 1'
    # Read-only polling must keep a deliberately selected secondary card.
    page.evaluate("sessionStorage.setItem('modem-view-slot','0')")
    page.evaluate('refreshSim()')
    assert page.evaluate('M.simSlot()') == '0'
    # A verified completion still follows the target if status was observed
    # before the job completed; immediate completion uses the same rule.
    page.evaluate("immediate=true;sessionStorage.setItem('modem-view-slot','1')")
    select.select_option('0');button.click();page.locator('.mud-dlg button').last.click()
    page.wait_for_function("M.simSlot()==='0' && document.querySelector('[data-current]').textContent.includes('当前上网卡：SIM 1')")
    assert button.is_disabled()
    # A completed job recovered after navigating away must also synchronize.
    page.evaluate("pageView.unload();target='1';state={ok:true,data_sim:1,saved_sim:1,data_up:true};jobState='done';sessionStorage.setItem('modem-data-sim-job','b'.repeat(32));document.body.replaceChildren(pageView.render())")
    page.wait_for_function("M.simSlot()==='1' && sessionStorage.getItem('modem-data-sim-job')===null")
    for width in (390,320):
        page.set_viewport_size({'width':width,'height':750})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Horizontal overflow'
    output = TOP/'logs/t551m/data-sim.png'
    output.parent.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(output))
    for language,title,error in [('en','SIM management','A data SIM switch is already running'),('tr','SIM yönetimi','İnternet SIM kartı zaten değiştiriliyor; lütfen bekleyin')]:
        page.evaluate('language=>{pageView.unload();L.env.lang=language;document.documentElement.lang=language;document.body.replaceChildren(pageView.render());M.callSimSet=async()=>({ok:false,error:"A data SIM switch is already running"});}',language)
        page.wait_for_function("document.querySelector('[data-current]').textContent.includes('SIM 2')")
        assert page.locator('h3').first.inner_text()==title
        select.select_option('0');button.click();page.locator('.mud-dlg button').last.click()
        page.wait_for_function('error=>document.querySelector("[data-result]").textContent.includes(error)',arg=error)
        assert not page.evaluate(r'/[\u3400-\u9fff]/.test(document.body.innerText)'),language
    page.evaluate('pageView.unload()')
    assert not errors, errors
    browser.close()
print('PASS: cellular menu, cancel/error isolation, verified and immediate switch, restored job, view synchronization, scoped RPC, manual secondary view, translations and narrow layout')
