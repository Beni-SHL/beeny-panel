/* Native adaptation of the supplied LiveNotificationFeed. Durable server data only. */
(()=>{'use strict';if(window.beenyNotificationFeed)return;window.beenyNotificationFeed=true;
 const CHECK='M5 12.5l4.2 4.2L19 7',BELL='M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 1.5h-15ZM10 20.5a2.2 2.2 0 0 0 4 0';
 function svg(path){const el=document.createElementNS('http://www.w3.org/2000/svg','svg');el.setAttribute('viewBox','0 0 24 24');el.setAttribute('aria-hidden','true');const p=document.createElementNS(el.namespaceURI,'path');p.setAttribute('d',path);el.append(p);return el;}
 function init(){document.querySelectorAll('[data-notifications]').forEach(center=>{
 if(center.dataset.notificationsBound)return;center.dataset.notificationsBound='1';
 const bell=center.querySelector('.notification-bell'),popup=center.querySelector('.notification-popover'),items=center.querySelector('.notification-items'),badge=center.querySelector('.notification-badge'),unread=center.querySelector('.notification-unread'),feedback=center.querySelector('.notification-feedback'),fa=()=>document.documentElement.lang==='fa';
 let upto=0,loading=false,mutating=false,first=true,seen=new Set();
 const close=()=>{popup.hidden=true;bell.setAttribute('aria-expanded','false');};
 const text=(tag,value,cls)=>{const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;return el;};
 async function refresh(){if(loading||mutating||!center.isConnected)return;loading=true;
 try{const response=await fetch(center.dataset.notifications,{headers:{Accept:'application/json'},cache:'no-store',credentials:'same-origin'});if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error();const data=await response.json();
 if(!Array.isArray(data.items))throw Error();upto=Number(data.latest_id)||0;
 const count=Number(data.unread)||0;badge.textContent=count>99?'99+':String(count);badge.hidden=!count;unread.textContent=badge.textContent;unread.hidden=!count;center.classList.toggle('has-unread',count>0);
 const keep=items.scrollTop,fragment=document.createDocumentFragment();
 if(!data.items.length){const empty=text('div','','notification-empty'),mark=text('span','','notification-empty-mark');mark.append(svg(CHECK));empty.append(mark,text('b',fa()?'همه‌چیز به‌روز است':'You’re all caught up'),text('p',fa()?'اعلان‌های جدید اینجا نمایش داده می‌شوند.':'New notifications will land here.'));fragment.append(empty);}
 data.items.forEach((row,index)=>{const article=text('article','','notification-card');article.setAttribute('role','listitem');article.dataset.notification=String(row.id);article.dataset.read=String(Boolean(row.read));
 if(!first&&!seen.has(row.id)){article.classList.add('notification-arriving');article.style.setProperty('--arrival-delay',Math.min(index,5)*60+'ms');}
 const tile=text('span','','notification-app-tile');tile.append(svg(row.read?CHECK:BELL));
 const content=text('div','','notification-card-content'),meta=text('div','','notification-meta'),stamp=text('time','');const date=new Date(row.created);if(!Number.isNaN(date.getTime())){stamp.dateTime=date.toISOString();stamp.textContent=date.toLocaleString(fa()?'fa-IR':'en-GB',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
 meta.append(text('span','Beeny'),text('span','·'),stamp);content.append(meta,text('b',row.title||'','notification-title'),text('p',row.body||'','notification-body'));const remove=text('button','','notification-delete');remove.type='button';remove.setAttribute('aria-label',fa()?'حذف اعلان':'Delete notification');remove.append(svg('m7 7 10 10M17 7 7 17'));remove.addEventListener('click',()=>acknowledge(String(row.id)+'/delete',remove));article.append(tile,content,remove);fragment.append(article);});
 items.replaceChildren(fragment);items.scrollTop=keep;seen=new Set(data.items.map(row=>row.id));first=false;feedback.textContent='';
 }catch(_){if(!popup.hidden)feedback.textContent=fa()?'دریافت اعلان‌ها ناموفق بود؛ دوباره باز کنید.':'Could not refresh. Reopen to retry.';}finally{loading=false;}}
 bell.addEventListener('click',()=>{popup.hidden=!popup.hidden;bell.setAttribute('aria-expanded',String(!popup.hidden));if(!popup.hidden)refresh();});
 center.querySelector('.notification-close').addEventListener('click',()=>{close();bell.focus();});
 document.addEventListener('click',event=>{if(!center.contains(event.target))close();});center.addEventListener('keydown',event=>{if(event.key==='Escape'){close();bell.focus();}});
 async function acknowledge(action,button){if(mutating||loading)return;mutating=true;const buttons=[...center.querySelectorAll('.notification-actions button,.notification-delete')];buttons.forEach(b=>b.disabled=true);window.BeenyActionButton?.set(button,'loading');feedback.textContent='';
 try{const response=await fetch(center.dataset.notifications+'/'+action,{method:'POST',credentials:'same-origin',body:new URLSearchParams({csrf:center.dataset.csrf,upto:String(upto)}),headers:{Accept:'application/json'}});if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error();const d=await response.json();if(d.success===false||d.ok===false)throw Error();window.BeenyActionButton?.set(button,'success');
 }catch(_){window.BeenyActionButton?.set(button,'error');feedback.textContent=fa()?'تغییر تأیید نشد؛ دوباره تلاش کنید.':'Change not confirmed. Please retry.';return;}finally{mutating=false;buttons.forEach(b=>b.disabled=false);}
 await refresh();}
 center.querySelector('.notification-read').addEventListener('click',event=>acknowledge('read',event.currentTarget));center.querySelector('.notification-clear').addEventListener('click',event=>acknowledge('clear',event.currentTarget));refresh();
 const timer=setInterval(()=>{if(!center.isConnected){clearInterval(timer);return;}if(!document.hidden)refresh();},60000);
 });}init();document.addEventListener('admin:content-ready',init);document.addEventListener('customer:content-ready',init);
})();
