(() => {
  'use strict';
  const key='beeny-private-share-draft';
  const panel=document.querySelector('[data-share-user]');
  function getDraft() {
    try {const row=JSON.parse(sessionStorage.getItem(key)||'null');if(row && Date.now()-row.time<600000) return row;sessionStorage.removeItem(key);} catch (_) {}
    return null;
  }
  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', () => {
    const password=form.querySelector('[name=portal_password]');
    if (!password?.value) return;
    const user=document.querySelector('#username')?.value || panel?.dataset.shareUser;
    const login=form.querySelector('[name=portal_username]')?.value || user;
    if (!user) return;
    try {sessionStorage.setItem(key,JSON.stringify({user,login,password:password.value,time:Date.now()}));} catch (_) {}
  }));
  if (!panel) return;
  const draft=getDraft(), url=document.getElementById('customer_link')?.value;
  const output=panel.querySelector('textarea'), status=panel.querySelector('[data-share-status]');
  if (draft?.user===panel.dataset.shareUser && url) {
    output.value=`سلام 👋\nاطلاعات حساب بنی شما:\n\nآدرس پروفایل: ${url}\nنام کاربری: ${draft.login}\nرمز عبور: ${draft.password}\n\nبرای دیدن مصرف، دانلود کانفیگ و تمدید، وارد صفحه شخصی‌تان شوید. لطفاً این اطلاعات را محرمانه نگه دارید.`;
    try {sessionStorage.removeItem(key);} catch (_) {}
  } else {
    status.textContent='Save a new customer password, then generate the private link in this tab. Existing passwords cannot be retrieved.';
  }
  panel.querySelector('[data-share-copy]').addEventListener('click',async()=>{
    if (!output.value) return;
    try {await navigator.clipboard.writeText(output.value);status.textContent='Complete access message copied. Share it privately.';} catch (_) {output.focus();output.select();status.textContent='Select and copy the complete message manually.';}
  });
  panel.querySelector('[data-share-clear]').addEventListener('click',()=>{output.value='';try{sessionStorage.removeItem(key);}catch(_){}status.textContent='Private draft cleared.';});
})();
