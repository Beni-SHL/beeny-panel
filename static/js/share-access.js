(()=>{'use strict';
 const key='beeny-private-share-draft',panel=document.querySelector('[data-share-user]');
 function draft(){try{const row=JSON.parse(sessionStorage.getItem(key)||'null');if(row&&Date.now()-row.time<600000)return row;sessionStorage.removeItem(key)}catch(_){}return null}
 async function copy(text){try{await navigator.clipboard.writeText(text)}catch(_){const input=document.createElement('textarea');input.value=text;input.style.cssText='position:fixed;opacity:0';document.body.append(input);input.select();const ok=document.execCommand('copy');input.remove();if(!ok)throw Error('Copy unavailable')}}
 document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',()=>{const password=form.querySelector('[name=portal_password]');if(!password?.value)return;const user=document.querySelector('#username')?.value||panel?.dataset.shareUser,login=form.querySelector('[name=portal_username]')?.value||user;if(user)try{sessionStorage.setItem(key,JSON.stringify({user,login,password:password.value,time:Date.now()}))}catch(_){}}));
 if(!panel)return;const row=draft(),url=document.getElementById('customer_link')?.value,output=panel.querySelector('textarea'),status=panel.querySelector('[data-share-status]');let password='',login=document.querySelector('[name=portal_username]')?.value||panel.dataset.shareUser;
 if(row?.user===panel.dataset.shareUser){password=row.password;login=row.login}
 const language=panel.querySelector('[data-share-language]');let cleared=false;
 function render(){
  if(cleared)return;
  const en=language?.value==='en';output.lang=en?'en':'fa';output.dir=en?'ltr':'rtl';
  if(url){
   output.value=en?`Hello 👋\nYour Beeny account details:\n\n🔗 Personal page: ${url}\n👤 Username: ${login}${password?'\n🔐 Password: '+password:''}\n\n📊 View usage and remaining allowance\n📥 Download VPN profiles and connection guides\n💳 Renew your service and top up your wallet\n\nThese details are private. Keep them confidential.`:`سلام 👋\nاطلاعات حساب بنی شما:\n\n🔗 صفحهٔ شخصی: ${url}\n👤 نام کاربری: ${login}${password?'\n🔐 رمز عبور: '+password:''}\n\n📊 مشاهدهٔ مصرف و اعتبار\n📥 دانلود کانفیگ و راهنمای اتصال\n💳 تمدید سرویس و شارژ کیف پول\n\nاین اطلاعات شخصی است؛ آن را محرمانه نگه دارید.`;
   if(!password)status.textContent='Set a new customer password to include it in this message. Existing passwords cannot be recovered.';
  }else status.textContent='Generate the private profile link to prepare the access message.';
 }
 render();language?.addEventListener('change',render);
 if(url&&password)try{sessionStorage.removeItem(key)}catch(_){}

 const paths={copy:'M9 8V3h12v14h-5M3 8h12v13H3Z',telegram:'M3 10 21 3l-5 18-5-7-8-4Zm8 4L21 3',whatsapp:'M21 11.5a9 9 0 0 1-13 8L3 21l1.5-5A9 9 0 1 1 21 11.5ZM8 8c1 4 3 6 7 7',instagram:'M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4Zm5 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM17 7h.01',share:'M12 16V3m-5 5 5-5 5 5M4 13v8h16v-8'};
 function icon(button,name,label){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[name]);svg.append(path);button.append(svg);button.title=label;button.setAttribute('aria-label',label);}
 const socials=panel.querySelector('[data-share-social]');
 for(const [name,label] of [['copy','Copy message'],['telegram','Telegram'],['whatsapp','WhatsApp'],['instagram','Instagram']]){const button=document.createElement('button');button.type='button';button.className='ac-btn '+name;icon(button,name,label);button.addEventListener('click',async()=>{if(!output.value){status.textContent='Generate a private link first.';return}try{if(name==='telegram')window.open('https://t.me/share/url?url='+encodeURIComponent(url)+'&text='+encodeURIComponent(output.value),'_blank','noopener,noreferrer');else if(name==='whatsapp')window.open('https://wa.me/?text='+encodeURIComponent(output.value),'_blank','noopener,noreferrer');else{await copy(output.value);status.textContent=name==='instagram'?'Message copied. Paste it into your Instagram conversation.':'Complete message copied ✓';if(name==='instagram')window.open('https://www.instagram.com/','_blank','noopener,noreferrer')}}catch(_){status.textContent='Copy is unavailable in this browser.'}});socials.append(button)}
 if(navigator.share){const button=document.createElement('button');button.type='button';button.className='ac-btn';icon(button,'share','Share…');button.addEventListener('click',async()=>{if(!output.value)return;try{await navigator.share({title:'Beeny account',text:output.value})}catch(_){}});socials.append(button)}
 panel.querySelector('[data-share-clear]')?.addEventListener('click',()=>{cleared=true;output.value='';password='';try{sessionStorage.removeItem(key)}catch(_){}status.textContent='Private draft cleared.'});
 setTimeout(()=>{cleared=true;output.value='';password='';status.textContent='Private draft expired.'},Math.max(0,600000-(row?Date.now()-row.time:0)));window.addEventListener('pagehide',()=>{cleared=true;output.value='';password='';});
})();
