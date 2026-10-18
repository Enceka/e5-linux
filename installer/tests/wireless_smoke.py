"""Exercise real wireless controls through a test-only structured bridge."""
from playwright.sync_api import sync_playwright
from ui_smoke import BRIDGE, ROOT, fixture_context, layout, settle

WIRELESS = r"""
localStorage.setItem('onboarding-v1','seen');
window.__fixture.devices=[];
const originalInvoke=window.__TAURI_INTERNALS__.invoke;
window.__TAURI_INTERNALS__.invoke=async(cmd,args={})=>{
 const f=window.__fixture;
 if(cmd!=='backend_request'||!['adb_connect','adb_disconnect'].includes(args.command)) return originalInvoke(cmd,args);
 f.requests.push(args.command);f.calls.push({command:args.command,params:args.params});
 if(f.fail===args.command) throw new Error('Fixture: wireless connection rejected');
 if(args.command==='adb_connect'){
  const endpoint=args.params.address.includes(':')?args.params.address:args.params.address+':5555';
  const state=f.wirelessState||'device';
  f.devices=[...f.devices.filter(d=>d.serial!==endpoint),{serial:endpoint,label:'M8',state,wireless:true}];
  return {endpoint,state,devices:f.devices};
 }
 f.devices=f.devices.filter(d=>d.serial!==args.params.serial);
 return {endpoint:args.params.serial,devices:f.devices};
};
"""


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=fixture_context(browser,viewport={'width':800,'height':650})
        context.add_init_script(BRIDGE+WIRELESS)
        page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:1420')
        page.get_by_role('button',name='安装 OpenWrt',exact=False).click();settle(page)
        page.locator('.wireless-adb summary').click()
        field=page.get_by_label('设备地址 / 地址:端口',exact=True)
        connect=page.get_by_role('button',name='连接',exact=True)
        disconnect=page.get_by_role('button',name='断开所选无线设备',exact=True)
        assert field.input_value()=='192.168.0.1' and disconnect.is_disabled()
        assert 'package' not in page.evaluate('window.__fixture.requests')
        page.evaluate("window.__fixture.fail='adb_connect'")
        connect.click();settle(page)
        assert connect.is_enabled()
        assert page.locator('[data-sonner-toast][data-type=error]').count()==1
        page.evaluate('window.__fixture.fail=null')
        field.press('Enter');settle(page)
        assert page.get_by_label('请选择设备').input_value()=='192.168.0.1:5555'
        assert disconnect.is_enabled()
        assert page.get_by_role('button',name='检查设备',exact=True).is_disabled()
        assert page.evaluate("window.__fixture.calls.filter(c=>c.command==='adb_connect').at(-1).params")=={'address':'192.168.0.1'}
        # A second router must not silently become the selected installation target.
        field.fill('192.168.0.2:5556');connect.click();settle(page)
        assert page.get_by_label('请选择设备').input_value()=='192.168.0.1:5555'
        options=page.get_by_label('请选择设备').inner_text()
        assert '192.168.0.1:5555' in options and '192.168.0.2:5556' in options
        page.get_by_label('请选择设备').select_option('192.168.0.2:5556')
        assert '192.168.0.2:5556' in page.locator('.wireless-target').inner_text()
        page.locator('.wireless-adb').scroll_into_view_if_needed();settle(page);layout(page)
        page.screenshot(path=str(ROOT/'screenshots/wireless-adb-zh.png'))
        disconnect.click();settle(page)
        assert page.evaluate("window.__fixture.calls.filter(c=>c.command==='adb_disconnect').at(-1).params")=={'serial':'192.168.0.2:5556'}
        assert page.get_by_label('请选择设备').input_value()==''
        assert page.get_by_label('请选择设备').locator('option').count()==2
        assert disconnect.is_disabled()
        page.evaluate("window.__fixture.devices.push({serial:'usb-device',label:'USB',state:'device',wireless:false})")
        page.get_by_role('button',name='刷新设备',exact=True).click();settle(page)
        page.get_by_label('请选择设备').select_option('usb-device')
        assert disconnect.is_disabled()
        # Authorization/offline are connection states, not false successful readiness.
        field.fill('192.168.0.3');page.evaluate("window.__fixture.wirelessState='unauthorized'")
        connect.click();settle(page)
        assert page.get_by_text('已连接，请在设备上允许调试',exact=True).count()==1
        page.evaluate("window.__fixture.wirelessState='offline'")
        connect.click();settle(page)
        assert page.get_by_text('设备已添加但仍离线，请检查调试状态后刷新',exact=True).count()==1
        page.locator('.page-scroll').evaluate('(e)=>e.scrollTop=e.scrollHeight');layout(page)
        # The same action stays available while the original Android transaction waits.
        page.evaluate("window.__fixture.saved=[window.__fixture.tx]")
        page.get_by_role('button',name='返回',exact=True).click();settle(page)
        page.get_by_role('button',name='继续未完成的安装',exact=False).click();settle(page)
        page.get_by_role('button',name='确认安装计划',exact=True).click();settle(page)
        page.get_by_role('checkbox').check();page.get_by_role('button',name='确认并开始',exact=True).click();settle(page)
        assert page.locator('.wireless-adb').get_attribute('open') is not None
        assert page.get_by_role('button',name='断开所选无线设备',exact=True).count()==0
        bound=page.evaluate('window.__fixture.tx.device.serial')
        page.get_by_label('设备地址 / 地址:端口',exact=True).fill('192.168.0.1')
        page.get_by_role('button',name='连接',exact=True).click();settle(page)
        assert page.evaluate('window.__fixture.tx.device.serial')==bound
        page.evaluate("window.__emitFixture({stage:'transfer_install',status:'running',unsafe:true,revision:15})");settle(page)
        assert page.locator('.wireless-adb').count()==0
        page.evaluate("window.__emitFixture({stage:'root_permission',status:'waiting_user',unsafe:false,revision:16})");settle(page)
        page.get_by_label('语言').select_option('en');page.get_by_label('Theme').select_option('dark');settle(page);layout(page)
        assert page.get_by_label('Device address / address:port',exact=True).is_visible()
        page.screenshot(path=str(ROOT/'screenshots/wireless-adb-wait-en.png'))
        assert not errors,errors
        browser.close()
        print('Wireless ADB smoke passed: retry, Enter connect without package, explicit multi-device target, exact disconnect, USB protection, authorization/offline, bound Android resume and unsafe-stage exclusion, bilingual 800x650 layout; no real device access')


if __name__=='__main__':main()
