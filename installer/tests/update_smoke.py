"""Update reboot guidance and clocks that stop on terminal states."""
import time
from playwright.sync_api import sync_playwright
from ui_smoke import fixture_context,BRIDGE,ROOT,layout,settle


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=fixture_context(browser,viewport={'width':800,'height':650})
        context.add_init_script(BRIDGE+"localStorage.setItem('onboarding-v1','seen');window.__fixture.tx.choices={method:'update'};Object.assign(window.__fixture.tx.plan,{method:'update',wipe:false,two_stage:false,offline:false});")
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:1420')
        page.get_by_role('button',name='继续未完成的安装',exact=False).click();settle(page)
        page.get_by_role('button',name='确认安装计划',exact=True).click();settle(page)
        assert '自动重启以应用更新' in page.locator('.page-scroll').inner_text()
        page.get_by_role('checkbox').check()
        page.get_by_role('button',name='确认并开始').click();settle(page)
        now=time.time()
        def event(**change):page.evaluate('change=>window.__emitFixture(change)',change)
        event(stage='openwrt_boot',status='waiting_device',revision=10,stage_started_at=now-3,
              details={'host':'192.168.9.1','reboot_manually':False})
        settle(page);layout(page)
        assert page.locator('h1').inner_text()=='更新已提交，设备将自动重启'
        assert '自动重启以应用更新' in page.locator('.boot-guidance').inner_text()
        assert page.locator('[data-sonner-toast]').filter(has_text='自动重启以应用更新').count()>=1
        before=page.locator('.elapsed').inner_text()
        page.wait_for_timeout(1300)
        assert page.locator('.elapsed').inner_text()!=before
        page.screenshot(path=str(ROOT/'screenshots/update-reboot-zh.png'))
        event(stage='openwrt_boot',status='waiting_device',revision=11,
              details={'host':'192.168.9.1','reboot_manually':False,'connection_state':'reconnecting','verification_error':None})
        settle(page);layout(page)
        assert page.locator('h1').inner_text()=='设备正在重启，等待重新连接'
        assert page.locator('.verification-error').count()==0
        assert page.locator('[data-sonner-toast][data-type=warning],[data-sonner-toast][data-type=error]').count()==0
        for revision in range(12,18):event(revision=revision)
        settle(page)
        assert page.locator('[data-sonner-toast][data-type=info]').filter(has_text='设备正在重启，等待重新连接').count()==1
        page.screenshot(path=str(ROOT/'screenshots/update-reconnecting-zh.png'))
        page.get_by_label('语言').select_option('en');settle(page)
        assert page.locator('h1').inner_text()=='Device restarting; waiting to reconnect'
        page.get_by_label('Language').select_option('zh');settle(page)
        for index,status in enumerate(('completed','failed','cancelled')):
            event(stage='complete' if status=='completed' else 'verify_capacity',status=status,revision=20+index,
                  stage_started_at=now-9,stage_finished_at=now-1,updated=now-1,
                  result={'filesystem_bytes':10737418240,'url':'http://192.168.9.1'})
            settle(page)
            assert page.locator('.elapsed').inner_text()=='阶段用时 8s'
            page.wait_for_timeout(1300)
            assert page.locator('.elapsed').inner_text()=='阶段用时 8s'
        event(stage='complete',status='completed',revision=23)
        page.get_by_label('语言').select_option('en');page.get_by_label('Theme').select_option('dark')
        settle(page);layout(page)
        assert page.locator('h1').inner_text()=='OpenWrt updated and verified'
        assert 'Updates keep the existing password' in page.locator('.success-panel .login-hint').inner_text()
        assert 'Fresh installation' not in page.locator('.success-panel .login-hint').inner_text()
        assert 'device restarted' in page.locator('.success-panel').inner_text()
        assert page.locator('.elapsed').inner_text()=='Stage elapsed 8s'
        page.screenshot(path=str(ROOT/'screenshots/update-complete-clock-en.png'))
        assert not errors,errors
        browser.close()
        print('Update smoke passed: plan/reboot guidance, reconnects stay neutral without error/warning toasts, repeated waits deduplicated, active clock advances, terminal clocks freeze, bilingual update result at 800x650')


if __name__=='__main__':main()
