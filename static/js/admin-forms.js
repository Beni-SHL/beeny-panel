/* Progressive form transport. Existing form-specific handlers keep precedence. */
(()=>{'use strict';
if(window.beenyAdminForms)return;window.beenyAdminForms=true;
const t=s=>window.adminT?.(s)||s;
function status(form,message,error=false){let out=form.querySelector('[data-admin-form-status]');if(!out){out=document.createElement('p');out.dataset.adminFormStatus='';out.setAttribute('role','status');out.setAttribute('aria-live','polite');form.append(out);}out.textContent=t(message);out.classList.toggle('form-error',error);return out;}
async function mount(doc,url){
 const incoming=doc.getElementById('admin-page'),current=document.getElementById('admin-page');
 if(!incoming||!current)throw Error('Your session may have expired. Refresh before retrying.');
 const scripts=[...incoming.querySelectorAll('script')];scripts.forEach(s=>s.remove());
 current.replaceChildren(...incoming.childNodes);current.dataset.adminMounted='1';document.title=doc.title;
 if(url.origin===location.origin&&url.href!==location.href)history.replaceState(null,'',url.href);
 for(const original of scripts){
  if(original.src){const src=new URL(original.src,location.href);if(src.origin!==location.origin)continue;const script=document.createElement('script');script.src=src.href;script.async=false;if(original.type)script.type=original.type;await new Promise((resolve,reject)=>{script.onload=resolve;script.onerror=()=>reject(Error('Saved, but page controls could not be loaded. Refresh this page.'));current.append(script);});}
  else if(original.type==='application/json'){current.append(original);}
  else if(original.textContent.trim()){const script=document.createElement('script');script.textContent="(()=>{\n"+original.textContent+"\n})();";current.append(script);}
 }
 document.dispatchEvent(new CustomEvent('admin:content-ready'));
}
window.beenyAdminNavigate=async target=>{const url=new URL(target,location.href);if(url.origin!==location.origin)throw Error('Unexpected redirect.');const response=await fetch(url,{credentials:'same-origin'});if(!response.ok)throw Error('Saved, but the updated page could not be loaded.');await mount(new DOMParser().parseFromString(await response.text(),'text/html'),url);};
document.addEventListener('click',async event=>{const link=event.target.closest('a[data-admin-navigate]');if(!link||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();if(link.dataset.busy)return;link.dataset.busy='1';link.setAttribute('aria-busy','true');try{await window.beenyAdminNavigate(link.href);}catch(error){const notice=document.createElement('p');notice.className='cc-feedback';notice.setAttribute('role','status');notice.textContent=t(error.message);document.getElementById('admin-page').prepend(notice);}finally{delete link.dataset.busy;link.removeAttribute('aria-busy');}});
document.addEventListener('submit',async event=>{
 const form=event.target;
 if(event.defaultPrevented||!(form instanceof HTMLFormElement)||(!form.closest('#admin-page')&&!form.matches('[data-admin-ajax]'))||form.hasAttribute('data-native-submit'))return;
 if(form.dataset.settingsAjax!==undefined||form.matches('[data-price-ajax]'))return;
 const url=new URL((form.getAttribute('action')||location.href),location.href);
 if(url.origin!==location.origin||(form.getAttribute('method')||'get').toLowerCase()!=='post')return;
 event.preventDefault();if(form.dataset.adminBusy)return;
 // FormData must be built before disabling controls; include the clicked action.
 const data=new FormData(form);if(event.submitter?.name)data.append(event.submitter.name,event.submitter.value);
 form.dataset.adminBusy='1';form.setAttribute('aria-busy','true');
 const buttons=[...form.querySelectorAll('button[type=submit],button:not([type]),input[type=submit]')];const states=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);status(form,'Saving…');
 try{
  const response=await fetch(url,{method:'POST',body:data,credentials:'same-origin',headers:{'X-Beeny-Form':'1','X-CSRF-Token':document.querySelector('meta[name=csrf-token]')?.content||''}});
  const finalURL=new URL(response.url||url.href);
  if(finalURL.origin!==location.origin)throw Error('Unexpected redirect. Refresh before retrying.');
  if(finalURL.pathname.endsWith('/login')){location.assign(finalURL.href);return;}
  const type=response.headers.get('Content-Type')||'';
  if(type.includes('application/json')){
   const result=await response.json();if(!response.ok||result.success===false||result.error)throw Error(result.message||result.error||'Save failed.');
   if(result.redirect){const next=new URL(result.redirect,location.href);if(next.origin!==location.origin)throw Error('Unexpected redirect.');const page=await fetch(next,{credentials:'same-origin'});if(!page.ok)throw Error('Saved, but the updated page could not be loaded.');await mount(new DOMParser().parseFromString(await page.text(),'text/html'),next);}else status(form,result.message||'Saved.');return;
  }
  const doc=new DOMParser().parseFromString(await response.text(),'text/html');
  if(!response.ok){const description=doc.querySelector('[data-error-description],.admin-notice.error,.alert-danger,p');throw Error(description?.textContent.trim()||'Save failed.');}
  // Return the server-rendered validation messages, new rows and one-time security codes.
  await mount(doc,finalURL);
 }catch(error){status(form,error.message||'Save failed.',true);}
 finally{delete form.dataset.adminBusy;form.removeAttribute('aria-busy');buttons.forEach((b,i)=>b.disabled=states[i]);}
});
})();
