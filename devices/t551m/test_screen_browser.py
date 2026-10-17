"""Touch gesture/navigation regressions in Chromium using captured local API data.

Usage: python devices/t551m/test_screen_browser.py --fixtures FILE --webroot DIR
The test server never contacts or changes a real device.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--fixtures',type=Path,required=True)
    ap.add_argument('--webroot',type=Path,required=True)
    ap.add_argument('--screenshots',type=Path,default=Path('logs/t551m'))
    args=ap.parse_args()
    fixtures=json.loads(args.fixtures.read_text(encoding='utf-8'))
    posts=[]
    gets=[]
    power_reply={'ok':True}
    fixtures['/api/status']['screen']['idle']=0
    fixtures['/api/status']['screen']['ui_size']='standard'
    fixtures['/api/status']['sims']=[
        {'slot':0,'present':True,'operator':'CHN-UNICOM','registration':'home','radio_label':'4G','signal':{'rsrp':-91}},
        {'slot':1,'present':True,'operator':'46011','registration':'camped','radio_label':'5G SA','signal':{'rsrp':-104}}]
    for i, value in enumerate([0,1,2,3,7],1):
        fixtures['/api/status']['screen'][f'nav_slot{i}']=str(value)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlsplit(self.path).path
            gets.append(path)
            if path=='/api/qr':
                qr=args.fixtures.with_name('screen-wifi.svg')
                self.send_response(200);self.send_header('Content-Type','image/svg+xml');self.end_headers();self.wfile.write(qr.read_bytes());return
            if not path.startswith('/api/'):
                return super().do_GET()
            body=json.dumps(fixtures.get(path,{})).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
            posts.append((self.path,data))
            if self.path=='/api/backlight':fixtures['/api/status']['screen']['awake']=data.get('level',0)>0
            if self.path in ['/api/settings/ui','/api/settings/navigation']: fixtures['/api/status']['screen'][data['id']]=data['value']
            body=power_reply if self.path=='/api/settings/system' else {'ok':True}
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(body).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(args.webroot)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    args.screenshots.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        executable=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        browser=p.chromium.launch(**({'executable_path':str(executable)} if executable.exists() else {}))
        page=browser.new_page(viewport={'width':320,'height':480},has_touch=True,device_scale_factor=1)
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        page.wait_for_function("typeof last !== 'undefined' && last !== null")
        page.wait_for_timeout(700)
        assert page.evaluate('T551M.isLocked()')
        assert not errors,errors
        page.screenshot(path=str(args.screenshots/'screen-lock.png'))
        assert page.locator('#bar-op').inner_text()=='中国联通'
        assert page.locator('#bar-tech').inner_text()=='4G'
        assert page.locator('#sim-operator-1').text_content()=='中国电信'
        assert page.locator('#sim-radio-0').text_content()=='4G'
        assert page.locator('#sim-radio-1').text_content()=='5G SA'
        assert page.locator('#sim-note-1').text_content()=='注册详情未上报'
        assert page.locator('#hero-uptime-label').text_content()=='本次运行时长'
        assert page.locator('#hero-uptime').text_content() not in ('—','')
        assert page.locator('[data-title="signal"] .meter .mh > span:first-child').all_text_contents()==['RSRP','SINR','RSRQ']
        original_signal=page.evaluate('last.modem.signal')
        for snr in [4,0,-3.5,None]:
            page.evaluate('(snr)=>{last.modem.signal={rsrp:-91,rsrq:-13,snr};renderSignal(last)}',snr)
            shown=page.locator('#sg-sinr').text_content()
            assert shown=='--' if snr is None else shown.startswith(f'{snr:.1f} dB'),shown
        page.evaluate('(signal)=>{last.modem.signal=signal;renderSignal(last)}',original_signal)
        assert page.locator('#bar-dual').is_visible()
        assert page.locator('#bar-signal-0 .on').count()==3
        assert page.locator('#bar-signal-1 .on').count()==2
        for single in [0,1]:
            result=page.evaluate('''single=>{
                const sims=last.sims;last.sims=sims.map(s=>({...s,present:s.slot===single}));
                T551M.status(last);renderBar(last);
                const out={hidden:document.querySelector('#bar-dual').hidden,bars:document.querySelectorAll('#bar-bars .on').length};
                last.sims=sims;T551M.status(last);renderBar(last);return out;
            }''',single)
            assert result=={'hidden':True,'bars':3 if single==0 else 2},result
        assert page.evaluate("T551M.operator('Vodafone')")=='Vodafone'
        original_usb=page.evaluate('last.usb')
        for usb, title in [({'role':'device','link':'lease','devices':[]},'USB 已连接'),
                           ({'role':'device','cable':True,'port':'SDP','state':'not attached','link':'host','devices':[]},None),
                           ({'role':'device','cable':True,'port':'DCP','link':'charger','devices':[]},None),
                           ({'role':'host','link':'otg','devices':[{'name':'RTL8153 Ethernet','kind':'ethernet'}]},'USB 网卡 · RTL8153 Ethernet 已连接'),
                           ({'role':'host','link':'otg','devices':[{'name':'USB Audio'},{'name':'USB 10/100/1000 LAN','kind':'ethernet'}]},'USB Audio 已连接\nUSB 网卡 · USB 10/100/1000 LAN 已连接'),
                           ({'role':'host','link':'otg','devices':[{'name':'USB','kind':'ethernet'}]},'USB 网卡 已连接')]:
            page.evaluate('(usb)=>{last.usb=usb;T551M.status(last)}',usb)
            if title is None:
                assert page.locator('#home-usb').evaluate('(node)=>node.hidden')
                continue
            assert page.locator('#home-usb-title').text_content()==title
            assert not page.locator('#home-usb').evaluate('(node)=>node.hidden')
            assert page.locator('#home-usb-title').evaluate('(n)=>n.scrollWidth<=n.clientWidth && n.scrollHeight<=n.clientHeight')
            if len(usb['devices'])>1:
                assert 'USB 网卡' in page.evaluate('usbText(last.usb)')
                assert page.locator('#home-usb-title').evaluate('(n)=>getComputedStyle(n).whiteSpace')=='pre-line'
        page.evaluate("last.usb={role:'none',link:'none',devices:[]};T551M.status(last)")
        assert page.locator('#home-usb').evaluate('(node)=>node.hidden')
        page.evaluate('(usb)=>{last.usb=usb;T551M.status(last)}',original_usb)
        assert page.evaluate("T551M.amount(15830406)")=='15.83 MB'
        # Stable snapshots do not rebuild metrics/themes. Dark snapshots retain
        # fresh data without painting; wake must immediately use the latest one.
        counts=page.evaluate('''() => {
            T551M.status(last);
            const watched=new MutationObserver(()=>{});
            watched.observe(document.body,{subtree:true,childList:true,attributes:true,characterData:true});
            for(let i=0;i<20;i++)T551M.status(last);
            const unchanged=watched.takeRecords().length;
            setBlank(true);watched.takeRecords();
            const old=last.traffic.rx_rate;last.traffic.rx_rate=987654;
            T551M.status(last);
            const dark=watched.takeRecords().length;
            setBlank(false);
            const fresh=document.getElementById('lock-rx').textContent===T551M.speed(987654).join('');
            last.traffic.rx_rate=old;T551M.status(last);watched.disconnect();
            return {unchanged,dark,fresh};
        }''')
        assert counts=={'unchanged':0,'dark':0,'fresh':True},counts
        page.wait_for_timeout(500)  # retain the wake guard before gesture tests
        # Same byte-rate source and formatter for home/lock, including live changes.
        for unit, expected in [(None,['10','Mbps']),('bits',['10','Mbps']),('bytes',['1.19','MB/s']),('mbps',['10','Mbps']),('mbs',['1.19','MB/s']),('auto',['1.19','MB/s'])]:
            page.evaluate('(unit)=>{last.screen.speed_unit=unit;T551M.status(last)}',unit)
            assert page.evaluate('T551M.speed(1250000)')==expected
            for direction in ['rx','tx']:
                shown=page.locator('#ov-'+direction).inner_text()+page.locator('#ov-'+direction+'-u').inner_text()
                assert page.locator('#lock-'+direction).text_content()==shown
            assert page.evaluate('T551M.amount(15830406)')=='15.83 MB'
        page.evaluate("last.screen.speed_unit='bits';T551M.status(last)")
        for value, expected in [(0,['0','bps']),(-1,['0','bps']),(100,['800','bps']),(125,['1','Kbps']),
                                (125000,['1','Mbps']),(125000000,['1','Gbps']),
                                (124999.5,['1','Mbps']),(None,['—','bps']),(1000000000,['8','Gbps'])]:
            assert page.evaluate('(v)=>T551M.speed(v)',value)==expected
        assert page.evaluate('T551M.speed(NaN)')==['—','bps']
        page.evaluate("last.screen.speed_unit='bytes';T551M.status(last)")
        for value, expected in [(1023,['1023','B/s']),(1024,['1','KB/s']),(1048576,['1','MB/s']),(1073741824,['1','GB/s'])]:
            assert page.evaluate('(v)=>T551M.speed(v)',value)==expected
        page.evaluate("last.screen.speed_unit='bits';T551M.status(last)")
        page.evaluate("document.documentElement.lang='en'")
        assert page.evaluate("T551M.operator('CHN-UNICOM')")=='China Unicom'
        page.evaluate("document.documentElement.lang='zh'")
        cdp=page.context.new_cdp_session(page)
        def touch(kind, points):
            cdp.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':[{'x':x,'y':y,'id':i,'radiusX':3,'radiusY':3} for i,(x,y) in enumerate(points)]})
        def swipe(x=160,y=425,end_x=160,end_y=240,steps=14,delay=20):
            touch('touchStart',[(x,y)])
            for i in range(1,steps+1):
                touch('touchMove',[(x+(end_x-x)*i/steps,y+(end_y-y)*i/steps)])
                page.wait_for_timeout(delay)
            touch('touchEnd',[])
            page.wait_for_timeout(320)
        # A quick flick shorter than the distance threshold gains momentum.
        swipe(end_y=325,steps=4,delay=10)
        assert not page.evaluate('T551M.isLocked()'), 'fast 100px flick should unlock'
        page.wait_for_timeout(500)
        page.locator('#mobile-lock').tap(); page.wait_for_timeout(500)
        # Stopping before release loses inertia, as does reversing direction.
        touch('touchStart',[(160,425)])
        for y in [405,385,365,345]:
            touch('touchMove',[(160,y)]); page.wait_for_timeout(16)
        page.wait_for_timeout(160); touch('touchEnd',[]); page.wait_for_timeout(350)
        assert page.evaluate('T551M.isLocked()'), 'held short swipe must not unlock'
        touch('touchStart',[(160,425)])
        for y in [380,330,270,290]:
            touch('touchMove',[(160,y)]); page.wait_for_timeout(20)
        touch('touchEnd',[]); page.wait_for_timeout(350)
        assert page.evaluate('T551M.isLocked()'), 'reversal must cancel unlock'
        # Tap, short/sideways/top-origin swipe cannot unlock or change page.
        page.touchscreen.tap(35,450)
        swipe(end_y=380)
        swipe(end_x=270,end_y=350)
        swipe(y=80,end_y=0)
        assert page.evaluate('T551M.isLocked() && page === 0')
        # A second finger cancels the entire gesture.
        touch('touchStart',[(150,425)]); touch('touchMove',[(150,375)])
        touch('touchStart',[(150,375),(200,400)])
        touch('touchMove',[(150,230),(200,255)]); touch('touchEnd',[])
        page.wait_for_timeout(300)
        assert page.evaluate('T551M.isLocked()')
        # Mid-drag follows the finger; cancellation springs back.
        touch('touchStart',[(160,425)]); touch('touchMove',[(160,355)])
        transform=page.locator('#mobile-lockscreen').evaluate('(e)=>getComputedStyle(e).transform')
        assert '-70' in transform,transform
        page.screenshot(path=str(args.screenshots/'screen-lock-drag.png'))
        touch('touchCancel',[]); page.wait_for_timeout(300)
        assert page.evaluate('T551M.isLocked()')
        swipe()
        assert not page.evaluate('T551M.isLocked()')
        page.wait_for_timeout(500)
        page.screenshot(path=str(args.screenshots/'screen-home.png'))
        for index in (1,2,3,4,7,0):
            if index==4:
                page.locator('#mobile-more').tap(); page.wait_for_timeout(280)
                page.locator('#mobile-menu [data-page="4"]').tap()
            else:
                page.locator(f'#mobile-nav [data-page="{index}"]').tap()
            page.wait_for_timeout(300)
            assert page.evaluate('page')==index
            if index==4:
                page.wait_for_selector('#hs-qr svg')
                page.screenshot(path=str(args.screenshots/'screen-hotspot.png'))
                assert page.locator('#hs-qr svg').evaluate('(e)=>getComputedStyle(e).stroke')=='none'
        assert page.locator('#mobile-nav').bounding_box()['height']==52
        page.locator('#mobile-nav [data-page="7"]').tap()
        page.wait_for_timeout(300)
        page.locator('#st-view button').filter(has_text='界面与锁屏').tap()
        page.wait_for_timeout(300)
        assert page.locator('#st-view').inner_text().find('顶部状态栏')>=0
        assert '底部入口' not in page.locator('#st-view').inner_text()
        page.screenshot(path=str(args.screenshots/'screen-settings.png'))
        # Switching away preserves the route; reselecting its tab resets it.
        page.locator('#mobile-nav [data-page="0"]').tap(); page.wait_for_timeout(300)
        page.locator('#mobile-nav [data-page="7"]').tap(); page.wait_for_timeout(300)
        assert page.evaluate('st.length')>1
        page.locator('#mobile-nav [data-page="7"]').tap(); page.wait_for_timeout(300)
        assert page.evaluate('st.length === 1 && stTop().view === "menu"')
        page.locator('#st-view button').filter(has_text='底部导航').tap(); page.wait_for_timeout(300)
        assert page.locator('#st-view .strow').count()==5
        assert '底部入口 5' in page.locator('#st-view').inner_text()
        page.locator('#mobile-nav [data-page="7"]').tap(); page.wait_for_timeout(300)
        # All five custom choices are reflected, including pages absent by default.
        for i, value in enumerate([5,6,2,3,7],1):
            fixtures['/api/status']['screen'][f'nav_slot{i}']=str(value)
        page.evaluate("poll()")
        page.wait_for_function("document.querySelector('#mobile-nav button').dataset.page === '5'")
        for index in [5,6,2,3,7]:
            page.locator(f'#mobile-nav [data-page="{index}"]').tap(); page.wait_for_timeout(300)
            assert page.evaluate('page')==index
        # Physical arrows and visual ordering follow the customized navigation.
        page.evaluate('showPage(5)')
        for key, target in [('ArrowRight',6),('ArrowRight',2),('ArrowLeft',6)]:
            page.keyboard.press(key); page.wait_for_timeout(300)
            assert page.evaluate('page')==target
            assert abs(page.evaluate('pages[page].getBoundingClientRect().left')) < 2
        # Unlock refreshes only the visible category, not an unsaved editor.
        fixtures['/api/settings/charge']={'items':[{'id':'power_on','label':'Wake test','type':'toggle','value':True}]}
        page.evaluate("showPage(P.settings);st=[{view:'menu'},{view:'cat',cat:{id:'charge',label:'Charge'},items:[]}];stRender();setBlank(true);setBlank(false)")
        before=gets.count('/api/settings/charge')
        page.wait_for_timeout(500);swipe();page.wait_for_function("stTop().items[0]?.id === 'power_on'")
        assert gets.count('/api/settings/charge')==before+1
        page.evaluate("st.push({view:'edit',cat:stTop().cat,item:{id:'x',label:'Unsaved',type:'number',value:7},parent:stTop()});stRender();setBlank(true);setBlank(false)")
        page.wait_for_timeout(500);swipe();page.wait_for_timeout(400)
        assert page.evaluate("stTop().view === 'edit' && stTop().item.value === 7")
        assert gets.count('/api/settings/charge')==before+1
        page.evaluate("st=[{view:'menu'}];stRender()")
        # Display size changes actual type and control height; no page overflows.
        sizes=[]
        for size in ['small','standard','large','extra']:
            fixtures['/api/status']['screen']['ui_size']=size
            page.evaluate(f"last.screen.ui_size='{size}'; T551M.status(last)")
            sizes.append(page.locator('#st-view .strow').first.evaluate('(e)=>({font:parseFloat(getComputedStyle(e).fontSize),height:e.getBoundingClientRect().height})'))
            for index in [0,1,2,4,5,6,7,8]:
                page.evaluate(f'showPage({index})');page.wait_for_timeout(260)
                overflow=page.evaluate('pages[page].scrollWidth > pages[page].clientWidth')
                assert not overflow,(size,index,'horizontal overflow')
            page.evaluate('showPage(7)'); page.wait_for_timeout(280)
            page.screenshot(path=str(args.screenshots/f'screen-size-{size}.png'))
        assert sizes[-1]['font']/sizes[1]['font']>1.35,sizes
        assert sizes[-1]['height']>sizes[1]['height']*1.3,sizes
        fixtures['/api/status']['screen']['ui_size']='standard'
        page.evaluate("last.screen.ui_size='standard';T551M.status(last)")
        # Confirmation text has its own row, including the tiny SIM tick slot.
        for language in ['zh','en']:
            for size in ['standard','extra']:
                page.evaluate('''([language,size])=>{
                    lang=language;last.screen.ui_size=size;T551M.status(last);showPage(P.settings);
                    const parent={view:'cat',cat:{id:'network',label:'Network'},items:[]};
                    const item={id:'sim_card',type:'choice',label:'SIM',confirm:true,value:'0',
                        options:[{value:'0',label:'SIM 1'},{value:'1',label:'SIM 2'},{value:'2',label:'Long option label for another setting'}]};
                    st=[{view:'menu'},parent,{view:'edit',cat:parent.cat,item,parent}];stRender();
                }''',[language,size])
                before=len(posts)
                page.locator('[data-st="opt:1"]').tap()
                row=page.locator('[data-st="opt:1"]')
                assert row.locator('.st-label').inner_text()=='SIM 2'
                assert row.locator('.st-confirm-hint').count()==1
                bounds=row.evaluate('''e=>{const r=e.getBoundingClientRect(),h=e.querySelector('.st-confirm-hint').getBoundingClientRect();
                    return {fits:h.left>=r.left&&h.right<=r.right&&h.bottom<=r.bottom,overflow:e.scrollWidth>e.clientWidth};}''')
                assert bounds['fits'] and not bounds['overflow'],(language,size,bounds)
                if language=='zh' and size=='extra':
                    page.screenshot(path=str(args.screenshots/'screen-sim-confirm-extra.png'))
                assert len(posts)==before,'First confirmation press must not apply the setting'
                page.locator('[data-st="opt:2"]').tap()
                assert row.locator('.st-confirm-hint').count()==0
                assert page.locator('#st-view .armed').count()==1
                page.evaluate('stDisarm()')
                assert page.locator('#st-view .st-confirm-hint').count()==0
        page.evaluate("lang='zh';last.screen.ui_size='standard';T551M.status(last);st=[{view:'menu'}];stRender()")
        # Appearance changes every surface without fading content or QR codes.
        for theme, rgb, foreground in [('dark','24, 33, 46','rgb(241, 245, 250)'),('light','255, 255, 255','rgb(23, 40, 59)')]:
            for opacity in [0,35,70,100]:
                appearance={'ui_theme':theme,'ui_opacity':opacity,'desktop_wallpaper':'custom','lock_wallpaper':'custom'}
                fixtures['/api/status']['screen'].update(appearance)
                page.evaluate('(s)=>{Object.assign(last.screen,s);T551M.status(last)}',appearance)
                expected=f'rgb({rgb})' if opacity==100 else f'rgba({rgb}, {opacity/100:g})'
                for selector in ['.card:not(.rates)','.strow','.mobile-grid button','#lock-summary']:
                    style=page.locator(selector).first.evaluate('(e)=>({bg:getComputedStyle(e).backgroundColor,opacity:getComputedStyle(e).opacity,color:getComputedStyle(e).color})')
                    assert style['bg']==expected,(theme,opacity,selector,style)
                    assert style['opacity']=='1'
                assert page.locator('body').evaluate('(e)=>getComputedStyle(e).color')==foreground
                sim=page.locator('#bar-sim').evaluate('(e)=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})')
                assert sim['bg']==foreground and sim['fg']!=sim['bg'],(theme,sim)
                assert page.locator('#hs-qr').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(255, 255, 255)'
        appearance={'ui_theme':'dark','ui_opacity':70,'desktop_wallpaper':'default','lock_wallpaper':'default'}
        fixtures['/api/status']['screen'].update(appearance)
        page.evaluate('(s)=>{Object.assign(last.screen,s);T551M.status(last)}',appearance)
        assert page.locator('.card:not(.rates)').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(24, 33, 46)'
        # Wake remains locked; dark touches and immediate wake noise are blocked.
        page.evaluate('setBlank(true)')
        swipe()
        assert page.evaluate('blank && T551M.isLocked()')
        page.evaluate('setBlank(false)')
        # Dispatch in one task to avoid CDP frame pacing stretching a burst into
        # a deliberate swipe. The timing matrix covers an early sustained swipe.
        page.evaluate('''() => {
            const target=document.querySelector('#mobile-lockscreen');
            for(const [type,y] of [['pointerdown',425],['pointermove',350],['pointerup',270]])
                target.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,pointerType:'mouse',buttons:type==='pointerup'?0:1,clientX:160,clientY:y}));
        }''')
        page.wait_for_timeout(320)
        assert page.evaluate('!blank && T551M.isLocked()')
        page.wait_for_timeout(500)
        swipe()
        assert not page.evaluate('T551M.isLocked()')
        # All config combinations remain navigable, with settings accessible.
        page.evaluate("last.screen.nav_bar=false;last.screen.status_bar=false;last.screen.ui_accent='violet';last.screen.ui_density='compact';T551M.status(last)")
        assert not page.locator('#mobile-nav').is_visible()
        assert not page.locator('#bar').is_visible()
        page.wait_for_timeout(500)
        page.locator('#mobile-more').tap()
        page.wait_for_timeout(280)
        assert page.locator('#mobile-menu').is_visible()
        assert page.locator('#mobile-menu [data-page]').count()==9
        page.screenshot(path=str(args.screenshots/'screen-menu.png'))
        button=page.locator('#mobile-menu-close').bounding_box()
        icon=page.locator('#mobile-menu-close svg').bounding_box()
        assert abs(button['x']+button['width']/2-icon['x']-icon['width']/2)<1
        assert abs(button['y']+button['height']/2-icon['y']-icon['height']/2)<1
        page.locator('#mobile-menu-close').tap()
        page.wait_for_timeout(280)
        assert not page.locator('#mobile-menu').is_visible()
        # Compact signal identity: one baseline, operator and RAT same type size.
        page.evaluate("last.screen.nav_bar=true;last.screen.status_bar=true;T551M.status(last);showPage(1)")
        page.wait_for_timeout(300)
        for size in ['standard','extra']:
            page.evaluate('(s)=>{last.screen.ui_size=s;T551M.status(last)}',size)
            geometry=page.evaluate('''() => {
                const op=document.querySelector('#sg-op'),tech=document.querySelector('#sg-tech'),band=document.querySelector('#sg-band');
                const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,height:r.height}};
                return {op:rect(op),tech:rect(tech),band:rect(band),font:[op,tech,band].map(e=>parseFloat(getComputedStyle(e).fontSize)),card:rect(op.parentNode)};
            }''')
            assert geometry['font'][0]==geometry['font'][1]>geometry['font'][2],geometry
            assert geometry['op']['right']<=geometry['tech']['x'] and geometry['tech']['right']<=geometry['band']['x'],geometry
            assert geometry['band']['right']<=geometry['card']['right'],geometry
            assert geometry['card']['height']<70,geometry
        page.evaluate("last.screen.ui_size='standard';T551M.status(last)")
        page.screenshot(path=str(args.screenshots/'screen-signal-compact.png'))
        # Hardware call opens the installed app from pages and plugin frames;
        # repeats neither reload it nor reach the plugin's dial action.
        page.route('**/plugins/phone/**', lambda route: route.fulfill(
            content_type='text/html', body='<html><head></head><body>Phone<input id="number"><script>window.calls=0;addEventListener("keydown",e=>{if(e.key==="F13")calls++});</script></body></html>'))
        fixtures['/api/plugins']={'plugins':[{'id':'phone','name':'电话'}]}
        page.evaluate('apps=null')
        def call_key():
            page.evaluate('''()=>{
                const target=document.activeElement?.contentDocument?.activeElement || document.activeElement;
                target.dispatchEvent(new KeyboardEvent('keydown',{key:'F13',keyCode:124,bubbles:true,cancelable:true}));
                target.dispatchEvent(new KeyboardEvent('keyup',{key:'F13',keyCode:124,bubbles:true,cancelable:true}));
            }''')
        call_key()
        page.wait_for_function("appOpen?.id === 'phone' && document.querySelector('#app-frame').contentDocument?.__e5InputObserver")
        page.locator('#app-frame').content_frame.locator('#number').fill('123')
        page.evaluate("document.querySelector('#app-frame').contentDocument.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'F13',repeat:true,bubbles:true}))")
        call_key()
        assert page.locator('#app-frame').content_frame.locator('#number').input_value()=='123'
        assert page.evaluate("document.querySelector('#app-frame').contentWindow.calls")==0
        # Closing via the visible toolbar must restore the source page, without
        # focusing an off-screen Apps button or a stale blank iframe load.
        origin=page.evaluate('page')
        page.locator('#mobile-back').tap()
        page.wait_for_timeout(400)
        returned=page.evaluate('''()=>({page,app:appOpen,focus:document.activeElement.id,
            x:pages[page].getBoundingClientRect().x,scroll:document.querySelector('#pages').scrollLeft})''')
        assert returned['page']==origin and returned['app'] is None and abs(returned['x'])<1,returned
        assert returned['focus']!='app-frame',returned
        for source in [0,7,8]:
            page.evaluate('(n)=>showPage(n)',source)
            page.wait_for_timeout(300)
            page.evaluate("(pages[page].querySelector('button') || document.querySelector('#mobile-back')).focus({preventScroll:true})")
            call_key()
            page.wait_for_function("appOpen?.id === 'phone' && document.querySelector('#app-frame').contentDocument?.__e5InputObserver")
            assert page.locator('#mobile-title').inner_text()=='电话'
            page.locator('#mobile-back').tap();page.wait_for_timeout(300)
            restored=page.evaluate('''()=>({page,app:appOpen,x:pages[page].getBoundingClientRect().x,
                focus:document.activeElement.tagName,load:document.querySelector('#app-frame').onload,
                rootScroll:document.body.scrollLeft+document.documentElement.scrollLeft})''')
            assert restored['page']==source and restored['app'] is None,restored
            assert abs(restored['x'])<1 and restored['rootScroll']==0,restored
            assert restored['focus']!='IFRAME' and restored['load'] is None,restored
        call_key()
        page.wait_for_function("appOpen?.id === 'phone' && document.querySelector('#app-frame').contentDocument?.__e5InputObserver")
        page.route('**/plugins/other/**', lambda route: route.fulfill(content_type='text/html',body='<body id="other-app">Other app</body>'))
        page.evaluate("openApp({id:'other',name:'Other'})")
        page.wait_for_function("document.querySelector('#app-frame').contentDocument?.body?.id === 'other-app' && document.querySelector('#app-frame').contentDocument.__e5InputObserver")
        call_key()
        page.wait_for_function("appOpen?.id === 'phone'")
        page.evaluate("closeApp();showPage(P.settings)")
        call_key()
        page.wait_for_function("appOpen?.id === 'phone'")
        page.evaluate("closeApp();setBlank(true)")
        call_key()
        assert page.evaluate('blank && T551M.isLocked()')
        for key in ['Enter','ArrowUp','ArrowDown','F1','ContextMenu','Backspace','1','AudioVolumeUp','AudioVolumeDown']:
            page.keyboard.press(key)
            assert page.evaluate('blank && T551M.isLocked()'), key
        page.touchscreen.tap(160,250)
        assert page.evaluate('blank && T551M.isLocked()')
        page.evaluate("window.dispatchEvent(new KeyboardEvent('keydown',{key:'Power',bubbles:true}));window.dispatchEvent(new KeyboardEvent('keyup',{key:'Power',bubbles:true}))")
        assert page.evaluate('!blank && T551M.isLocked()')
        call_key()
        assert page.evaluate('appOpen') is None
        page.wait_for_timeout(500);swipe();page.wait_for_timeout(400)
        assert not page.evaluate('T551M.isLocked()')
        def power_event(kind,repeat=False,frame=False):
            page.evaluate('''([kind,repeat,frame])=>{
                const target=frame?document.querySelector('#test-power-frame').contentWindow:window;
                target.dispatchEvent(new KeyboardEvent(kind,{key:'Power',repeat,bubbles:true,cancelable:true}));
            }''',[kind,repeat,frame])
        def hold_power(frame=False):
            power_event('keydown',frame=frame)
            page.wait_for_timeout(1300)
            power_event('keydown',True)
            power_event('keyup')
            page.wait_for_timeout(150)
            assert page.locator('#power-menu').is_visible()
        # Short presses toggle only on release; a held key never retriggers it.
        power_event('keydown'); page.wait_for_timeout(80)
        assert not page.evaluate('blank')
        power_event('keyup'); page.wait_for_timeout(100)
        assert page.evaluate('blank')
        vibrations=len([r for r in posts if r[0]=='/api/vibrate'])
        hold_power()
        assert not page.evaluate('blank') and page.evaluate('T551M.isLocked()')
        assert len([r for r in posts if r[0]=='/api/vibrate'])==vibrations+1
        page.screenshot(path=str(args.screenshots/'screen-power-menu.png'))
        page.locator('[data-power=reboot]').tap()
        assert not [r for r in posts if r[0]=='/api/settings/system']
        page.locator('[data-cancel]').tap() # Back to choices, then dismiss.
        page.locator('[data-cancel]').tap()
        assert page.evaluate('T551M.isLocked()')
        # Frame focus receives the same capture handler; release can land in parent.
        page.evaluate('''()=>{const f=document.createElement('iframe');f.id='test-power-frame';document.body.appendChild(f);T551MPower.attach(f.contentWindow);}''')
        hold_power(frame=True)
        page.locator('[data-cancel]').tap()
        page.evaluate("document.querySelector('#test-power-frame').remove()")
        # A lost key release cancels on focus loss, without a delayed phantom menu.
        power_event('keydown')
        page.evaluate("window.dispatchEvent(new Event('blur'))")
        page.wait_for_timeout(1250)
        assert not page.locator('#power-menu').is_visible()
        power_event('keyup')
        # The three actions send exactly one request, only after confirmation.
        for action in ['poweroff','reboot','android_once']:
            page.reload();page.wait_for_function("typeof last !== 'undefined' && last !== null");page.wait_for_timeout(500)
            hold_power()
            page.locator(f'[data-power={action}]').tap()
            before=len([r for r in posts if r[0]=='/api/settings/system'])
            if action=='android_once':
                assert '默认启动系统' in page.locator('.power-note').first.inner_text()
                power_reply['ok']=False
                page.locator('[data-confirm]').tap();page.wait_for_timeout(150)
                assert page.locator('[data-confirm]').is_enabled()
                assert '失败' in page.locator('#power-error').inner_text()
                before+=1;power_reply['ok']=True
            page.locator('[data-confirm]').tap();page.wait_for_timeout(150)
            requests=[r for r in posts if r[0]=='/api/settings/system']
            assert len(requests)==before+1 and requests[-1][1]=={'id':action},requests
            assert page.locator('[data-confirm]').is_disabled()
        assert not errors,errors
        print(json.dumps({'gesture_checks':'PASS','navigation':'PASS','settings':'PASS','appearance':'PASS','speed_units':'PASS','wake_guard':'PASS','power_menu':'PASS','dial_key':'PASS','signal_layout':'PASS','js_errors':errors}))
        browser.close()
    server.shutdown()


if __name__=='__main__':main()
