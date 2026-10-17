"""Wake races with delayed settings responses; no device access."""
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
    args=ap.parse_args()
    fixtures=json.loads(args.fixtures.read_text(encoding='utf-8'))
    fixtures['/api/status']['screen'].update(idle=0,lock_enabled=False,awake=True)
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            path=urlsplit(self.path).path
            if not path.startswith('/api/'):return super().do_GET()
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(fixtures.get(path,{})).encode())
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(args.webroot)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
            browser=p.chromium.launch(**({'executable_path':str(chrome)} if chrome.exists() else {}))
            page=browser.new_page(viewport={'width':320,'height':480});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.wait_for_function("typeof last!=='undefined' && last!==null && !T551M.isLocked()")
            page.evaluate('''()=>{
                const native=fetch;window.reads=[];
                window.fetch=(url,options)=>url==='/api/settings/charge' ?
                    new Promise(resolve=>reads.push(value=>resolve(new Response(JSON.stringify({items:[{id:'x',label:'State',type:'number',value}]}))))) : native(url,options);
                showPage(P.settings);st=[{view:'cat',cat:{id:'charge',label:'Charging'},items:[{id:'x',label:'State',type:'number',value:0}]}];stRender();
                window.wake=()=>{setBlank(true);setBlank(false)};
                wake();
            }''')
            page.wait_for_function('reads.length === 1')
            page.evaluate('wake();reads[0](1)')
            page.wait_for_function('reads.length === 2',timeout=5000)
            assert page.evaluate('stTop().items[0].value')==0,'old wake response must not paint'
            page.evaluate('reads[1](2)')
            page.wait_for_function('stWakeRequest === null && stTop().items[0].value === 2')
            # Leaving during a slow request must not repaint a hidden category.
            page.evaluate('wake()');page.wait_for_function('reads.length === 3')
            page.evaluate("showPage(P.overview);reads[2](3)")
            page.wait_for_function('stWakeRequest === null')
            assert page.evaluate('stTop().items[0].value')==2
            # Waking with an open editor keeps the draft and performs no category read.
            page.evaluate("showPage(P.settings);st.push({view:'edit',cat:stTop().cat,parent:stTop(),item:{id:'x',label:'Draft',type:'number',value:7}});stRender();wake()")
            page.wait_for_timeout(350)
            assert page.evaluate("stTop().view === 'edit' && stTop().item.value === 7 && reads.length === 3")
            assert not errors,errors
            browser.close()
            print('PASS: repeated wake refreshes latest state, stale/hidden responses discarded, editor retained')
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':main()
