(()=>{'use strict';
 const root=document.getElementById('monitor365');if(!root)return;
 const api=root.dataset.api,select=document.getElementById('mon-node'),wrap=document.getElementById('mon-nodes'),message=document.getElementById('mon-message');
 let days=1,data=[],busy=false,requestId=0,controller=null;
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const num=(x,d=1)=>x===null||x===undefined?'—':Number(x).toLocaleString('en-US',{maximumFractionDigits:d});
 const pct=x=>x==null?'—':num(x)+'%';
 const when=x=>x?new Date(x).toLocaleString():'No sample yet';
 const metric=(label,value,detail,percent)=>`<div class="mon-kpi"><span>${label}</span><strong class="mon-number">${value}</strong>${percent!=null?`<div class="mon-meter"><i style="width:${Math.max(0,Math.min(100,Number(percent)))}%"></i></div>`:''}<small>${detail}</small></div>`;
 function render(){
  const chosen=select.value,visible=data.filter(n=>chosen==='all'||String(n.id)===chosen);
  wrap.innerHTML=visible.length?visible.map(n=>{
   const m=n.current||{},p=n.peaks,c=n.capacity;
   return `<article class="mon-node mon-glass ${n.fresh?'':'mon-stale'}" data-node="${n.id}">
    <header class="mon-node-head"><div><h2>${esc(n.name)}</h2><p>${n.local?'Primary server':'Remote node'} · Last response ${esc(when(n.checked_at))}</p></div><span class="mon-tag ${n.fresh?'':'bad'}">${n.fresh?(m.vpn_active===false?'VPN stopped':'Telemetry live'):'Unknown / stale'}</span></header>
    ${n.alerts.map(a=>`<p class="mon-alert">${esc(a)}</p>`).join('')}
    <div class="mon-kpis">
    ${metric('CPU · total',pct(m.cpu),`Busiest core ${pct(m.core)} · peak ${pct(p.core)} at ${esc(when(n.peak_times.core))}`,m.cpu)}
    ${metric('Memory',pct(m.ram),`Peak ${pct(p.ram)} · ${m.memory_total?num(m.memory_total/1024**3)+' GiB installed':'Unknown'}`,m.ram)}
    ${metric('Traffic · receive / send',`${num(m.rx)} / ${num(m.tx)}`,`Mbps · peaks ${num(p.rx)} / ${num(p.tx)} · ${esc(m.interface||'unknown interface')}`,null)}
    ${metric('Connected devices',num(m.connections,0),`Peak ${num(p.connections,0)} · ${num(n.pool_free,0)} address slots free`,m.pool&&m.connections!=null?m.connections/m.pool*100:null)}
    </div>
    <div class="mon-details"><span>Disk ${pct(m.disk)}</span><span>CPU steal ${pct(m.steal)}</span><span>Observed telemetry availability ${pct(n.availability)}</span><span>${num(n.samples,0)} samples in range</span></div>
    <div class="mon-charts"><div class="mon-chart"><h3>Resource peaks (%)</h3><canvas data-chart="resources" aria-label="CPU and memory history"></canvas><small>Purple: busiest CPU core · Teal: RAM · gaps: unknown</small></div><div class="mon-chart"><h3>Traffic (Mbps)</h3><canvas data-chart="network" aria-label="Receive and send traffic history"></canvas><small>Blue: received · Orange: sent · measured host interface</small></div><div class="mon-chart"><h3>Connected devices</h3><canvas data-chart="connections" aria-label="Connected device history"></canvas><small>Devices, not registered accounts · hover or touch for the sample time</small></div></div>
    <section class="mon-capacity"><h3><i class="fa-solid fa-gauge-high" aria-hidden="true"></i> Capacity guidance · last 48 hours</h3><div class="mon-cap-grid"><div><span>Configured address pool</span><strong>${num(m.pool??n.last_known?.pool,0)}</strong></div><div><span>Observed with headroom</span><strong>${num(c.observed_with_headroom,0)}</strong></div><div><span>Estimated concurrent devices · ${esc(c.confidence)}</span><strong>${num(c.estimated_connections,0)}</strong></div></div><p>${esc(c.reason)}</p></section>
    <details class="mon-capacity"><summary>VPN performance checks · read only</summary>${n.performance.map(p=>`<p>${esc(p)}</p>`).join('')}</details>
    ${root.dataset.owner==='1'?`<form class="mon-settings" data-id="${n.id}"><label>Provider port limit (Mbps)<input name="link_mbps" type="number" min="1" max="1000000" step="any" value="${n.link_mbps??''}" placeholder="Unknown"></label><button type="submit"><i class="fa-solid fa-check" aria-hidden="true"></i> Save limit</button><small>Use the VPS plan limit; leaving blank means unknown. Does not change network settings.</small></form>`:''}
   </article>`;
  }).join(''):'<div class="mon-empty mon-glass">No accessible nodes or samples yet.</div>';
  drawAll();
 }
 function draw(canvas,rows,keys,percent){
  const ctx=canvas.getContext('2d'),w=Math.max(200,canvas.clientWidth),h=180,dpr=Math.min(window.devicePixelRatio||1,2),light=document.body.classList.contains('light');
  canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const ink=light?'#596b87':'#b0bdd6',grid=light?'#24334e16':'#eef3ff16',left=37,right=w-8,top=12,bottom=150;
  const values=rows.flatMap(r=>keys.map(([k])=>r[k])).filter(v=>v!=null&&Number.isFinite(Number(v))),max=percent?100:Math.max(1,...values)*1.1;
  ctx.font='10px sans-serif';ctx.textAlign='right';
  for(let i=0;i<=4;i++){const y=bottom-(bottom-top)*i/4;ctx.strokeStyle=grid;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillStyle=ink;ctx.fillText(num(max*i/4,max>10?0:1),left-5,y+3);}
  const stamps=rows.map(r=>Date.parse(r.at)),start=stamps[0]||Date.now(),end=stamps.at(-1)||start+1,range=Math.max(1,end-start);
  for(const [key,color]of keys){ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2;let open=false,previous=null;
   rows.forEach((r,i)=>{const value=r[key];if(value==null){open=false;previous=null;return;}const x=left+(right-left)*(stamps[i]-start)/range,y=bottom-(bottom-top)*Number(value)/max;
    if(open&&stamps[i]-previous<=(days===1?15*60*1000:2*3600*1000))ctx.lineTo(x,y);else ctx.moveTo(x,y);open=true;previous=stamps[i];});ctx.stroke();}
  ctx.fillStyle=ink;ctx.textAlign='left';ctx.fillText(rows.length?new Date(start).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'Waiting for samples',left,173);ctx.textAlign='right';ctx.fillText(rows.length?new Date(end).toLocaleString([],{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'',right,173);
  canvas.onpointermove=e=>{if(!rows.length)return;const box=canvas.getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(e.clientX-box.left-left)/(right-left))),target=start+ratio*range;let index=0;for(let i=1;i<stamps.length;i++)if(Math.abs(stamps[i]-target)<Math.abs(stamps[index]-target))index=i;const r=rows[index];canvas.title=when(r.at)+' · '+keys.map(([k])=>k+': '+num(r[k])).join(' · ');};
 }
 function drawAll(){wrap.querySelectorAll('[data-node]').forEach(article=>{const n=data.find(x=>String(x.id)===article.dataset.node);if(!n)return;article.querySelectorAll('canvas').forEach(c=>{const type=c.dataset.chart;draw(c,n.history,type==='resources'?[['core','#a28bed'],['ram','#42b6ac']]:type==='network'?[['rx','#6098ef'],['tx','#e8a165']]:[['connections','#6098ef']],type==='resources');});});}
 async function load(force=false){
  if(document.hidden&&!force)return;if(busy){if(!force)return;controller?.abort();}
  const id=++requestId;busy=true;controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);
  try{const r=await fetch(api+'?days='+days,{signal:controller.signal,cache:'no-store'});if(!r.ok)throw Error('Unable to load telemetry ('+r.status+')');const body=await r.json();if(id!==requestId)return;data=body.nodes;
   const old=select.value;select.innerHTML='<option value="all">All nodes</option>'+data.map(n=>`<option value="${n.id}">${esc(n.name)}</option>`).join('');select.value=[...select.options].some(o=>o.value===old)?old:'all';render();
   document.getElementById('mon-live-text').textContent='Updated '+new Date().toLocaleTimeString();message.textContent='Automatic collection: every 30 seconds. First CPU/network rates appear after the next sample. History times use your browser timezone.';
  }catch(e){if(id===requestId)message.textContent=e.name==='AbortError'?'Telemetry request timed out; retrying.':e.message;}finally{clearTimeout(timer);if(id===requestId)busy=false;}
 }
 select.addEventListener('change',render);document.getElementById('mon-refresh').addEventListener('click',()=>load(true));
 root.querySelectorAll('[data-days]').forEach(b=>b.addEventListener('click',()=>{days=Number(b.dataset.days);root.querySelectorAll('[data-days]').forEach(x=>x.classList.toggle('selected',x===b));load(true);}));
 wrap.addEventListener('submit',async e=>{const form=e.target.closest('.mon-settings');if(!form)return;e.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const body=new FormData(form);body.set('node_id',form.dataset.id);body.set('csrf',root.dataset.csrf);const r=await fetch(api+'/settings',{method:'POST',body});if(!r.ok)throw Error('Save failed; check the value and refresh your login.');message.textContent='Provider limit saved.';await load(true);}catch(err){message.textContent=err.message;}finally{button.disabled=false;}});
 let scheduled;new ResizeObserver(()=>{cancelAnimationFrame(scheduled);scheduled=requestAnimationFrame(drawAll);}).observe(wrap);
 new MutationObserver(drawAll).observe(document.body,{attributes:true,attributeFilter:['class']});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});setInterval(load,30000);load();
})();
