'use strict';
'require baseclass';
'require rpc';
'require mu300.common as M';

var get = rpc.declare({object:'mu300dash',method:'sim_radio_get',nobatch:true,expect:{'':{}}});
var set = rpc.declare({object:'mu300dash',method:'sim_radio_set',params:['slot','enabled','confirm'],nobatch:true,expect:{'':{}}});
var status = rpc.declare({object:'mu300dash',method:'sim_radio_status',params:['id'],nobatch:true,expect:{'':{}}});
var errors={
    'modem_busy':'另一项模组操作正在执行',
    'Radio setting saved; target SIM is not ready':'设置已保存，目标 SIM 尚未就绪',
    'Radio setting saved; modem command failed:':'设置已保存，但基带执行失败：',
    'Radio setting saved; RF readback not confirmed':'设置已保存，但未能确认射频状态',
    'Radio setting saved; RF enable failed':'设置已保存，但射频开启失败',
    'Radio setting saved; RF disable failed':'设置已保存，但射频关闭失败',
    'Invalid saved SIM radio policy':'已保存的 SIM 射频设置无效'
};
function errorMessage(error) {
    var text=error.message||String(error);
    Object.keys(errors).forEach(function(key){text=text.replace(key,errors[key]);});
    return M.translate(text);
}

function attach(root) {
    var disposed=false, pending=false, timer, flags=null;
    root.innerHTML='<h3></h3><p class="mud-note"></p><div data-radios></div><p role="status" aria-live="polite"></p>';
    root.querySelector('h3').textContent=M.translate('SIM 射频');
    root.querySelector('.mud-note').textContent=M.translate('分别控制每张卡的射频并记住设置。关闭后该卡无法通话、收发短信或上网；不会自动切换到另一张卡。');
    var buttons=[], result=root.querySelector('[role=status]'), rows=root.querySelector('[data-radios]');
    rows.style.cssText='display:grid;gap:12px;margin:16px 0';
    [0,1].forEach(function(slot) {
        var row=document.createElement('div'), label=document.createElement('span'), b=document.createElement('button');
        row.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:16px';
        label.textContent='SIM '+(slot+1); b.type='button'; b.className='mud-btn'; b.setAttribute('role','switch'); b.setAttribute('aria-label','SIM '+(slot+1)+' '+M.translate('射频'));
        row.append(label,b); rows.append(row); buttons.push(b);
        b.onclick=function() {
            if(pending||!flags)return;
            var enabled=!flags[slot]; pending=true; paint();
            M.confirmBox('SIM '+(slot+1)+' · '+M.translate(enabled?'开启射频':'关闭射频'), M.translate('设置会在重启后保留。关闭当前上网卡会中断蜂窝网络。')).then(function(yes) {
                if(disposed)return;
                if(!yes){pending=false;paint();return;}
                result.textContent=M.translate('正在应用射频设置…');
                return set(String(slot),enabled,true).then(function(job) {
                    if(!job||!job.ok)throw new Error(job&&job.error||'提交失败');
                    var deadline=Date.now()+210000;
                    function watch() {
                        if(disposed)return;
                        if(Date.now()>deadline){finish(new Error(M.translate('应用超时，请刷新确认模组状态')));return;}
                        status(job.id).then(function(r) {
                            if(disposed)return;
                            if(r&&r.ok&&r.state==='done')finish();
                            else if(!r||!['queued','running'].includes(r.state))finish(new Error(r&&r.error||'无法读取执行结果'));
                            else timer=setTimeout(watch,1000);
                        }).catch(function(){if(!disposed)timer=setTimeout(watch,1000);});
                    }
                    watch();
                });
            }).catch(finish);
        };
    });
    function paint() {
        buttons.forEach(function(b,i){ b.disabled=pending||!flags;
            b.textContent=flags?M.translate(flags[i]?'已开启':'已关闭'):'--';
            b.setAttribute('aria-checked',String(!!(flags&&flags[i])));
            b.classList.toggle('on',!!(flags&&flags[i])); });
    }
    function refresh() {
        if(disposed||pending||document.hidden)return Promise.resolve();
        return get().then(function(r){if(disposed||pending)return;flags=r&&r.ok&&Array.isArray(r.enabled)?r.enabled:null;paint();}).catch(function(){if(!disposed){flags=null;paint();}});
    }
    function finish(error) {
        if(disposed)return;
        pending=false;clearTimeout(timer);
        result.textContent=error?errorMessage(error):M.translate('射频设置已应用并保存');
        result.style.color=error?'var(--danger,#dc3545)':'';
        refresh();
    }
    paint();refresh();
    return {refresh:refresh,dispose:function(){disposed=true;clearTimeout(timer);}};
}
return baseclass.extend({attach:attach});
