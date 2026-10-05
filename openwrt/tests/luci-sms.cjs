// Live LuCI rendering test; reads configuration, never saves it. All SMS sends are intercepted.
const fs=require('fs'),assert=require('assert/strict');
const {chromium}=require(process.env.E5_PLAYWRIGHT||'playwright');
const path=require('path'),os=require('os');
const output=process.env.E5_TEST_OUTPUT||path.join(os.tmpdir(),'e5-sms-ui');fs.mkdirSync(output,{recursive:true});
const base=process.env.E5_LUCI_URL;if(!base)throw new Error('Set E5_LUCI_URL to a test LuCI instance. SMS sending is mocked.');
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/ubus/**',async route=>{
  let payload;try{payload=route.request().postDataJSON();}catch{};
  const batch=Array.isArray(payload)?payload:[payload];
  if(batch.some(req=>req?.params?.[1]==='e5-sms' && req.params[2]==='send')){
   const request=batch.find(req=>req.params[2]==='send');assert.equal(typeof request.params[3].card,'string');
   return route.fulfill({json:batch.map(req=>({jsonrpc:'2.0',id:req.id,result:[0,{ok:false,error:'fixture send error'}]}))});
  }
  if(batch.some(req=>req?.params?.[1]==='e5-sms' && ['list','forward_log'].includes(req.params[2]))){
   const response=await route.fetch();const original=await response.json();
   const results=Array.isArray(original)?original:[original];
   const reply=results.map(res=>{
    const req=batch.find(req=>req.id===res.id);
    if(req?.params?.[1]!=='e5-sms')return res;
    if(req.params[2]==='list')return {jsonrpc:'2.0',id:req.id,result:[0,{sim:{card:0,name:'SIM1',state:'connected'},dual_sim:true,slots:{0:{ok:true},1:{ok:true}},messages:[{id:1000000000,card:0,sim:'SIM1',number:'10086',text:'卡一测试短信',state:'received',direction:'in',time:'2026-10-05T20:00:00+08:00'},{id:1000000001,card:1,sim:'SIM2',number:'10010',text:'卡二 <script>safe</script> 测试短信',state:'received',direction:'in',time:'2026-10-05T20:01:00+08:00'}]}]};
    if(req.params[2]==='forward_log')return {jsonrpc:'2.0',id:req.id,result:[0,{log:[]}]};
    return res;
   });
   return route.fulfill({response,json:Array.isArray(original)?reply:reply[0]});
  }
  return route.continue();
 });
 await page.goto(`${base}/cgi-bin/luci/admin/services/e5-sms`);
 if(await page.locator('input[name="luci_password"]').count()){
  await page.locator('input[name="luci_password"]').fill(process.env.E5_LUCI_PASSWORD||'root');
  await page.locator('input[type="submit"]').click();
 }
 await page.waitForSelector('.e5-sms-page');
 assert((await page.locator('.e5-sms-page').textContent()).includes('仅选择本次发送卡'));
 const mode=page.locator('[id="widget.cbid.e5-notify.forward.mode"]');
 const shared=page.locator('[data-field="cbid.e5-notify.forward.url"]');
 const one=page.locator('[data-field="cbid.e5-notify.forward_sim1.url"]');
 const two=page.locator('[data-field="cbid.e5-notify.forward_sim2.url"]');
 assert(await shared.isVisible());assert(!await one.isVisible());
 await mode.selectOption('per_sim');assert(await one.isVisible());assert(await two.isVisible());assert(!await shared.isVisible());
 await one.locator('input').fill('https://fixture.invalid/sim1');
 await mode.selectOption('shared');await mode.selectOption('per_sim');assert.equal(await one.locator('input').inputValue(),'https://fixture.invalid/sim1');
 const articles=page.locator('.e5-sms-message');assert.equal(await articles.count(),2);
 await articles.nth(1).getByRole('button',{name:'回复'}).click();assert.equal(await page.locator('#e5-sms-card').inputValue(),'1');
 await page.locator('#e5-sms-number').fill('10010');await page.locator('#e5-sms-text').fill('fixture');
 await page.getByRole('button',{name:'发送',exact:true}).click();
 await page.waitForFunction(()=>document.body.textContent.includes('fixture send error'));
 // Screenshots use only mocked texts. No Save/Apply or forwarding test is invoked.
 await page.screenshot({path:path.join(output,'luci-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(output,'luci-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);console.log('Live LuCI loads updated dual-SIM SMS page');await page.unrouteAll({behavior:"wait"});await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
