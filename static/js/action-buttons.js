/* Native adaptation of the supplied Prime/Download button states. No simulated progress. */
(()=>{'use strict';if(window.BeenyActionButton)return;
 const timers=new WeakMap(),fa=()=>document.documentElement.lang==='fa';
 const paths={save:'M5 3h12l4 4v14H3V3h2Zm2 0v6h10V3M7 21v-8h10v8',renew:'M3 10a9 9 0 0 1 16-5l2 3M21 3v5h-5M21 14a9 9 0 0 1-16 5l-2-3M3 21v-5h5',download:'M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5',publish:'M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6',check:'m5 12 4 4L19 6',error:'m6 6 12 12M6 18 18 6',loading:'M21 12a9 9 0 1 1-9-9'};
 function icon(kind){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.8');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[kind]||paths.save);svg.append(p);return svg;}
 function prepare(button,kind){if(!button||button.dataset.actionReady&&button.querySelector('.button-state'))return;button.dataset.actionReady='1';button.classList.add('beeny-action-button');
  const label=document.createElement('span');label.className='button-idle';while(button.firstChild)label.append(button.firstChild);
  if(!label.querySelector('svg,i'))label.prepend(icon(kind));const out=document.createElement('span');out.className='button-state';out.setAttribute('aria-live','polite');button.append(label,out);button.dataset.actionState='idle';}
 function set(button,state,progress){if(!button)return;prepare(button,'save');clearTimeout(timers.get(button));button.dataset.actionState=state;button.setAttribute('aria-busy',String(state==='loading'));
  const out=button.querySelector('.button-state');if(!out)return;out.replaceChildren();if(state==='idle')return;
  out.append(icon(state==='success'?'check':state==='error'?'error':'loading'));
  const label=document.createElement('span');label.textContent=state==='loading'?(Number.isFinite(progress)?progress+'%':fa()?'در حال انجام…':'Processing…'):state==='success'?(fa()?'انجام شد':'Done'):(fa()?'ناموفق':'Failed');out.append(label);
  button.style.setProperty('--action-progress',Number.isFinite(progress)?progress+'%':'0%');
  if(state==='success'||state==='error')timers.set(button,setTimeout(()=>set(button,'idle'),2500));}
 window.BeenyActionButton={set,prepare};
 function init(){document.querySelectorAll('button[type=submit],button:not([type])[form],a[href*="/download"],.portal-renew-cta').forEach(b=>{
  if(b.closest('.language-picker,.top-actions,.shell-controls')||b.matches('.logout-button,.shell-logout'))return;
  const text=b.textContent,kind=b.matches('a[href*="/download"]')?'download':/publish|انتشار/i.test(text)?'publish':/renew|تمدید/.test(text)||b.matches('.portal-renew-cta')?'renew':'save';prepare(b,kind);
 });}
 init();document.addEventListener('admin:content-ready',init);
 // Wallet payment uses server validation and its existing atomic ledger operation.
 document.addEventListener('submit',async event=>{const b=event.submitter;if(!b?.matches('[data-renew-wallet]'))return;event.preventDefault();const form=event.target;if(form.dataset.walletBusy)return;
  form.dataset.walletBusy='1';b.disabled=true;set(b,'loading');let out=form.querySelector('[data-wallet-result]');
  try{const source=new FormData(form),body=new FormData();for(const name of ['csrf','reference','plan_id','custom_days','custom_quota','custom_devices','coupon']){const value=source.get(name);if(value!==null)body.append(name,value);}const response=await fetch(b.formAction,{method:'POST',body,credentials:'same-origin',headers:{Accept:'application/json','X-Beeny-Wallet':'1'}});if(!/application\/json/.test(response.headers.get('Content-Type')||''))throw Error(fa()?'نشست را بررسی کنید و دوباره وارد شوید.':'Check your session and sign in again.');const d=await response.json();if(!response.ok||!d.success)throw Error(d.message||'Payment failed.');set(b,'success');out.textContent=d.message;
 const number=new Intl.NumberFormat(fa()?'fa-IR':'en-US',{maximumFractionDigits:2}),unit=fa()?'تومان':'Toman';
 document.querySelectorAll('[data-wallet-balance]').forEach(el=>el.textContent=number.format(d.wallet_balance)+' '+unit);
 document.querySelectorAll('[data-wallet-balance-number]').forEach(el=>el.textContent=number.format(d.wallet_balance));
 form.querySelector('[name=reference]').value=d.reference;
 const metrics=document.querySelectorAll('.metric-grid .metric'),a=d.account;
 const metric=(index,value,suffix)=>{const strong=metrics[index]?.querySelector(':scope>strong');if(!strong)return;strong.textContent=value;const small=document.createElement('small');small.textContent=suffix;strong.append(small);};
 metric(0,number.format(a.used),fa()?'گیگابایت':'GB');metric(1,a.remaining===null?'∞':number.format(a.remaining),fa()?'گیگابایت':'GB');metric(2,a.days_left===null?'∞':number.format(a.days_left),fa()?'روز':'Days');metric(3,number.format(d.current_devices),(fa()?'از ':'of ')+number.format(d.max_devices));
 const expiry=metrics[2]?.querySelector('.metric-foot');if(expiry)expiry.textContent=a.expiry_text;
 const foot=metrics[0]?.querySelector('.metric-foot');if(foot)foot.textContent=(fa()?'از ':'of ')+(a.quota?number.format(a.quota)+' GB':'∞');
 const progress=metrics[0]?.querySelector('.mini-progress i');if(progress)progress.style.setProperty('--progress',a.percent+'%');
 const remaining=a.quota?Math.max(0,100-a.percent):100;
 const ring=document.querySelector('.quota-glass .quota-consumed');if(ring)ring.style.strokeDasharray=(a.quota?a.percent*4.963716:0)+' 496.3716';
 const amount=document.querySelector('.quota-glass>div>strong');if(amount)amount.textContent=a.quota?Math.round(remaining)+'%':'∞';
 const wave=document.querySelector('.quota-glass .quota-wave')?.parentElement;if(wave)wave.setAttribute('transform','translate(0 '+(163-remaining*1.26)+')');
 const legend=document.querySelector('.balance-legend span b');if(legend)legend.textContent=a.remaining===null?'∞':number.format(a.remaining)+' GB';
 document.dispatchEvent(new CustomEvent('beeny:wallet-paid',{detail:{balance:d.wallet_balance}}));}
  catch(e){set(b,'error');out.textContent=e.message||'Payment failed. Check your wallet before retrying.';}
  finally{delete form.dataset.walletBusy;b.disabled=false;}
 });
 // Read real download bytes. Unknown length stays indeterminate; only completed responses succeed.
 document.addEventListener('click',async event=>{const b=event.target.closest?.('a[href*="/download"]');if(!b||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||b.target==='_blank')return;
  const url=new URL(b.href,location.href);if(url.origin!==location.origin)return;event.preventDefault();if(b.dataset.actionState==='loading')return;set(b,'loading');
  try{const response=await fetch(url,{credentials:'same-origin'});if(!response.ok||response.redirected&&new URL(response.url).pathname.endsWith('/login')||/text\/html/.test(response.headers.get('Content-Type')||''))throw Error('Download failed.');
   const total=Number(response.headers.get('Content-Length')),reader=response.body?.getReader();let blob;
   if(reader){const chunks=[];let bytes=0;for(;;){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;if(bytes>32*1024*1024){await reader.cancel();throw Error('Download exceeds the profile size limit.');}chunks.push(value);set(b,'loading',total>0?Math.min(99,Math.floor(bytes*100/total)):undefined);}blob=new Blob(chunks,{type:response.headers.get('Content-Type')||'application/octet-stream'});}else blob=await response.blob();
   let name=(response.headers.get('Content-Disposition')||'').match(/filename="?([^";]+)"?/i)?.[1]||'Beeny-profile.ovpn';name=name.replace(/[\\/\x00-\x1f]/g,'_').slice(0,150);
   const href=URL.createObjectURL(blob),a=document.createElement('a');a.href=href;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(href),60000);set(b,'success');
  }catch(e){set(b,'error');b.title=fa()?'دانلود ناموفق بود؛ دوباره تلاش کنید.':'Download failed; please retry.';}
 });
 // Normal renewal remains a native form submission; only show its pending state.
 document.addEventListener('submit',event=>{if(event.defaultPrevented)return;const b=event.submitter;if(b&&event.target.id==='renewal-form'&&!b.matches('[data-renew-wallet]'))set(b,'loading');});

 document.addEventListener('submit',event=>{queueMicrotask(()=>{if(event.defaultPrevented)return;const b=event.submitter;if(!b||b.closest('.language-picker,.shell-controls,.top-actions'))return;set(b,'loading');});});
 if(typeof MutationObserver!=='undefined'){
  const pending=new WeakSet();
  new MutationObserver(records=>{for(const record of records){const b=record.target;if(!b.matches?.('button')||b.closest('.language-picker,.shell-controls,.top-actions'))continue;
   if(b.disabled&&record.oldValue===null&&b.dataset.actionState!=='loading'){pending.add(b);set(b,'loading');}
   else if(!b.disabled&&pending.has(b)){pending.delete(b);if(b.dataset.actionState==='loading')set(b,'idle');}
  }}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['disabled'],attributeOldValue:true});
 }
 window.addEventListener?.('pageshow',event=>{if(event.persisted)document.querySelectorAll('[data-action-state="loading"]').forEach(b=>set(b,'idle'));});
})();
