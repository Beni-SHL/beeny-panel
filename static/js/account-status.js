/* Reuse the canonical edit form, including its permissions, activation checks and node sync. */
(()=>{'use strict';if(window.beenyAccountStatus)return;window.beenyAccountStatus=true;
 document.addEventListener('click',async event=>{const button=event.target.closest?.('[data-account-status]');if(!button)return;event.stopPropagation();if(button.disabled)return;
 const id=Number(button.dataset.accountStatus),root=button.closest('.users-page'),base=JSON.parse(document.getElementById('users-page-data').textContent).panelPath;if(!Number.isSafeInteger(id)||id<=0||root.dataset.canManage!=='true')return;
 const next=button.getAttribute('aria-checked')==='true'?'disabled':'active',endpoint=base+'/users/edit/'+id,fa=document.documentElement.lang==='fa';button.disabled=true;button.setAttribute('aria-busy','true');
 try{const source=await fetch(endpoint,{credentials:'same-origin'});if(!source.ok||source.redirected)throw Error(fa?'امکان ویرایش حساب وجود ندارد.':'Cannot edit this account.');const doc=new DOMParser().parseFromString(await source.text(),'text/html'),form=doc.querySelector('form[data-admin-ajax]');if(!form||new URL(form.getAttribute('action'),location.href).pathname!==endpoint)throw Error(fa?'فرم حساب معتبر نیست.':'Account form could not be verified.');
 const data=new FormData(form);data.set('status',next);data.set('csrf',document.querySelector('meta[name=csrf-token]')?.content||'');
 const result=await fetch(endpoint,{method:'POST',body:data,credentials:'same-origin'}),page=new DOMParser().parseFromString(await result.text(),'text/html'),state=page.querySelector('.ac-status')?.textContent.trim();if(!result.ok||state!==next)throw Error(page.querySelector('.ac-alert')?.textContent.trim()||(fa?'تغییر وضعیت تأیید نشد.':'Status change was not confirmed.'));
 button.setAttribute('aria-checked',String(next==='active'));button.lastElementChild.textContent=window.adminT?.(next)||next;document.dispatchEvent(new Event('beeny:accounts-refresh'));
 }catch(error){const stack=document.getElementById('toastStack'),message=document.createElement('p');message.className='toast error';message.setAttribute('role','alert');message.textContent=error.message;stack?.append(message);setTimeout(()=>message.remove(),6000);}
 finally{button.disabled=false;button.setAttribute('aria-busy','false');}
 });})();
