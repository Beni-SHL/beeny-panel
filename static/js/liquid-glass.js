/* Adapted from the supplied trackPrevious radio switcher. Reinitializes after AJAX. */
(()=>{function init(){document.querySelectorAll('[data-liquid-switcher]').forEach(el=>{if(el.dataset.liquidReady)return;el.dataset.liquidReady='1';let previousValue=el.querySelector('input[type=radio]:checked')?.getAttribute('c-option')||null;if(previousValue)el.setAttribute('c-previous',previousValue);el.addEventListener('change',event=>{const radio=event.target;if(!radio.matches('input[type=radio]')||!radio.checked)return;el.setAttribute('c-previous',previousValue??'');previousValue=radio.getAttribute('c-option')||radio.value;el.querySelectorAll('[data-liquid-active]').forEach(item=>item.removeAttribute('data-liquid-active'));radio.closest('label')?.setAttribute('data-liquid-active','')})})}init();document.addEventListener('admin:content-ready',init)})();
/* Shared account dock and account-menu keyboard behavior. */
(()=>{'use strict';if(window.beenyAccountNavigation)return;window.beenyAccountNavigation=true;
 const reduce=()=>window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
 // Exact supplied spring parameters: stiffness 420, damping 30, mass .7.
 function spring(from,to){const frames=[];let x=from,v=0;for(let i=0;i<=48;i++){frames.push({width:x+'px',offset:i/48});const dt=.01;v+=(-420*(x-to)-30*v)/.7*dt;x+=v*dt;}frames[48].width=to+'px';return frames;}
 function sync(animate=true){const hash=location.hash.slice(1),page=/\/(tickets|wallet|devices|renew)(?:\/|$)/.exec(location.pathname)?.[1],section=page||(['renew','configs'].includes(hash)?hash:'overview');
 document.querySelectorAll('.account-dock').forEach(nav=>{if(nav.parentElement!==document.body)document.body.append(nav);nav.querySelectorAll('[data-dock-section]').forEach(a=>{const active=a.dataset.dockSection===section,was=a.hasAttribute('aria-current'),from=a.getBoundingClientRect().width,label=a.querySelector('.dock-label'),target=active?Math.min(200,46+label.scrollWidth):40;
 a.style.setProperty('--dock-active-width',target+'px');if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
 if(animate&&was!==active&&!reduce()&&a.animate){a._dockAnimation?.cancel();a._dockAnimation=a.animate(spring(from,target),{duration:480,easing:'linear'});}
 if(active&&nav.scrollWidth>nav.clientWidth)requestAnimationFrame(()=>a.scrollIntoView({behavior:reduce()?'instant':'smooth',block:'nearest',inline:'nearest'}));
 });});}
 addEventListener('hashchange',()=>sync());addEventListener('resize',()=>sync(false));document.fonts?.ready.then(()=>sync(false));sync(false);
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
