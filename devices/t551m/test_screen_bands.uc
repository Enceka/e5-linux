// Shared network contract; no modem access, configuration writes or reconnects.
'use strict';
let calls=[],selected='1',fail=false;
let state={mode:{label:'4g',gran:'1'},lte:{locked:'1,8'},nr:{locked:''},cells:[],endc:'1',auto_apply:1,
    caps:{lte:'1,3,5,8,34,39,40,41',nr:'1,5,8,28,41,78'}};
let ctx={run:()=>1,uci:()=>({get:(c,s,k)=>k=='control_slot'?selected:null}),
    sim_card:()=>0,sh_json:()=>null,at:()=>die('Screen bypassed shared AT owner'),
    ubus:(object,method,args)=>{
        push(calls,{object,method,args});
        if (method=='lock_get') return state;
        if (method=='sim_radio_get') return {ok:1,enabled:[true,true]};
        if (method=='cells') return {cell:{neigh:[{rat:'lte',arfcn:3740,pci:36}]}};
        return fail ? {ok:0,error:'Unsupported band requested'} : {ok:1,started:1,id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'};
    }};
let network=filter(loadfile(ARGV[0],{raw_mode:true})()(ctx),c=>c.id=='network')[0];
function check(v,why){if(!v)die(why);}
function item(id){return filter(network.items(),i=>i.id==id)[0];}
check(join(',',map(item('lte_bands').options,o=>o.value))==state.caps.lte,'LTE differs from web');
state.caps.nr='3,77,79';
check(join(',',map(item('nr_bands').options,o=>o.value))==state.caps.nr,'NR is not dynamic');
state.nr.locked='3,77,79,80';
check(length(item('nr_bands').value)==0,'All supported bands should show automatic, like web');
state.nr.locked='77,80';
check(join(',',item('nr_bands').value)=='77','Unsupported readback bits leaked into editable selection');
check(index(item('nr_bands').display_value.en,'n80')>=0,'Actual readback hidden from status summary');
state.nr.locked='';
check(item('nr_bands').none_label.en=='Auto','Automatic label differs from web');
check(item('net_mode').value=='4g' && item('net_mode').slot=='1','Wrong SIM scope');
check(item('nr_mode').value=='sa','Standalone 5G access setting lost');
check(length(filter(item('cell_lock').options,o=>o.value=='lte:3740,36'))==1,'Neighbors lost');
for(let pair in [['net_mode','sa'],['net_mode','5g4g'],['nr_mode','nsa'],['nr_bands',[77]],['lte_bands',[1,8]],['bands_default',null],['auto_apply',false],['cell_lock','lte:3740,36']]) {
    let r=network.set(pair[0],pair[1],'0');
    check(r.job && r.slot=='0','Async job or captured slot lost');
    let last=calls[length(calls)-1];
    check(last.object=='mu300dash'&&last.method=='lock_set'&&last.args.slot=='0','Not using common scoped mutation');
}
fail=true;check(network.set('nr_bands',[77],'1')=='Unsupported band requested','Backend failure hidden');
let count=length(calls);
check(type(network.set('lte_bands','1;reboot','1'))=='string'&&length(calls)==count,'Invalid input reached backend');
state={error:'AT unavailable',auto_apply:1};
check(item('lte_bands').type=='info'&&item('lte_bands').value==null,'Failed read reported unlocked');
print('PASS: shared per-SIM network modes, dynamic bands, neighbors, captured scope, asynchronous jobs and failures\n');
