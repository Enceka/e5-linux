// Exercise the shipped LuCI functions with mocked RPC; no device actions.
const fs = require('fs'), assert = require('assert');
const base = 'openwrt/luci-app-t551m/htdocs/luci-static/resources/';
const common = fs.readFileSync(base+'mu300/common.js','utf8');
const locks = fs.readFileSync(base+'view/mu300/locks.js','utf8');
const waiter = common.slice(common.indexOf('function waitLockJob('),common.indexOf('\nvar ',common.indexOf('function waitLockJob(')));
const busy = common.slice(common.indexOf('function busy('),common.indexOf('\n/*',common.indexOf('function busy(')));
new Function(common);new Function(locks);new Function(fs.readFileSync(base+'view/mu300/home.js','utf8'));
(async()=>{
    let slot='0', sent=[];
    const scoped=new Function('rpc','sessionStorage',common.slice(0,common.indexOf('var callUsbGet'))+';return {callStatus,callCells,callSignal,callAt,callLockGet,callLockFresh,callLockSet,callLockStatus,callTrafficGet,callTrafficSet};')(
        {declare:spec=>(...args)=>{sent.push({method:spec.method,args,params:spec.params,nobatch:spec.nobatch});return Promise.resolve({});}},
        {getItem:()=>slot});
    for (slot of ['0','1']) {
        await scoped.callStatus();await scoped.callCells();await scoped.callSignal();await scoped.callAt('AT+COPS?');
        await scoped.callLockGet();await scoped.callLockFresh(true);await scoped.callLockSet('lte','1,3');
        for(const kind of ['ims','volte','vonr'])await scoped.callLockSet(kind,'off');
        await scoped.callLockStatus('job');await scoped.callTrafficGet();await scoped.callTrafficSet('{}');
        for (const request of sent.splice(0)) {
            assert.equal(request.params.at(-1),'slot');assert.equal(request.args.at(-1),slot);
            assert.equal(request.args.length,request.params.length);
			if (['cells','signal','lock_get'].includes(request.method)) assert.strictEqual(request.nobatch,true,'Slow AT must not hold cached data in the same HTTP batch');
        }
    }
    console.log('PASS: dashboard, terminal, lock jobs and traffic RPC scope follows selected SIM');
    let queue = [{state:'running'},{state:'done',ok:1}], timers=new Map(), counter=0;
    const set=(fn,ms)=>{if(ms===240000){timers.set(++counter,fn);return counter;}queueMicrotask(fn);return ++counter;};
    const wait = new Function('callLockStatus','setTimeout','clearTimeout',waiter+';return waitLockJob;')(
        async()=>queue.shift(),set,id=>timers.delete(id));
    await wait({ok:1,id:'job'});
    queue=[{state:'error',error:'AT rejected'}];
    await assert.rejects(wait({ok:1,id:'job'}),/AT rejected/);
    await assert.rejects(wait({ok:0,error:'bad request'}),/bad request/);
    let removed=0;
    const clearBusy=new Function(busy+';return busy;')();
    clearBusy({classList:{contains:()=>false,remove:()=>{}},querySelectorAll:()=>[{remove:()=>removed++}]},false);
    assert.equal(removed,1,'paint() removed the busy class, but spinner still needs removal');
    let messages=[], cleared=0;
    const M={waitLockJob:async()=>{throw new Error('No AT response')},busy:()=>cleared++,translate:x=>x};
    const view=new Function('view','M',locks+';')({extend:x=>x},M);
    const instance={...view,Q:()=>null,note:(text,type)=>messages.push({text,type}),refresh:()=>{},_applying:true};
    await instance.readback({ok:1,id:'job'},{});
    assert.equal(cleared,1);assert.equal(instance._applying,false);
    assert(messages.some(m=>m.type==='error'&&m.text.includes('No AT response')));
    M.waitLockJob=async()=>({state:'done',ok:1});M.callLockGet=async()=>({ts:1,mode:{label:'4g'}});
    instance.paint=()=>{};instance.paintServing=()=>{};
    await instance.readback({ok:1,id:'job'},{});
    assert.equal(instance.lastLock.mode.label,'4g');assert.equal(messages.at(-1).type,'success');
    M.translate=x=>x;
    const nodes={'lock-nrline':{},'lock-lteline':{},'lock-nr':{children:[]},'lock-lte':{children:[]}};
    const bands={...view,Q:id=>nodes[id],lockCand:{nr:[78],lte:[]},lockSel:{nr:{78:true},lte:{}},
        chipRow:(box,rat,cand)=>{box.children=cand.map(b=>({getAttribute:()=>String(b)}));},
        lastLock:{caps:{nr:'1,3',lte:'1,3,8'},nr:{locked:'1,78'},lte:{locked:''}}};
    bands.paint();
    assert.deepEqual(bands.lockCand.nr,[1,3]);assert(!bands.lockSel.nr[78]);
    assert(nodes['lock-nrline'].textContent.includes('已锁'), 'Equal counts do not mean equal bands');
    bands.lastLock.caps.nr='';bands.paint();
    assert.deepEqual(bands.lockCand.nr,[]);assert.deepEqual(bands.lockSel.nr,{});
    assert.equal(nodes['lock-nr'].children.length,0);
    assert(nodes['lock-nrline'].textContent.includes('暂不可用'));
    const switches=['volte','vonr'].map(kind=>({
        dataset:{voice:kind},setAttribute(k,v){this[k]=v;}
    }));
    bands._root={querySelectorAll:selector=>switches.filter(b=>selector.includes('"'+b.dataset.voice+'"'))};
    for(const kind of ['volte','vonr'])nodes['lock-'+kind+'-state']={};
    bands.lastLock.volte={enabled:true,source:'modem'};
    bands.lastLock.vonr={enabled:null,source:'unknown'};
    bands.paint();
    assert(nodes['lock-volte-state'].textContent.includes('已开启'));
    assert.equal(switches.find(b=>b.dataset.voice==='volte')['aria-checked'],'true');
    assert.equal(switches.find(b=>b.dataset.voice==='volte').disabled,false);
    assert(switches.filter(b=>b.dataset.voice==='vonr').every(b=>b.disabled&&b['aria-checked']==='false'));
    console.log('PASS: single VoLTE/VoNR switches, unknown-state disable and separate SIM RPC');
    console.log('PASS: job success/error, clock-independent completion, spinner cleanup, failed and successful readback');
    console.log('PASS: dynamic candidates, stale selection cleanup, unavailable capabilities and set comparison');
    // Hold the neighboring-cell RPC while live serving data arrives. Each
    // section paints immediately; repeated ticks cannot queue duplicate work.
    let replyCells, replySignal, cellCalls=0, signalCalls=0, serving=[], neighbors=[], states={};
    M.callCells=()=>{cellCalls++;return new Promise(r=>replyCells=r)};
    M.callSignal=()=>{signalCalls++;return new Promise(r=>replySignal=r)};
    const progressive={...view,loading:(key,pending,error)=>states[key]={pending,error},
        paintServing:c=>serving.push(c),paintNeighbors(){neighbors.push(this.neighborCell)}};
    const meta=progressive.loadServingMeta(), live=progressive.loadServing();
    assert.strictEqual(progressive.loadServingMeta(),meta);
    assert.strictEqual(progressive.loadServing(),live);
    assert.equal(cellCalls,1);assert.equal(signalCalls,1);
    replySignal({ts:10,lte:{band:8},sig:{rsrp:-93}});await live;
    assert.equal(serving.at(-1).lte.band,8);assert.equal(neighbors.length,0);
    replyCells({cell:{ts:9,partial:1,neigh_pending:1,operator:{name:'test'}}});await meta;
    assert.equal(serving.at(-1).operator.name,'test');assert.equal(states.neigh.pending,true);
    const ready={ts:10,partial:1,neigh_pending:0,neigh:[{pci:22}]};
    M.callCells=async()=>({cell:ready});await progressive.loadServingMeta();
    assert.strictEqual(neighbors.at(-1),ready,'Neighbors show before identity completes');
    assert.equal(states.neigh.pending,false);
    M.callCells=async()=>({cell:{...ready,neigh:null,neigh_pending:1}});await progressive.loadServingMeta();
    assert.strictEqual(progressive.neighborCell,ready,'Refreshing must retain the previous table');
    M.callCells=async()=>{throw new Error('offline')};await progressive.loadServingMeta();
    assert.equal(states.neigh.pending,false);assert.equal(states.neigh.error,'offline');
    assert.strictEqual(progressive.neighborCell,ready);
    M.callCells=()=>new Promise(r=>replyCells=r);
    const late=progressive.loadServingMeta();progressive._disposed=true;
    replyCells({cell:{neigh:[]}});await late;
    assert.strictEqual(progressive.neighborCell,ready,'Late replies cannot paint an unloaded view');
	progressive.lastSignal={partial:1,reg:{stat:1},lte:null,nr:null,sig:{rsrp:-90}};
	progressive.servingMeta={lte:{band:8},nr:null,sig:{rsrp:-93},sig_src:'lte'};
	progressive.mergeServing();
	assert.equal(serving.at(-1).lte.band,8,'A core-only snapshot must not erase loaded engineering data');
    console.log('PASS: independent serving/neighbor rendering, partial refresh, errors, deduplication and unload');
})().catch(e=>{console.error(e);process.exitCode=1});
