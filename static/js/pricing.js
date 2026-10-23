/* Customer views are replaced without replacing the dock; initialize each DOM root once. */
(()=>{'use strict';const roots=new WeakSet();function mount(){const view=document.querySelector('.workspace,.customer-shell');if(view){if(roots.has(view))return;roots.add(view);}else if(document.querySelector('.account-dock'))return;
(() => {
 document.querySelectorAll('[data-pricing]').forEach(box=>{
  const admin=box.hasAttribute('data-pricing-admin'),form=box.closest('form');
  const initial=admin?null:JSON.parse(box.querySelector('.pricing-policy').textContent);
  function calculate(){
   const policy=admin?Object.fromEntries(['base','per_gb','per_day','per_device'].map(k=>[k,Number(box.querySelector(`[name=pricing_${k}]`).value)])):initial;
   const get=n=>Number(box.querySelector(`[name=custom_${n}]`).value),days=get('days'),quota=get('quota'),devices=get('devices');
   const total=policy.base+quota*policy.per_gb+days*policy.per_day+(devices-1)*policy.per_device;
   const valid=[days,quota,devices,total].every(Number.isSafeInteger)&&days>=1&&days<=3650&&quota>=1&&quota<=1000000&&devices>=1&&devices<=100&&total>=1&&total<=1000000000;
   const text=valid?new Intl.NumberFormat(admin||document.documentElement.lang==='en'?'en-GB':'fa-IR').format(total)+(admin?' Toman':(document.documentElement.lang==='en'?" Toman":' تومان')):(admin?'Choose valid values and pricing rates':(document.documentElement.lang==='en'?"This combination or price is invalid":'مقادیر یا قیمت این ترکیب معتبر نیست'));
   box.querySelector('.quote-total').textContent=text;
   if(!admin){const radio=box.querySelector('[name=plan_id]');radio.dataset.price=valid?String(total):'0';if(radio.checked)document.getElementById('pay-price').textContent=text;box.classList.toggle('custom-active',radio.checked);box.querySelectorAll('[name^=custom_]').forEach(input=>input.disabled=!radio.checked)}
  }
  box.addEventListener('input',calculate);form.querySelectorAll('[name=plan_id]').forEach(e=>e.addEventListener('change',calculate));calculate();
 });
})();

}mount();document.addEventListener('customer:content-ready',mount);})();
