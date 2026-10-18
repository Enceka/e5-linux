"""Offline onboarding/help integration checks against the production UI bundle."""
from playwright.sync_api import sync_playwright
from ui_smoke import fixture_context,BRIDGE, ROOT, layout, settle


def bounded_dialog(page):
    box=page.get_by_role('dialog').bounding_box()
    assert box and box['x']>=0 and box['y']>=0,box
    viewport=page.viewport_size
    assert box['x']+box['width']<=viewport['width']+.5,box
    assert box['y']+box['height']<=viewport['height']+.5,box
    assert page.evaluate('scrollY')==0
    for _ in range(15):
        page.keyboard.press('Tab')
        assert page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)")


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=fixture_context(browser,viewport={'width':1120,'height':900})
        context.add_init_script(BRIDGE)
        page=context.new_page();errors=[];remote=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:remote.append(request.url) if not request.url.startswith('http://127.0.0.1:1420/') and request.url!='https://api.kanokano.cn/pay/zsm.png' else None)
        page.goto('http://127.0.0.1:1420')
        dialog=page.get_by_role('dialog',name='新手引导')
        dialog.wait_for();settle(page);bounded_dialog(page)
        assert set(page.evaluate('window.__fixture.requests'))=={'hello'}
        page.screenshot(path=str(ROOT/'screenshots/onboarding-light-zh.png'))
        dialog.get_by_role('button',name='下一步',exact=True).click();settle(page)
        dialog.get_by_role('heading',name='选择适合你的安装方式').wait_for()
        dialog.get_by_role('button',name='下一步',exact=True).click();settle(page)
        dialog.get_by_text('电脑记录和备份都丢失时',exact=False).wait_for()
        dialog.get_by_role('button',name='上一步',exact=True).click();settle(page)
        dialog.get_by_role('button',name='下一步',exact=True).click();settle(page)
        dialog.get_by_role('button',name='开始使用',exact=True).click()
        assert page.evaluate("localStorage.getItem('onboarding-v1')")=='seen'
        page.reload();settle(page)
        assert page.get_by_role('dialog').count()==0
        page.get_by_role('button',name='帮助与使用指南',exact=True).click()
        dialog=page.get_by_role('dialog',name='帮助与使用指南');dialog.wait_for();settle(page)
        bounded_dialog(page)
        dialog.get_by_role('textbox',name='搜索使用指南').fill('没有任何匹配xyz')
        dialog.get_by_text('没有找到相关内容',exact=False).wait_for()
        dialog.get_by_role('textbox',name='搜索使用指南').fill('Magisk')
        assert dialog.locator('.help-topics button').count()>=1
        dialog.get_by_role('textbox',name='搜索使用指南').fill('')
        dialog.get_by_role('button',name='更新与自动重启',exact=True).click()
        dialog.get_by_text('不要因为重启期间连接不上而重新执行更新。',exact=True).wait_for()
        dialog.get_by_role('button',name='连接与常见问题',exact=True).click()
        dialog.get_by_text('电脑记录和导出备份都丢失时',exact=False).wait_for()
        assert dialog.locator('article').evaluate('(el)=>el.scrollHeight>el.clientHeight')
        dialog.locator('article').evaluate('(el)=>el.scrollTop=el.scrollHeight')
        page.screenshot(path=str(ROOT/'screenshots/help-recovery-light-zh.png'))
        page.keyboard.press('Escape');settle(page)
        assert page.get_by_role('dialog').count()==0
        assert page.get_by_role('button',name='帮助与使用指南',exact=True).evaluate('(el)=>el===document.activeElement')
        page.keyboard.press('F1');page.get_by_role('dialog').wait_for()
        page.get_by_role('button',name='重新查看新手引导',exact=True).click()
        page.get_by_role('dialog',name='新手引导').wait_for()
        page.get_by_role('button',name='暂时跳过',exact=True).click();settle(page)
        # Help is available during a real coordinator-shaped wait without touching the task.
        page.get_by_role('button',name='安装 OpenWrt',exact=False).click()
        page.get_by_role('button',name='校验安装包',exact=True).click()
        page.get_by_role('button',name='刷新设备',exact=True).click()
        page.get_by_label('请选择设备').select_option('fixture-1234')
        page.get_by_role('button',name='检查设备',exact=True).click()
        page.get_by_role('button',name='查看安装计划',exact=True).click()
        page.get_by_role('button',name='确认并开始',exact=True).wait_for();settle(page)
        page.get_by_role('checkbox').check()
        page.get_by_role('button',name='确认并开始',exact=True).click()
        page.get_by_role('heading',name='请完成 Android 初始设置',exact=True).first.wait_for()
        before=page.evaluate('window.__fixture.requests.length')
        page.get_by_role('button',name='查看当前步骤帮助',exact=True).click()
        dialog=page.get_by_role('dialog',name='帮助与使用指南');dialog.wait_for();settle(page)
        assert dialog.locator('[aria-current=page]').inner_text()=='Android 重置后续装'
        assert page.evaluate('window.__fixture.requests.length')==before
        page.keyboard.press('Escape');settle(page)
        assert page.evaluate("window.__fixture.tx.status")=='waiting_user'
        assert page.get_by_role('button',name='查看当前步骤帮助',exact=True).evaluate('(el)=>el===document.activeElement')
        page.get_by_label('语言').select_option('en')
        page.get_by_label('Theme').select_option('dark')
        page.set_viewport_size({'width':800,'height':650})
        page.emulate_media(reduced_motion='reduce')
        page.keyboard.press('F1')
        dialog=page.get_by_role('dialog',name='Help and user guide');dialog.wait_for();settle(page)
        bounded_dialog(page)
        dialog.get_by_role('button',name='Updates and automatic restart',exact=True).click()
        dialog.get_by_text('Do not start another update because the device is unreachable during restart.',exact=True).wait_for()
        dialog.get_by_role('button',name='Connection and troubleshooting',exact=True).click()
        dialog.get_by_text('this version cannot reconstruct a record from the device alone',exact=False).wait_for()
        page.evaluate("window.__emitFixture({stage:'root_permission',status:'waiting_user'})");settle(page)
        assert page.evaluate("!!document.elementFromPoint(600,120).closest('[role=dialog]')"), 'Toast obscures help'
        page.screenshot(path=str(ROOT/'screenshots/help-small-dark-en.png'))
        dialog.get_by_role('button',name='Replay getting started',exact=True).click()
        dialog=page.get_by_role('dialog',name='Getting started');dialog.wait_for();settle(page)
        bounded_dialog(page)
        page.screenshot(path=str(ROOT/'screenshots/onboarding-small-dark-en.png'))
        page.keyboard.press('Escape');settle(page);layout(page)
        assert not errors,errors
        assert not remote,remote
        # A saved transaction suppresses automatic onboarding even on a fresh computer profile.
        second=fixture_context(browser,viewport={'width':800,'height':650})
        second.add_init_script(BRIDGE+'window.__fixture.saved=[window.__fixture.tx];')
        saved=second.new_page();saved.goto('http://127.0.0.1:1420');settle(saved)
        assert saved.get_by_role('dialog').count()==0
        assert set(saved.evaluate('window.__fixture.requests'))=={'hello'}
        third=fixture_context(browser,viewport={'width':800,'height':650})
        third.add_init_script(BRIDGE)
        skipped=third.new_page();skipped.goto('http://127.0.0.1:1420')
        skipped.get_by_role('dialog',name='新手引导').wait_for()
        skipped.get_by_role('button',name='暂时跳过',exact=True).click()
        skipped.reload();settle(skipped)
        assert skipped.get_by_role('dialog').count()==0
        print('Help smoke passed: first launch/replay/skip/persistence, saved-record suppression, offline search/manual, focus trapping/restore/Escape/F1, contextual help without backend operations, languages/themes and bounded 800x650 dialogs')
        browser.close()


if __name__=='__main__':main()
