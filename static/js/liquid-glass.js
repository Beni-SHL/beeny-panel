/* Adapted from the supplied trackPrevious radio switcher. Reinitializes after AJAX. */
(()=>{function init(){document.querySelectorAll('[data-liquid-switcher]').forEach(el=>{if(el.dataset.liquidReady)return;el.dataset.liquidReady='1';let previousValue=el.querySelector('input[type=radio]:checked')?.getAttribute('c-option')||null;if(previousValue)el.setAttribute('c-previous',previousValue);el.addEventListener('change',event=>{const radio=event.target;if(!radio.matches('input[type=radio]')||!radio.checked)return;el.setAttribute('c-previous',previousValue??'');previousValue=radio.getAttribute('c-option')||radio.value;el.querySelectorAll('[data-liquid-active]').forEach(item=>item.removeAttribute('data-liquid-active'));radio.closest('label')?.setAttribute('data-liquid-active','')})})}init();document.addEventListener('admin:content-ready',init)})();
/* Shared account dock and account-menu keyboard behavior. */
(()=>{'use strict';if(window.beenyAccountNavigation)return;window.beenyAccountNavigation=true;
 function sync(){const hash=location.hash.slice(1),tickets=/\/tickets(?:\/|$)/.test(location.pathname);document.querySelectorAll('[data-dock-section]').forEach(a=>{const name=a.dataset.dockSection,active=tickets?name==='tickets':name===(['renew','configs'].includes(hash)?hash:'overview');if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});}
 addEventListener('hashchange',sync);sync();
 document.addEventListener('click',event=>document.querySelectorAll('.account-menu[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false;}));
 document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.account-menu[open]').forEach(menu=>{menu.open=false;menu.querySelector('summary')?.focus();});});
})();

/* Blur is CSS-first; enable the optional source-map distortion only after decode. */
(()=>{if(document.documentElement.classList.contains('beeny-refraction-ready')||!window.Image||!window.CSS?.supports('backdrop-filter','url("#beeny-liquid")'))return;
 const map=document.querySelector('#beeny-liquid feImage')?.getAttribute('href');if(!map)return;
 const image=new Image();image.src=map;
 const ready=()=>document.documentElement.classList.add('beeny-refraction-ready');
 if(image.decode)image.decode().then(ready,()=>{});else{image.onload=ready;if(image.complete&&image.naturalWidth)ready();}
})();
