"""Verify explicit UI methods survive probing, review and back navigation."""
from playwright.sync_api import sync_playwright
from ui_smoke import fixture_context,BRIDGE, ROOT, settle


def last(page,command):
    return page.evaluate('(command)=>window.__fixture.calls.filter(call=>call.command===command).at(-1).params',command)


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=fixture_context(browser,viewport={'width':1120,'height':900})
        context.add_init_script(BRIDGE+"localStorage.setItem('onboarding-v1','seen');window.__fixture.probed={existing:true,tf:null};")
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:1420')
        page.get_by_role('button',name='高级选项',exact=False).click();settle(page)
        button=page.get_by_role('button',name='重装已有内置分区',exact=False)
        assert button.get_attribute('aria-pressed')=='true'
        page.get_by_role('button',name='校验安装包',exact=True).click()
        page.get_by_label('请选择设备').select_option('fixture-1234')
        page.get_by_role('button',name='检查设备',exact=True).click();settle(page)
        assert last(page,'probe')['method']=='reinstall'
        page.get_by_role('button',name='查看安装计划',exact=True).click();settle(page)
        assert last(page,'plan')['choices']['method']=='reinstall'
        assert page.locator('.plan-list').get_by_text('重装已有内置分区',exact=True).count()==1
        assert page.locator('.plan-list').get_by_text('mmcblk1p20',exact=True).count()==1
        assert page.get_by_text('已有 OpenWrt 系统与设置会被替换，Android 用户数据保留。',exact=True).count()==1
        assert page.get_by_role('button',name='确认并开始',exact=True).is_disabled()
        page.screenshot(path=str(ROOT/'screenshots/reinstall-no-card-plan-zh.png'))
        page.get_by_role('button',name='返回',exact=True).click();settle(page)
        assert page.locator('h1').inner_text()=='高级选项'
        assert button.get_attribute('aria-pressed')=='true'
        page.get_by_role('button',name='检查设备',exact=True).click();settle(page)
        assert last(page,'probe')['method']=='reinstall'
        page.get_by_role('button',name='返回',exact=True).click();settle(page)
        # A present card must never replace an explicit internal choice.
        for method,label,existing in [('part','独立内置分区',False),('reinstall','重装已有内置分区',True),('tf','TF 卡',False)]:
            page.evaluate('(existing)=>window.__fixture.probed={existing,tf:"/dev/block/mmcblk0p1"}',existing)
            page.get_by_role('button',name='安装 OpenWrt',exact=False).click();settle(page)
            choice=page.get_by_role('button',name=label,exact=False);choice.click()
            page.get_by_role('button',name='检查设备',exact=True).click();settle(page)
            assert last(page,'probe')['method']==method
            assert choice.get_attribute('aria-pressed')=='true'
            page.get_by_role('button',name='查看安装计划',exact=True).click();settle(page)
            assert last(page,'plan')['choices']['method']==method
            page.get_by_role('button',name='返回',exact=True).click();settle(page)
            assert choice.get_attribute('aria-pressed')=='true'
            page.get_by_role('button',name='返回',exact=True).click();settle(page)
        page.get_by_role('button',name='高级选项',exact=False).click();settle(page)
        page.get_by_role('button',name='userdata 镜像',exact=True).click()
        page.get_by_role('button',name='检查设备',exact=True).click();settle(page)
        assert last(page,'probe')['method']=='image'
        assert page.get_by_role('button',name='userdata 镜像',exact=True).get_attribute('aria-pressed')=='true'
        assert not errors,errors
        assert not {'start','resume','retry','cancel'} & set(page.evaluate('window.__fixture.requests'))
        print('Method smoke passed: no-card reinstall, explicit part/reinstall/TF/image preserved, exact probe/plan parameters, review target/impact and return-to-origin; no device writes')
        browser.close()


if __name__=='__main__':main()
