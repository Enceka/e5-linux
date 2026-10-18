"""Device enumeration remains available without a package; text selection is scoped."""
from playwright.sync_api import sync_playwright
from ui_smoke import fixture_context,BRIDGE, ROOT, layout, settle


def selection(page,selector,expected):
    assert page.locator(selector).first.evaluate('(el)=>getComputedStyle(el).userSelect')==expected,selector


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=fixture_context(browser,viewport={'width':800,'height':650})
        context.add_init_script(BRIDGE+"window.__fixture.devices=[];localStorage.setItem('onboarding-v1','seen');")
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:1420')
        page.get_by_role('button',name='安装 OpenWrt',exact=False).click();settle(page)
        refresh=page.get_by_role('button',name='刷新设备',exact=True)
        assert page.locator('.wireless-adb summary').inner_text()=='无线 ADB 连接'
        assert refresh.is_enabled()
        assert page.get_by_role('button',name='检查设备',exact=True).is_disabled()
        assert page.get_by_role('button',name='查看安装计划',exact=True).is_disabled()
        assert 'package' not in page.evaluate('window.__fixture.requests')
        for _ in range(3):
            refresh.click();settle(page)
            assert refresh.is_enabled()
        assert page.get_by_label('请选择设备').locator('option:checked').inner_text()=='未发现设备'
        selection(page,'h1','none');selection(page,'.stepper','none');selection(page,'.ui-button','none')
        selection(page,'.file-path','text')
        page.screenshot(path=str(ROOT/'screenshots/no-device-refresh-light-zh.png'))
        # A transient enumeration failure clears stale readiness and leaves retry available.
        page.evaluate("window.__fixture.fail='devices'")
        refresh.click()
        page.get_by_text('Error: Fixture: operation rejected',exact=True).wait_for();settle(page)
        assert refresh.is_enabled()
        selection(page,'.toast-description','text')
        page.evaluate("window.__fixture.fail=null;window.__fixture.devices=[{serial:'second-5678',state:'unauthorized',label:'Other'}, {serial:'chosen-1234',state:'device',label:'E5'}]")
        refresh.click();settle(page)
        assert page.get_by_label('请选择设备').input_value()==''
        page.get_by_label('请选择设备').select_option('chosen-1234')
        assert page.get_by_role('button',name='检查设备',exact=True).is_disabled()
        assert 'probe' not in page.evaluate('window.__fixture.requests')
        page.get_by_role('button',name='校验安装包',exact=True).click()
        page.get_by_role('button',name='检查设备',exact=True).click();settle(page)
        assert page.get_by_role('button',name='查看安装计划',exact=True).is_enabled()
        selection(page,'.device-card small','none');selection(page,'.device-card strong','text')
        # Refresh invalidates old root inspection; no-device response cannot leave install enabled.
        page.evaluate('window.__fixture.devices=[]')
        refresh.click();settle(page)
        assert page.get_by_label('请选择设备').input_value()==''
        assert page.locator('.device-card').count()==0
        assert page.get_by_role('button',name='查看安装计划',exact=True).is_disabled()
        page.evaluate("window.__fixture.devices=[{serial:'single-1234',state:'unauthorized',label:'E5'}]")
        refresh.click();settle(page)
        assert page.get_by_label('请选择设备').input_value()=='single-1234'
        assert '等待调试授权' in page.get_by_label('请选择设备').locator('option:checked').inner_text()
        page.get_by_role('button',name='详细日志',exact=False).click();settle(page)
        selection(page,'.log-toggle','none');selection(page,'.log-panel pre','text')
        page.locator('.log-panel pre').dblclick(position={'x':95,'y':20})
        assert page.evaluate('getSelection().toString().length')>0
        page.evaluate('getSelection().removeAllRanges()')
        page.locator('h1').dblclick()
        assert page.evaluate('getSelection().toString()')==''
        page.get_by_role('button',name='详细日志',exact=False).click();settle(page)
        page.get_by_role('button',name='返回',exact=True).click();settle(page)
        for name in ['高级选项','临时启动已安装的 OpenWrt']:
            page.get_by_role('button',name=name,exact=False).click();settle(page)
            assert refresh.is_enabled()
            page.get_by_role('button',name='返回',exact=True).click();settle(page)
        page.get_by_label('语言').select_option('en')
        page.get_by_role('button',name='Advanced options',exact=False).click();settle(page)
        assert page.locator('.wireless-adb summary').inner_text()=='Wireless ADB connection'
        page.locator('.page-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
        page.get_by_role('button',name='Userdata image',exact=True).click()
        selection(page,'input[type=number]','text')
        page.get_by_role('button',name='Help and user guide',exact=True).click();settle(page)
        page.get_by_role('dialog').get_by_role('button',name='Connection and troubleshooting',exact=True).click()
        selection(page,'.help-article>h2','none');selection(page,'.help-markdown p','text')
        selection(page,'.help-topics button','none')
        page.keyboard.press('Escape');settle(page);layout(page)
        assert not errors,errors
        assert not {'plan','start','cancel','resume','retry'} & set(page.evaluate('window.__fixture.requests'))
        print('Refresh smoke passed: unverified package, repeated empty-list retry, error retry, multiple/unauthorized devices, stale-root clearing, install/advanced/boot pages, bounded layout and selective copying; no device writes')
        browser.close()


if __name__=='__main__':main()
