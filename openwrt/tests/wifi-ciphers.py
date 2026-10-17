#!/usr/bin/env python3
"""Capability parsing and the actual generated LuCI cipher controls."""
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
backend = runpy.run_path(str(TOP/'openwrt/luci-app-t551m/root/usr/libexec/e5-wifi-ciphers'))
ui = runpy.run_path(str(TOP/'devices/wifi-ciphers.py'))


class Ciphers(unittest.TestCase):
    def test_native_luci_select_keeps_stored_invalid_cipher(self):
        import os
        source=os.environ.get('E5_TEST_WIRELESS_JS');ui_source=os.environ.get('E5_TEST_UI_JS')
        if not source or not ui_source:
            self.skipTest('pinned wireless.js and ui.js required')
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'www/luci-static/resources/view/network/wireless.js'
            target.parent.mkdir(parents=True);target.write_bytes(Path(source).read_bytes());ui['patch'](root)
            text=target.read_text(encoding="utf-8");begin=text.rfind('o=',0,text.index("'cipher',"));end=text.index('const crypto_modes',begin)
            code=text[begin:end]
            native=Path(ui_source).read_text(encoding="utf-8");native=native[native.index('const UISelect='):native.index('const UIDropdown=')]
            with sync_playwright() as p:
                chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                browser=p.chromium.launch(**({'executable_path':str(chrome)} if chrome.exists() else {}))
                page=browser.new_page()
                result=page.evaluate('''([code,native])=>{
                    const E=(tag,attrs,children=[])=>{const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs||{}))if(v!=null)e.setAttribute(k,v);for(const c of children)e.append(c);return e;};
                    const L={env:{lang:'en'},isObject:x=>x&&typeof x==='object'};
                    const base={extend(methods){function Widget(...args){this.__init__(...args)}Widget.prototype={setUpdateEvents(){},setChangeEvents(){},...methods};return Widget;}};
                    const Select=new Function('UIElement','L','E','dom','_',native+';return UISelect;')(base,L,E,{bindClassInstance(){}},x=>x);
                    const option={keylist:[],labels:{},depends(){},value(v,label){this.keylist.push(v);this.labels[v]=label}};
                    const ss={children:[{option:'encryption',write(){}}],taboption(){return option}};
                    const control=new Function('ss','form','_','e5CipherCaps','L','uci','let o;'+code+';return o;')(ss,{ListValue:{}},x=>x,{suites:['00-0f-ac:4']},L,{get(){return 'sae+gcmp'}});
                    const oldKeys=control.keylist.slice(),oldChoices={...control.labels};
                    const old=new Select('gcmp',oldChoices,{sort:oldKeys});document.body.append(old.render());
                    const value=control.cfgvalue('id');
                    const fixed=new Select(value,control.labels,{sort:control.keylist});document.body.append(fixed.render());
                    return {before:old.getValue(),after:fixed.getValue(),valid:control.validate('id',fixed.getValue())};
                }''',[code,native])
                self.assertEqual(result['before'],'auto')
                self.assertEqual(result['after'],'gcmp')
                self.assertIsInstance(result['valid'],str)
                browser.close()

    def test_parse_oui_not_display_name(self):
        text = '''Wiphy phy0
\tSupported Ciphers:
\t\t* WEP40 (00-0f-ac:1)
\t\t* TKIP (00-0f-ac:2)
\t\t* CCMP-128 (00-0f-ac:4)
\t\t* vendor cipher (00-14-72:1)
\tAvailable Antennas: TX 0 RX 0
\t\t* GCMP-256 (00-0f-ac:9)
'''
        self.assertEqual(backend['parse'](text),['00-0f-ac:1','00-0f-ac:2','00-0f-ac:4','00-14-72:1'])
        self.assertEqual(backend['parse']('no capabilities'),[])

    def test_unknown_radio_and_read_failure_do_not_claim_unsupported(self):
        with patch.object(subprocess,'run') as run:
            self.assertEqual(backend['capabilities']('radio0;reboot'),{})
            run.assert_not_called()
        with patch.object(subprocess,'run',side_effect=OSError('missing ubus')):
            self.assertEqual(backend['capabilities']('radio0'),{})

    def test_real_pinned_luci_source(self):
        # Pass a copy of the pinned image's source; do not modify a release root.
        import os
        source = os.environ.get('E5_TEST_WIRELESS_JS')
        if not source:
            self.skipTest('E5_TEST_WIRELESS_JS=pinned LuCI wireless.js required')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'www/luci-static/resources/view/network/wireless.js'
            target.parent.mkdir(parents=True);target.write_bytes(Path(source).read_bytes())
            ui['patch'](root);first=target.read_text(encoding="utf-8");ui['patch'](root)
            self.assertEqual(target.read_text(encoding="utf-8"),first)
            subprocess.run(['node','--check',str(target)],check=True)
            begin=first.rfind('o=',0,first.index("'cipher',"))
            end=first.index('const crypto_modes',begin)
            code=first[begin:end]
            test='''const assert=require('assert');
const source=JSON.parse(process.argv[1]);
const factory=new Function('ss','form','_','e5CipherCaps','L','uci', 'let o;'+source+';return o;');
function controls(caps,lang='en',encryption='psk2'){
 const opt={keylist:[],depends(){},value(v){this.keylist.push(v)}};
 const ss={children:[{option:'encryption',write(){}}],taboption(){return opt}};
 return factory(ss,{ListValue:{}},x=>x,caps,{env:{lang}},{get(){return encryption}});
}
const native=controls({suites:['00-0f-ac:2','00-0f-ac:4']},'zh-cn');
assert.deepStrictEqual(native.keylist,['auto','ccmp','tkip','tkip+ccmp']);
assert.strictEqual(native.validate('id','ccmp'),true);
assert.strictEqual(typeof native.validate('id','gcmp'),'string');
const other=controls({suites:['00-0f-ac:4','00-0f-ac:8','00-0f-ac:9','00-0f-ac:10']});
assert.deepStrictEqual(other.keylist,['auto','ccmp','ccmp256','gcmp','gcmp256']);
assert.strictEqual(other.validate('id','gcmp'),true);
assert.strictEqual(controls({}).keylist.length,7);
assert.strictEqual(controls({}).validate('id','gcmp'),true);
for (const cipher of ['gcmp','gcmp256','ccmp256']) {
 const saved=controls({suites:['00-0f-ac:4']},'en','sae+'+cipher);
 assert.strictEqual(saved.cfgvalue('id'),cipher);
 assert(saved.keylist.includes(cipher),'stored cipher must not turn into auto');
 assert.strictEqual(typeof saved.validate('id',cipher),'string');
 assert.strictEqual(saved.keylist.filter(v=>v===cipher).length,1);
 saved.cfgvalue('id');assert.strictEqual(saved.keylist.filter(v=>v===cipher).length,1);
}
'''
            subprocess.run(['node','-e',test,json.dumps(code)],check=True)


if __name__ == '__main__':
    unittest.main()
