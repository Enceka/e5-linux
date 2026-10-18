"""Credit copying and optional online-first donation dialog with offline fallback."""
from playwright.sync_api import sync_playwright
from ui_smoke import BRIDGE,ROOT,layout,settle
from help_smoke import bounded_dialog

ONLINE='https://api.kanokano.cn/pay/zsm.png'
GROUPS=('376737485','1016263950','950666902','262019320')


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(viewport={'width':800,'height':650})
        # An acknowledgement from the older release must not suppress startup.
        context.add_init_script(BRIDGE+"window.__fixture.autoDismissSupport=false;")
        requests=[]
        context.route(ONLINE,lambda route:(requests.append(route.request.url),route.fulfill(path=str(ROOT/'ui/src/assets/donation-fallback.png'),content_type='image/png'))[-1])
        page=context.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:1420')
        dialog=page.get_by_role('dialog',name='赞赏支持作者');dialog.wait_for();settle(page)
        bounded_dialog(page)
        assert page.get_by_role('dialog').count()==1
        assert dialog.locator('.lucide-github').count()==2
        assert dialog.get_by_text('你的 Star，是持续维护与更新的动力。',exact=True).count()==1
        page.evaluate("() => {window.__nativeCalls=[];const base=window.__TAURI_INTERNALS__.invoke;window.__TAURI_INTERNALS__.invoke=(cmd,args)=>{window.__nativeCalls.push({cmd,args});return base(cmd,args)};}")
        for project,authors in (('e5-linux','Enceka · Minikano'),('mu300-linux','dikeckaan · Minikano')):
            assert dialog.get_by_text('作者: '+authors,exact=True).count()==1
            dialog.get_by_role('link',name='去 GitHub 给项目点 Star: '+project,exact=True).click();settle(page)
        assert page.evaluate("window.__nativeCalls.filter(c=>c.cmd==='open_repository').map(c=>c.args.repository)")==['e5','mu300']
        assert page.get_by_role('dialog').count()==1
        image=dialog.get_by_role('img',name='Minikano 赞赏码')
        assert image.get_attribute('src')==ONLINE
        assert image.evaluate('(el)=>el.complete && el.naturalWidth===613')
        assert requests==[ONLINE]
        assert set(page.evaluate('window.__fixture.requests'))=={'hello'}
        page.keyboard.press('F1');settle(page)
        assert page.get_by_role('dialog').count()==1
        page.screenshot(path=str(ROOT/'screenshots/support-first-launch-zh.png'))
        dialog.get_by_role('button',name='继续使用',exact=True).click()
        page.get_by_role('dialog',name='新手引导').wait_for();settle(page)
        assert page.get_by_role('dialog').count()==1
        page.get_by_role('button',name='暂时跳过',exact=True).click();settle(page)
        page.reload();settle(page);layout(page)
        dialog=page.get_by_role('dialog',name='赞赏支持作者');dialog.wait_for();settle(page)
        assert requests==[ONLINE,ONLINE]
        dialog.get_by_role('button',name='关闭赞赏提示',exact=True).click();settle(page)
        assert page.get_by_role('dialog').count()==0
        sidebar=page.locator('.support-info')
        assert sidebar.inner_text().startswith('安装器作者: Minikano')
        assert sidebar.locator('.repository-link .lucide-github').count()==2
        assert sidebar.get_by_role('button',name='赞赏支持作者',exact=True).inner_text()=='赞赏支持作者'
        assert sidebar.bounding_box()['y']+sidebar.bounding_box()['height']<=page.locator('.sidebar-note').bounding_box()['y']
        page.evaluate("Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async(value)=>{window.__copied=value}})")
        for number in GROUPS:
            page.get_by_role('button',name='复制群号: '+number,exact=True).click();settle(page)
            assert page.evaluate('window.__copied')==number
        assert page.locator('.community-number').first.evaluate('(el)=>getComputedStyle(el).userSelect')=='text'
        page.evaluate("() => {window.__nativeCalls=[];const base=window.__TAURI_INTERNALS__.invoke;window.__TAURI_INTERNALS__.invoke=(cmd,args)=>{window.__nativeCalls.push({cmd,args});return base(cmd,args)};}")
        for project,url in (('e5','https://github.com/sprd-linux-devs/e5-linux'),('mu300','https://github.com/dikeckaan/mu300-linux')):
            link=sidebar.locator('a[href="'+url+'"]')
            assert link.count()==1
            link.click();settle(page)
        assert page.evaluate("window.__nativeCalls.filter(c=>c.cmd==='open_repository').map(c=>c.args.repository)")==['e5','mu300']
        page.screenshot(path=str(ROOT/'screenshots/author-sidebar-zh.png'))
        # Failure to access the online code uses the bundled code; no device request.
        context.unroute(ONLINE)
        context.route(ONLINE,lambda route:route.abort())
        page.get_by_role('button',name='赞赏支持作者',exact=True).click()
        dialog=page.get_by_role('dialog',name='赞赏支持作者');dialog.wait_for();settle(page)
        image=dialog.get_by_role('img',name='Minikano 赞赏码')
        assert 'donation-fallback-' in image.get_attribute('src')
        assert image.evaluate('(el)=>el.complete && el.naturalWidth===613')
        page.keyboard.press('Escape');settle(page)
        # A stalled request also falls back, without blocking closing the modal.
        context.unroute(ONLINE)
        pending=[]
        context.route(ONLINE,lambda route:pending.append(route))
        page.get_by_role('button',name='赞赏支持作者',exact=True).click()
        dialog=page.get_by_role('dialog',name='赞赏支持作者');dialog.wait_for()
        dialog.locator('img[src*="donation-fallback-"]').wait_for(timeout=8000)
        for route in pending:route.abort()
        page.keyboard.press('Escape');settle(page)
        page.get_by_label('语言').select_option('en');page.get_by_label('Theme').select_option('dark');settle(page);layout(page)
        context.unroute(ONLINE);context.route(ONLINE,lambda route:route.abort())
        page.get_by_role('button',name='Support the author',exact=True).click()
        dialog=page.get_by_role('dialog',name='Support the author');dialog.wait_for();settle(page);bounded_dialog(page)
        page.screenshot(path=str(ROOT/'screenshots/support-offline-dark-en.png'))
        page.get_by_role('button',name='Close support notice',exact=True).click();settle(page)
        # Clipboard rejection is reported through the existing toast surface.
        page.evaluate("Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async()=>{throw Error('clipboard denied')}})")
        page.get_by_role('button',name='Copy group number: '+GROUPS[0],exact=True).click();settle(page)
        assert page.locator('[data-sonner-toast][data-type=error]').filter(has_text='clipboard denied').count()==1
        assert set(page.evaluate('window.__fixture.requests'))=={'hello'}
        assert not errors,errors
        browser.close()
        print('Support smoke passed: every-launch voluntary dialog despite old acknowledgement, GitHub icons and fixed Star link, visible text support button, sequential onboarding, exact group copying, keyboard close, online/failure/timeout fallback, bilingual 800x650 layout; no device requests')


if __name__=='__main__':main()
