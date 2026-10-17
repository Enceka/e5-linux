// Test the production LuCI handlers without device access or a browser timer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const dir = path.join(__dirname, '../luci-app-t551m/htdocs/luci-static/resources');
const source = fs.readFileSync(path.join(dir, 'mu300/charge.js'), 'utf8');
const common = fs.readFileSync(path.join(dir, 'mu300/common.js'), 'utf8');
const catalog = new Function(common.slice(common.indexOf('var DASH_I18N = {'),
  common.indexOf('var DASH_KEYS = ')) + 'return DASH_I18N;')();
const state = () => ({ok:true, available:true, capacity:76, status:'Charging', online:true,
  enabled:true, start:70, stop:80, full_once:false});
function fixture() {
  const elements = {}, calls = [], replies = [state()];
  const card = {style:{}, querySelector(selector) {
    const name = /data-charge="([^"]+)"/.exec(selector)[1];
    return elements[name] ||= {disabled:false, value:'', checked:false, textContent:'', reportValidity:()=>true};
  }};
  const root = {appendChild(child){assert.equal(child,card);}};
  const translate = text => {
    // All user-visible Chinese strings must have both English and Turkish.
    if (/[\u4e00-\u9fff]/.test(text)) {
      assert(catalog[text], 'missing translation: ' + text);
      assert.equal(catalog[text].length, 2);
    }
    return text;
  };
  const M = {translate, localize(node) {
    for (const text of node.innerHTML.matchAll(/>([^<>]*[\u4e00-\u9fff][^<>]*)</g)) translate(text[1]);
  }};
  const rpc = {declare(info){return (...args) => {
    calls.push([info.method, ...args]);
    const reply = replies.shift();
    return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply);
  };}};
  const module = new Function('baseclass','rpc','M','document',source)(
    {extend:x=>x}, rpc, M, {createElement:()=>card});
  return {elements, calls, replies, module, root};
}
const submit = f => f.elements.form.onsubmit({preventDefault(){}});
(async () => {
  const f = fixture(); await f.module.mount(f.root);
  assert.equal(f.elements.capacity.textContent,'76%');
  assert.equal(f.elements.start.value,70);
  assert.equal(f.elements.save.disabled,false);
  f.elements.start.value='85'; f.elements.stop.value='80';
  submit(f); assert.equal(f.calls.length,1);
  assert.match(f.elements.note.textContent,/恢复充电阈值/);
  f.elements.start.value='65'; f.elements.stop.value='85';
  f.replies.push({...state(),start:65,stop:85});
  await submit(f);
  assert.deepEqual(f.calls.at(-1),['configure','1','65','85','0']);
  f.elements.power_on.checked=true;
  f.replies.push({...state(),power_on:true,start:65,stop:85});
  await submit(f);
  assert.deepEqual(f.calls.at(-1),['configure','1','65','85','1']);
  assert.equal(f.elements.power_on.checked,true);
  f.replies.push({...state(),full_once:true});
  await f.elements.once.onclick();
  assert.equal(f.elements.once.disabled,true);
  assert.equal(f.elements.once.textContent,'正在临时充满…');
  // Explicit refresh follows a screen-side settings change.
  f.replies.push({...state(),enabled:false,start:60,stop:90});
  await f.elements.refresh.onclick();
  assert.equal(f.elements.enabled.checked,false);
  assert.equal(f.elements.stop.value,90);
  f.replies.push({ok:false,saved:true,error:'charge_reload_failed'});
  await submit(f); assert.match(f.elements.note.textContent,/已保存.*应用失败/);
  const down = fixture(); down.replies[0]={ok:true,available:false};
  await down.module.mount(down.root); assert.equal(down.elements.save.disabled,true);
  submit(down); assert.equal(down.calls.length,1);
  const failed = fixture(); failed.replies[0]=new Error('connection');
  await failed.module.mount(failed.root);
  assert.equal(failed.elements.save.disabled,true);
  assert.match(failed.elements.note.textContent,/读取失败/);
  // Duplicate requests are blocked until the existing one completes.
  let resolve;
  const pending = fixture(); pending.replies[0]=new Promise(r=>{resolve=r;});
  const loading = pending.module.mount(pending.root);
  pending.elements.refresh.onclick(); assert.equal(pending.calls.length,1);
  assert.equal(pending.elements.refresh.disabled,true);
  resolve(state()); await loading;
  assert.equal(pending.elements.refresh.disabled,false);
  assert(!/setInterval|setTimeout|poll\.add/.test(source));
  console.log('PASS: charge controls, shared settings refresh, threshold checks, charge once, errors, unavailable hardware, request isolation, translations, no polling');
})().catch(error=>{console.error(error);process.exitCode=1;});
