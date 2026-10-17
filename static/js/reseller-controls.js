(()=>{
 'use strict';
 const money=n=>new Intl.NumberFormat(document.documentElement.lang==='en'?'en-US':'fa-IR').format(n)+(document.documentElement.lang==='en'?" Toman":' تومان');
 document.querySelectorAll('[data-reseller-pricing]').forEach(form=>{
  const rates=JSON.parse(form.dataset.resellerPricing);
  const update=()=>{
   const planSelect=form.querySelector('select[name=plan_id]');
   const selected=planSelect?.selectedOptions[0]||form.querySelector('[name=plan_id]:checked');
   const custom=selected?.value==='custom';
   form.querySelector('.reseller-custom-fields').hidden=!custom;
   form.querySelectorAll('.reseller-custom-fields input').forEach(input=>input.disabled=!custom);
   const value=name=>Number(form.elements[name].value);
   const price=custom?rates.base+rates.per_day*value('days')+rates.per_gb*value('quota')+rates.per_device*(value('devices')-1):Number(selected?.dataset.price);
   const valid=Number.isSafeInteger(price)&&price>0&&price<=1000000000;
   form.querySelector('[data-reseller-total]').textContent=valid?money(price):(document.documentElement.lang==='en'?"No valid rate for this combination":'این ترکیب تعرفهٔ معتبر ندارد');
   form.querySelector('button[type=submit]').disabled=!valid||(!form.querySelector('[name=action]')&&!form.elements.node_id?.value);
  };
  form.addEventListener('input',update);form.addEventListener('change',update);update();
 });
 const create=document.querySelector('[data-reseller-create]');
 const password=create?.querySelector('[data-password-input]');
 create?.querySelector('[data-generate-password]').addEventListener('click',()=>{
  const alphabet='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#_-';
  const chars=[];while(chars.length<24){const byte=crypto.getRandomValues(new Uint8Array(1))[0];if(byte<256-256%alphabet.length)chars.push(alphabet[byte%alphabet.length]);}
  password.value=chars.join('');password.type='text';
  const toggle=create.querySelector('[data-reseller-password-toggle]');toggle.setAttribute('aria-pressed','true');toggle.setAttribute('aria-label',document.documentElement.lang==='en'?'Hide password':'پنهان کردن رمز');
 });
 create?.querySelector('[data-reseller-password-toggle]').addEventListener('click',event=>{const visible=password.type==='password';password.type=visible?'text':'password';event.currentTarget.setAttribute('aria-pressed',String(visible));event.currentTarget.setAttribute('aria-label',visible?'Hide password':'Show password');});
 const key='beeny-reseller-draft:'+location.pathname;
 let draft=null;
 try{const saved=sessionStorage.getItem(key);sessionStorage.removeItem(key);if(saved){const data=JSON.parse(saved);if(Date.now()-data.time<300000)draft=data;}}catch(_){}
 create?.addEventListener('submit',()=>{try{sessionStorage.setItem(key,JSON.stringify({reference:create.elements.reference.value,password:password.value,time:Date.now()}));}catch(_){/* The manager can enter the chosen password into the share box. */}});
 async function copy(text){
  if(navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(text);return true;}catch(_){}}
  const input=document.createElement('textarea');input.value=text;input.style.cssText='position:fixed;opacity:0;left:-9999px';document.body.append(input);input.select();const result=document.execCommand('copy');input.remove();return result;
 }
 document.querySelectorAll('[data-copy-text]').forEach(button=>button.addEventListener('click',async()=>{const label=button.textContent;button.textContent=await copy(button.dataset.copyText)?(document.documentElement.lang==='en'?"Copied \u2713":'کپی شد ✓'):(document.documentElement.lang==='en'?"Clipboard access denied":'کپی مجاز نیست');setTimeout(()=>button.textContent=label,2500);}));
 document.querySelectorAll('[data-account-share]').forEach(card=>{
  const input=card.querySelector('[data-share-password]'),preview=card.querySelector('[data-share-preview]'),status=card.querySelector('[data-share-status]');
  if(draft?.reference===card.dataset.shareReference){input.value=draft.password;card.querySelector('.reseller-share').open=true;card.querySelector('.reseller-row-detail').open=true;}
  const message=()=>`سلام 👋\nحساب شما در بنی پنل آماده است.\n\nپنل شخصی: ${card.dataset.shareUrl}\nنام کاربری: ${card.dataset.shareUser}\nرمز ورود: ${input.value}\n\nبرای مشاهدهٔ حجم، اعتبار و دانلود کانفیگ وارد لینک بالا شوید.\nاین اطلاعات خصوصی است؛ فقط نزد خودتان نگه دارید.`;
  const update=()=>{preview.textContent=`پنل شخصی: ${card.dataset.shareUrl}\nنام کاربری: ${card.dataset.shareUser}\nرمز ورود: ${input.value?'••••••••':'رمز تعیین‌شده را وارد کنید'}`;status.textContent='';};
  input.addEventListener('input',update);update();
  card.querySelector('[data-copy-account]').addEventListener('click',async()=>{if(!input.value){status.textContent=(document.documentElement.lang==='en'?"Enter the current password for the full message.":'برای متن کامل، رمز فعلی را وارد کنید.');input.focus();return;}status.textContent=await copy(message())?(document.documentElement.lang==='en'?"Full account message copied \u2713":'متن کامل حساب کپی شد ✓'):(document.documentElement.lang==='en'?"Browser denied clipboard access.":'مرورگر اجازهٔ کپی نداد.');});
 });
 draft=null;
})();
