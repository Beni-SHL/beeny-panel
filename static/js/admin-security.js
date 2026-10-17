(() => {
  'use strict';
  const csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content;
  const original=window.fetch;
  window.fetch=function(input,init={}) {
    const url=new URL(input instanceof Request?input.url:input,location.href);
    const method=(init.method||(input instanceof Request?input.method:'GET')).toUpperCase();
    if(url.origin===location.origin&&!['GET','HEAD','OPTIONS'].includes(method)) {
      init={...init,headers:new Headers(init.headers||(input instanceof Request?input.headers:undefined))};
      init.headers.set('X-CSRF-Token',csrf()||'');
    }
    return original.call(this,input,init);
  };
  function protect(form) {
    if((form.getAttribute('method')||'get').toLowerCase()==='get'||new URL(form.getAttribute('action')||location.href,location.href).origin!==location.origin)return;
    if(!form.querySelector('[name="csrf"]')) {
      const field=document.createElement('input');field.type='hidden';field.name='csrf';field.value=csrf()||'';form.append(field);
    }
  }
  document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('form').forEach(protect));
  document.addEventListener('submit',event=>protect(event.target),true);
  document.addEventListener('click',event=> {
    if(event.defaultPrevented)return;
    const link=event.target.closest('a[href]');
    if(!link)return;
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin||!/(\/users\/(delete|reset_traffic)\/\d+|\/settings\/nodes\/delete\/\d+)$/.test(url.pathname))return;
    event.preventDefault();
    const form=document.createElement('form');form.method='post';form.action=url.href;document.body.append(form);protect(form);form.dataset.adminAjax='';form.requestSubmit();
  });
})();
