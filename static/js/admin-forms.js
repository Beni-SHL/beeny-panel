/* Progressive form transport. Existing form-specific handlers keep precedence. */
(()=>{'use strict';
if(window.beenyAdminForms)return;window.beenyAdminForms=true;
const staticRoot=new URL('.',document.currentScript.src);
// Fixed paths and Subresource Integrity pins generated from this source release.
const approvedScripts={
  "admin-language.js": "sha256-eAEypkP/V9CyYRx3+PP+hCycNeUGYviKPtDSwA7MIzs=",
  "admin-security.js": "sha256-9G14/BJSrUrzUN6Uv7I95+UdpxrH3g9dPygvgdmYWBo=",
  "auth-bloom.js": "sha256-0ts/0RKWo7h1lFp72nQcenZNomaG0PUKnTnB1gzAek0=",
  "avatar-theme.js": "sha256-I4BgBFFNVz3vCUt73Phb16V0QCrqjsdOzSWB5Irg1Hc=",
  "backup-settings.js": "sha256-7VGfBXodxpcJKwv3YHaAFwLc5BHCAzBVtF3bp+uBues=",
  "bank-carousel.js": "sha256-S3bzFgSQ5hi8ZZREqjr85Y8okXI4/bTnBmxc6hWB43M=",
  "commissions.js": "sha256-l76aq16x4YNKAtmsJWrm2DaaMKnWmHrTcCrW4P75ysI=",
  "connection-guard.js": "sha256-LDR7iCFlxhKhP7HyghPv6c6B6ilXTFH0zzdj9jyMC/I=",
  "control-center.js": "sha256-8BwoAQr/ET7L6LYzsM+CJzc+T+VT/9dmLq310izYy64=",
  "dashboard-page.js": "sha256-bg/GbrF4KGGDdwjB72js0weGhgsRCpeDjdqHZ/5pyWI=",
  "direct-sale.js": "sha256-jzPsFAFZpdhGtBnTS/Q8hazcLfxrq9MKauVkiOuLJaY=",
  "dns-services.js": "sha256-/dAQ9pVQ+4klEVFfUjEV+936qxinblKdbFhM6vNfiQY=",
  "experience.js": "sha256-jALQJoydJ92hvwvJLHoaq/yyjgI2L2sqJ7cXcPbne0s=",
  "flags.js": "sha256-FdKRh+NAC61vlvUzexYDderQaT3o0Qy3ZZvtMOjn2ZM=",
  "general-settings.js": "sha256-31SSEDcR02Ctq+VR4uorSAYIJanw4kGs8VagEMWaEso=",
  "https-settings.js": "sha256-877bsGQzPnGZ+6dlXErrTHvYbG93uOHoVwWphyyNhbs=",
  "liquid-glass.js": "sha256-DY6r7JbYRJddGHCyyZ5JdHR2rcPqVBo7RKinsnUQaGE=",
  "maintenance.js": "sha256-tn++9ASrbLDL3H8WP/myOYo/it6JLv1be7ECUUIH0VM=",
  "monitoring.js": "sha256-keBynFdB5WTp84Mc+pBH+ksQ+jg3E3mu1JKRyWS7Oyw=",
  "network-settings.js": "sha256-YitmThuFKE088JF+qg46fGsXj4P/r0Sn1+r2c+gWUcc=",
  "password-controls.js": "sha256-33sBQ0dV/WTpiC06N9iJI1frv8wB7FQr5JKn/UQQZqw=",
  "performance.js": "sha256-9ArsdDtzT3ttmr6yvGrDJ826M0mqP5JewohTPOpwVpc=",
  "polish.js": "sha256-he3KMKrK8p6Sf2Q25d+UBJahVrZ9wznZ5/C2gsoR6AQ=",
  "portal-content.js": "sha256-E7kjZ3R29D1OqPvx80ZnU9LwSIoaRnAIWSbMUtYIv6M=",
  "portal.js": "sha256-czjN3rlGNtKXUKTKs7FAmNBa4kkPr7QIQ5OA4kGkc/M=",
  "pricing.js": "sha256-r7Zke2mow49nB6bmBf/A+qQNqt8Dbt7PEfQCt1PVBRA=",
  "quality.js": "sha256-dWbTZJJKkEHnLc1knyhb6SjAM4Gd055qC63FCZKYszQ=",
  "refinement.js": "sha256-ElMmRymghNMPAobC5NcbTStFgO+SEwL6Ztlv+uu4Ghc=",
  "release-344.js": "sha256-Ty1UuI95Nc398CjbTMW3782k0cxvqgYbHcdwL/UkTLI=",
  "representative-credit.js": "sha256-VYbl4UKfNeSd2MUgEZaLoXhGSP/9tlmme04iCEiHwv8=",
  "reseller-controls.js": "sha256-mQaw/FYwQhXzGL9xNoL3odBMZU7317P2Uhz3x3FQs7U=",
  "settings-forms.js": "sha256-fWDeD4thXQ2dXxOirPaGzvo7g2yP2BUt22rd2NId8Tk=",
  "share-access.js": "sha256-Uh/JDI3IF1UvSyzcSASjEPvjE1c8M+HBVyWBOjnT5ns=",
  "studio.js": "sha256-JbYvBwbva9xOFuAuNtJxfY9B96NVNGmpNk6DKzLjHXc=",
  "system-settings.js": "sha256-Nb6NZ9Bqe3Sw6aR4LmZ300s1mtjt4WnHy7EE1PFypGw=",
  "transports.js": "sha256-wG7sVmDVO35jc8jCxrPmOc2SpeqY6jCrJLve1T8XOE8=",
  "tunnels.js": "sha256-I1DfjkF5qzv3HrG9uq56+E9a/EErIbkcvEnEh10JkA4=",
  "users-page.js": "sha256-eckl4jfsw7pH2fwhSXQwGIanaR62iSaGPfZPngfLQw0=",
  "video-upload.js": "sha256-473GepeDKz4gchDhnSfpPdWnEKRYl1fDPys2RFuDdmM=",
  "vpn-settings.js": "sha256-ZbWZ7Z7MvQNKalFiid9gKYGIbxDmtPjBJMy63YagDdE=",
  "workspace.js": "sha256-3KiKNaqeQcjAhkmFZj/7O4Yw+9EVC+h5zJjfDNdvRcY="
};
function sanitize(root){
 root.querySelectorAll('iframe,object,embed,base,meta').forEach(node=>node.remove());
 root.querySelectorAll('*').forEach(node=>{
  for(const attribute of [...node.attributes]){
   const name=attribute.name.toLowerCase();
   if(name.startsWith('on')||name==='srcdoc')node.removeAttribute(attribute.name);
   else if(['href','src','action','formaction','xlink:href'].includes(name)){
    try{const link=new URL(attribute.value,location.href);if(!['http:','https:','mailto:','tel:'].includes(link.protocol))node.removeAttribute(attribute.name);}catch(e){node.removeAttribute(attribute.name);}
   }
  }
 });
}
const t=s=>window.adminT?.(s)||s;
function status(form,message,error=false){let out=form.querySelector('[data-admin-form-status]');if(!out){out=document.createElement('p');out.dataset.adminFormStatus='';out.setAttribute('role','status');out.setAttribute('aria-live','polite');form.append(out);}out.textContent=t(message);out.classList.toggle('form-error',error);return out;}
async function mount(doc,url){
 const incoming=doc.getElementById('admin-page'),current=document.getElementById('admin-page');
 if(!incoming||!current)throw Error('Your session may have expired. Refresh before retrying.');
 const scripts=[...incoming.querySelectorAll('script')];scripts.forEach(s=>s.remove());sanitize(incoming);
 current.replaceChildren(...incoming.childNodes);current.dataset.adminMounted='1';document.title=doc.title;
 if(url.origin===location.origin&&url.href!==location.href)history.replaceState(null,'',url.href);
 for(const original of scripts){
  if(original.type==='application/json'){current.append(original);continue;}
  if(!original.src)continue; // Server response text is data; never execute inline code.
  const src=new URL(original.getAttribute('src'),url.href);
  const name=src.pathname.startsWith(staticRoot.pathname)?src.pathname.slice(staticRoot.pathname.length):'';
  const integrity=approvedScripts[name];
  if(src.origin!==location.origin||!integrity)continue;
  const script=document.createElement('script');
  const asset=new URL(name,staticRoot);asset.searchParams.set('v',integrity.slice(7));
  script.src=asset.href;script.integrity=integrity;script.crossOrigin='anonymous';script.async=false;
  await new Promise((resolve,reject)=>{script.onload=resolve;script.onerror=()=>reject(Error('Saved, but page controls could not be loaded. Refresh this page.'));current.append(script);});
 }
 document.dispatchEvent(new CustomEvent('admin:content-ready'));
}
document.addEventListener('change',event=>{if(event.target.matches('[data-submit-on-change]'))event.target.form?.requestSubmit();});
document.addEventListener('click',event=>{if(event.target.closest('[data-print-page]'))window.print();});
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
