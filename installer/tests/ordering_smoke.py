"""Exercise out-of-order checkpoints and saved unconfirmed plans in the UI."""
from playwright.sync_api import sync_playwright
from ui_smoke import fixture_context,BRIDGE, settle


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=fixture_context(browser,viewport={'width':800,'height':650})
        context.add_init_script(BRIDGE+"localStorage.setItem('onboarding-v1','seen');window.__fixture.startRace=true;")
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:1420')
        page.get_by_role('button',name='继续未完成的安装',exact=False).click();settle(page)
        assert page.locator('.record').get_by_text('独立内置分区 · ••••1234',exact=True).count()==1
        page.get_by_role('button',name='确认安装计划',exact=True).click();settle(page)
        assert page.get_by_role('button',name='确认并开始').is_disabled()
        assert not {'start','resume','retry'} & set(page.evaluate('window.__fixture.requests'))
        page.get_by_role('button',name='返回',exact=True).click();settle(page)
        assert page.locator('h1').inner_text()=='继续未完成的安装'
        page.get_by_role('button',name='确认安装计划',exact=True).click();settle(page)
        page.get_by_role('checkbox').check()
        page.get_by_role('button',name='确认并开始').click()
        page.get_by_role('heading',name='OpenWrt 已安装并通过校验',exact=True).wait_for();settle(page)
        # A late request response and arbitrarily late events must not undo completion.
        for i in range(20):
            page.evaluate("window.__emitFixture({stage:'root_permission',status:'waiting_user',revision:1})")
        settle(page)
        assert page.locator('h1').inner_text()=='OpenWrt 已安装并通过校验'
        assert page.get_by_role('button',name='在安全边界暂停',exact=True).count()==0
        page.evaluate("window.__emitFixture({stage:'root_permission',status:'waiting_user',revision:3});window.__fixture.cancelAccepted=false")
        page.get_by_role('button',name='在安全边界暂停',exact=True).click();settle(page)
        assert page.get_by_text('已请求暂停，将在安全边界生效。',exact=True).count()==0
        assert page.evaluate("window.__fixture.calls.filter(c=>c.command==='start').length")==1
        assert not errors,errors
        browser.close()
        print('Ordering smoke passed: saved plans require confirmation, no stale response/event regression, 20 late events ignored, rejected pause has no success toast')


if __name__=='__main__':main()
