(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fa = new Intl.NumberFormat(document.documentElement.lang==='en'?'en-US':'fa-IR', {maximumFractionDigits: 3});
  const theme = document.getElementById('portal-theme');
  theme.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {localStorage.setItem('beeny-customer-theme', next);} catch (_) {}
    theme.setAttribute('aria-pressed', next === 'dark');
  });
  theme.setAttribute('aria-pressed', document.documentElement.dataset.theme === 'dark');
  const paymentTotal=document.getElementById('pay-price');
  const transferAmount=document.querySelector('[data-transfer-amount]');
  if(paymentTotal&&transferAmount){
    const updateTransfer=()=>{transferAmount.textContent=paymentTotal.textContent;};
    updateTransfer();new MutationObserver(updateTransfer).observe(paymentTotal,{childList:true,characterData:true,subtree:true});
  }
  const values = JSON.parse(document.getElementById('daily-data').textContent);
  const svg = document.getElementById('daily-chart');
  const tooltip = document.getElementById('chart-tooltip');
  const ns = 'http://www.w3.org/2000/svg';
  function add(type, attributes, text) {
    const el = document.createElementNS(ns, type);
    Object.entries(attributes).forEach(([k,v]) => el.setAttribute(k, v));
    if (text !== undefined) el.textContent = text;
    svg.appendChild(el); return el;
  }
  function draw(range) {
    const rows = values.slice(-range);
    const empty=document.getElementById("chart-empty");if(empty)empty.hidden=rows.some(row=>row[1]>0);
    svg.replaceChildren();
    const max = Math.max(...rows.map(r => r[1]), .01);
    const unit=max<1?(document.documentElement.lang==='en'?"MB":'مگابایت'):(document.documentElement.lang==='en'?"GB":'گیگابایت'),factor=max<1?1024:1;
    const top = 15, bottom = 197, left = 46, width = 655, step = width / rows.length;
    for (let i=0; i<=4; i++) {
      const y = bottom - (bottom-top)*i/4;
      add('line', {x1:left, y1:y, x2:left+width, y2:y, class:'chart-grid'});
      add('text', {x:left-9, y:y+4, 'text-anchor':'end'}, fa.format(max*i/4*factor));
    }
    const points=[];
    rows.forEach(([day,gb], i) => {
      const height=(bottom-top)*gb/max, x=left+step*i+step/2;
      const label = `${new Date(day+'T12:00:00Z').toLocaleDateString(document.documentElement.lang==='en'?'en-US':'fa-IR',{year:'numeric',month:'long',day:'numeric',timeZone:'UTC'})} · ${fa.format(gb<1?gb*1024:gb)} ${gb<1?(document.documentElement.lang==='en'?"MB":'مگابایت'):(document.documentElement.lang==='en'?"GB":'گیگابایت')}`;
      const bar=add('g',{class:'chart-bar',tabindex:0,role:'button','aria-label':label,style:`animation-delay:${i*.012}s`});
      const visual=document.createElementNS(ns,'rect');Object.entries({x:x-step*.24,y:bottom-height,width:step*.48,height:Math.max(height,1),rx:4}).forEach(([k,v])=>visual.setAttribute(k,v));bar.appendChild(visual);
      const hit=document.createElementNS(ns,'rect');Object.entries({x:x-step*.48,y:top,width:step*.96,height:bottom-top,fill:'transparent','pointer-events':'all'}).forEach(([k,v])=>hit.setAttribute(k,v));bar.appendChild(hit);
      const title=document.createElementNS(ns,'title'); title.textContent=label; bar.appendChild(title);
      const show=()=>{tooltip.hidden=false;tooltip.textContent=label;};
      bar.addEventListener('click',()=>{svg.querySelectorAll('.selected').forEach(x=>x.classList.remove('selected'));bar.classList.add('selected');document.getElementById('chart-selection').textContent=label;});bar.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();bar.dispatchEvent(new Event('click'));}});bar.addEventListener('mouseenter',show);bar.addEventListener('focus',show);
      bar.addEventListener('mouseleave',()=>tooltip.hidden=true);bar.addEventListener('blur',()=>tooltip.hidden=true);
      if (i % Math.max(1,Math.ceil(rows.length/7)) === 0 || i===rows.length-1) add('text',{x,y:221,'text-anchor':'middle'}, new Date(day+'T12:00:00Z').toLocaleDateString(document.documentElement.lang==='en'?'en-US':'fa-IR',{month:'short',day:'numeric',timeZone:'UTC'}));
      points.push([x,bottom-height]);
    });
    add('polyline',{points:points.map(p=>p.join(',')).join(' '), class:'trend',fill:'none','pointer-events':'none'});
    const total=rows.reduce((sum,r)=>sum+r[1],0);document.getElementById('range-total').textContent=fa.format(total<1?total*1024:total);document.getElementById('range-unit').textContent=(total<1?(document.documentElement.lang==='en'?"MB":'مگابایت'):(document.documentElement.lang==='en'?"GB":'گیگابایت'))+(document.documentElement.lang==='en'?" in selected period":' در بازه انتخابی');svg.dataset.unit=unit;
    svg.setAttribute('aria-label',`مصرف ${range} روز گذشته؛ ${fa.format(rows.reduce((sum,r)=>sum+r[1],0))} گیگابایت`);
  }
  document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('active',b===button));draw(Number(button.dataset.range));
  })); draw(7);
  if (!reduced) document.querySelectorAll('[data-counter]').forEach(el=>{
    const value=Number(el.dataset.counter);const start=performance.now();
    function tick(now){const progress=Math.min(1,(now-start)/900);el.textContent=fa.format(value*(1-Math.pow(1-progress,3)));if(progress<1) requestAnimationFrame(tick);}
    requestAnimationFrame(tick);
  });
  document.querySelectorAll('[name=plan_id]').forEach(el=>el.addEventListener('change',()=>{
    document.getElementById('pay-price').textContent=new Intl.NumberFormat(document.documentElement.lang==='en'?'en-US':'fa-IR').format(Number(el.dataset.price))+(document.documentElement.lang==='en'?" Toman":' تومان');
  }));
  const copy=document.getElementById('copy-card');
  copy?.addEventListener('click',async()=>{
    try {await navigator.clipboard.writeText(copy.dataset.card);copy.textContent=(document.documentElement.lang==='en'?"Copied \u2713":'کپی شد ✓');}
    catch(_){copy.textContent=(document.documentElement.lang==='en'?"Select and copy the number":'شماره را انتخاب و کپی کنید');}
  });
  const file=document.getElementById('receipt-file');
  file.addEventListener('change',()=>{
    const chosen=file.files[0];if(!chosen)return;
    if(chosen.size>20*1024*1024){file.value='';document.getElementById('receipt-label').textContent=(document.documentElement.lang==='en'?"Image must be at most 20 MB":'حجم تصویر باید حداکثر ۲۰ مگابایت باشد');return;}
    document.getElementById('receipt-label').textContent=chosen.name;
    const preview=document.getElementById('receipt-preview');const reader=new FileReader();
    reader.onload=()=>{preview.src=reader.result;preview.hidden=false;};reader.readAsDataURL(chosen);
  });
  document.getElementById('avatar-file').addEventListener('change',function(){if(!this.files[0])return;if(this.files[0].size>20*1024*1024){this.value='';window.alert((document.documentElement.lang==='en'?"Profile photo must be at most 20 MB.":'حجم عکس پروفایل باید حداکثر ۲۰ مگابایت باشد.'));return;}this.form.requestSubmit();});
  document.getElementById('renewal-form').addEventListener('submit',function(event){const button=event.submitter||this.querySelector('[type=submit]');if(!button||button.matches('[data-renew-wallet]'))return;setTimeout(()=>{button.disabled=true;button.textContent=(document.documentElement.lang==='en'?"Submitting\u2026":'در حال ثبت درخواست…');},0);});
})();
