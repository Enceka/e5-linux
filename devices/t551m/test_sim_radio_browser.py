"""Run the production shared RF widget without touching a modem."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'openwrt/luci-app-t551m/htdocs/luci-static/resources'
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.set_content('<div id="radios"></div>')
    page.evaluate('''() => {
        window.flags=[true,true];window.calls=[];window.confirmed=true;window.fail=false;window.lang='zh';
        window.baseclass={extend:x=>x};
        window.M={translate:x=>x,confirmBox:()=>Promise.resolve(confirmed)};
        window.rpc={declare:spec=>(...args)=>{
            if(spec.method==='sim_radio_get'){
                if(window.slowRead){window.slowRead=false;const old=flags.slice();return new Promise(resolve=>window.finishOldRead=()=>resolve({ok:true,enabled:old}));}
                return Promise.resolve({ok:true,enabled:flags.slice(),supported:window.radioSupported});
            }
            if(spec.method==='sim_radio_set'){calls.push(args);if(!fail)flags[+args[0]]=args[1];return Promise.resolve({ok:true,id:'a'.repeat(32)});}
            if(spec.method==='sim_radio_status')return Promise.resolve({state:fail?'error':'done',ok:!fail,error:fail?'Test refusal':null});
            throw Error('unexpected RPC');
        }};
    }''')
    page.evaluate('(source)=>{window.widget=new Function("baseclass","rpc","M",source)(baseclass,rpc,M).attach(document.getElementById("radios"));}', (BASE/'mu300/sim-radio.js').read_text(encoding='utf-8'))
    buttons=page.get_by_role('switch')
    page.wait_for_function('document.querySelectorAll("[role=switch]")[0].disabled===false')
    assert buttons.count()==2
    page.evaluate('confirmed=false')
    buttons.nth(1).click()
    page.wait_for_timeout(50)
    assert page.evaluate('calls.length')==0
    page.evaluate('confirmed=true')
    page.evaluate('slowRead=true;void widget.refresh()')
    buttons.nth(1).click()
    page.wait_for_function('document.querySelector("[role=status]").textContent.includes("已应用")')
    assert page.evaluate('calls[0]')==['1',False,True]
    assert buttons.nth(0).get_attribute('aria-checked')=='true'
    assert buttons.nth(1).get_attribute('aria-checked')=='false'
    page.evaluate('finishOldRead()')
    page.wait_for_timeout(50)
    assert buttons.nth(1).get_attribute('aria-checked')=='false', 'Old read undid completed RF state'
    buttons.nth(0).click()
    page.wait_for_function('flags[0]===false && document.querySelectorAll("[role=switch]")[0].disabled===false')
    assert page.evaluate('calls[1]')==['0',False,True]
    page.evaluate('fail=true')
    buttons.nth(0).click()
    page.wait_for_function('document.querySelector("[role=status]").textContent.includes("Test refusal")')
    assert buttons.nth(0).get_attribute('aria-checked')=='false'
    page.evaluate('radioSupported=[true,false];widget.refresh()')
    assert buttons.nth(1).is_disabled()
    assert not buttons.nth(0).is_disabled()
    page.evaluate('widget.dispose()')
    browser.close()
print('PASS: shared RF widget confirmation, slot isolation, both-off, polling, failure reconciliation and disposal')
