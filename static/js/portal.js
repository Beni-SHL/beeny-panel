(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fa = new Intl.NumberFormat('fa-IR', {maximumFractionDigits: 3});
  const theme = document.getElementById('portal-theme');
  theme.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {localStorage.setItem('beeny-customer-theme', next);} catch (_) {}
    theme.setAttribute('aria-pressed', next === 'dark');
  });
  theme.setAttribute('aria-pressed', document.documentElement.dataset.theme === 'dark');
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
    svg.replaceChildren();
    const max = Math.max(...rows.map(r => r[1]), .01);
    const top = 15, bottom = 197, left = 46, width = 655, step = width / rows.length;
    for (let i=0; i<=4; i++) {
      const y = bottom - (bottom-top)*i/4;
      add('line', {x1:left, y1:y, x2:left+width, y2:y, class:'chart-grid'});
      add('text', {x:left-9, y:y+4, 'text-anchor':'end'}, fa.format(max*i/4));
    }
    const points=[];
    rows.forEach(([day,gb], i) => {
      const height=(bottom-top)*gb/max, x=left+step*i+step/2;
      const label = `${day} · ${fa.format(gb)} گیگابایت`;
      const bar=add('rect', {x:x-step*.24, y:bottom-height, width:step*.48, height:Math.max(height, 1), class:'chart-bar', tabindex:0, role:'img', 'aria-label':label, style:`animation-delay:${i*.012}s`});
      const title=document.createElementNS(ns,'title'); title.textContent=label; bar.appendChild(title);
      const show=()=>{tooltip.hidden=false;tooltip.textContent=label;};
      bar.addEventListener('mouseenter',show);bar.addEventListener('focus',show);
      bar.addEventListener('mouseleave',()=>tooltip.hidden=true);bar.addEventListener('blur',()=>tooltip.hidden=true);
      if (i % Math.max(1,Math.ceil(rows.length/7)) === 0 || i===rows.length-1) add('text',{x,y:221,'text-anchor':'middle'}, new Date(day+'T12:00:00Z').toLocaleDateString('fa-IR',{month:'short',day:'numeric',timeZone:'UTC'}));
      points.push([x,bottom-height]);
    });
    add('polyline',{points:points.map(p=>p.join(',')).join(' '), class:'trend',fill:'none','pointer-events':'none'});
    document.getElementById('range-total').textContent=fa.format(rows.reduce((sum,r)=>sum+r[1],0));
    svg.setAttribute('aria-label',`مصرف ${range} روز گذشته؛ ${fa.format(rows.reduce((sum,r)=>sum+r[1],0))} گیگابایت`);
  }
  document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('active',b===button));draw(Number(button.dataset.range));
  })); draw(30);
  if (!reduced) document.querySelectorAll('[data-counter]').forEach(el=>{
    const value=Number(el.dataset.counter);const start=performance.now();
    function tick(now){const progress=Math.min(1,(now-start)/900);el.textContent=fa.format(value*(1-Math.pow(1-progress,3)));if(progress<1) requestAnimationFrame(tick);}
    requestAnimationFrame(tick);
  });
  document.querySelectorAll('[name=plan_id]').forEach(el=>el.addEventListener('change',()=>{
    document.getElementById('pay-price').textContent=new Intl.NumberFormat('fa-IR').format(Number(el.dataset.price))+' تومان';
  }));
  const copy=document.getElementById('copy-card');
  copy.addEventListener('click',async()=>{
    try {await navigator.clipboard.writeText(copy.dataset.card);copy.textContent='کپی شد ✓';}
    catch(_){copy.textContent='شماره را انتخاب و کپی کنید';}
  });
  const file=document.getElementById('receipt-file');
  file.addEventListener('change',()=>{
    const chosen=file.files[0];if(!chosen)return;
    if(chosen.size>5*1024*1024){file.value='';document.getElementById('receipt-label').textContent='حجم تصویر باید کمتر از ۵ مگابایت باشد';return;}
    document.getElementById('receipt-label').textContent=chosen.name;
    const preview=document.getElementById('receipt-preview');const reader=new FileReader();
    reader.onload=()=>{preview.src=reader.result;preview.hidden=false;};reader.readAsDataURL(chosen);
  });
  document.getElementById('avatar-file').addEventListener('change',function(){if(this.files[0]&&this.files[0].size<=5*1024*1024)this.form.requestSubmit();});
  document.getElementById('renewal-form').addEventListener('submit',function(){const button=this.querySelector('[type=submit]');button.disabled=true;button.textContent='در حال ثبت درخواست…';});
})();
