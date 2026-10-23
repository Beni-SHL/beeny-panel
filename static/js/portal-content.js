/* Customer views are replaced without replacing the dock; initialize each DOM root once. */
(()=>{'use strict';const roots=new WeakSet();function mount(){const view=document.querySelector('.workspace,.customer-shell');if(view){if(roots.has(view))return;roots.add(view);}else if(document.querySelector('.account-dock'))return;
(()=>{'use strict';const root=document.documentElement,renew=document.getElementById('renew');function renewalTab(){if(!renew||!renew.isConnected)return;const show=location.hash==='#renew';renew.hidden=!show;document.querySelector('main')?.classList.toggle('renewal-tab-active',show);if(show)renew.scrollIntoView({block:'start'});}addEventListener('hashchange',renewalTab);renewalTab();
const observer='IntersectionObserver' in window?new IntersectionObserver(entries=>entries.forEach(entry=>entry.target.classList.toggle('in-view',entry.isIntersecting))):null;document.addEventListener('customer:before-navigate',()=>observer?.disconnect(),{once:true});document.querySelectorAll('.balance-card').forEach(box=>observer?observer.observe(box):box.classList.add('in-view'));
document.querySelectorAll('[data-dismiss-announcement]').forEach(form=>form.addEventListener('submit',async event=>{event.preventDefault();const row=form.closest('[data-announcement]'),button=form.querySelector('button');button.disabled=true;try{const response=await fetch(form.getAttribute('action')||location.href,{method:'POST',body:new FormData(form),credentials:'same-origin',headers:{Accept:'application/json'}});if(!response.ok||response.redirected)throw Error('Dismiss failed');row.remove();}catch(_){row.querySelector('.announcement-error').textContent=root.lang==='en'?'Could not dismiss. Please retry.':'ثبت نشد؛ دوباره تلاش کنید.';}finally{button.disabled=false;}}));
const tutorialDialog=document.getElementById('tutorial-dialog');
if(tutorialDialog&&typeof tutorialDialog.showModal==='function'){
 const player=tutorialDialog.querySelector('video'),title=tutorialDialog.querySelector('h2'),error=tutorialDialog.querySelector('.tutorial-video-error');let trigger=null;
 document.querySelectorAll('[data-tutorial-video]').forEach(link=>link.addEventListener('click',event=>{
  if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  event.preventDefault();trigger=link;error.hidden=true;title.textContent=link.dataset.tutorialTitle;
  player.pause();player.removeAttribute('src');player.removeAttribute('poster');
  if(link.dataset.tutorialPoster)player.poster=link.dataset.tutorialPoster;
  player.src=link.dataset.tutorialVideo;tutorialDialog.showModal();player.load();player.play()?.catch(()=>{});
 }));
 tutorialDialog.querySelector('[data-close-tutorial]').addEventListener('click',()=>tutorialDialog.close());
 tutorialDialog.addEventListener('click',event=>{if(event.target!==tutorialDialog)return;const box=tutorialDialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)tutorialDialog.close();});
 player.addEventListener('error',()=>{if(tutorialDialog.open&&player.hasAttribute('src'))error.hidden=false;});
 tutorialDialog.addEventListener('close',()=>{player.pause();player.removeAttribute('src');player.removeAttribute('poster');player.load();error.hidden=true;title.textContent='';trigger?.focus({preventScroll:true});trigger=null;});
}
})();

}mount();document.addEventListener('customer:content-ready',mount);})();
