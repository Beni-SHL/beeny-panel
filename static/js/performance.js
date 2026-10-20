(()=>{'use strict';
 const html=document.documentElement;let scrollTimer,routeTimer,loadingDelay;
 function finish(){html.classList.remove('beeny-page-pending','beeny-route-pending');clearTimeout(routeTimer);clearTimeout(loadingDelay);}
 const frames=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 // Normal page content is never hidden while waiting for every font or asset.
 frames().then(finish);
 addEventListener('pageshow',()=>{finish();sync();});addEventListener('pagehide',()=>{window.__beenyBackgroundPaused=true;});
 const sync=()=>{window.__beenyBackgroundPaused=document.hidden||html.classList.contains('beeny-scrolling')||matchMedia('(prefers-reduced-motion: reduce)').matches;};
 document.addEventListener('visibilitychange',sync);
 function scrolling(){if(!html.classList.contains('beeny-scrolling')){html.classList.add('beeny-scrolling');sync();}clearTimeout(scrollTimer);scrollTimer=setTimeout(()=>{html.classList.remove('beeny-scrolling');sync();},180);}
 document.addEventListener('scroll',scrolling,{capture:true,passive:true});sync();
 function loading(event){clearTimeout(loadingDelay);loadingDelay=setTimeout(()=>{if(event?.defaultPrevented)return;html.classList.add('beeny-route-pending');routeTimer=setTimeout(finish,8000)},350);}
 document.addEventListener('click',event=>{const a=event.target.closest?.('a[href]');if(!a||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||a.hasAttribute('download')||a.matches('[data-admin-navigate],[data-no-page-loader]')||(a.target&&a.target!=='_self'))return;const url=new URL(a.href,location.href);if(url.origin!==location.origin)return;if(url.pathname===location.pathname&&url.search===location.search){return;}if(/\/(download|config|avatar|receipt)(\/|$)/.test(url.pathname)||a.classList.contains('configs-trigger'))return;queueMicrotask(()=>{if(!event.defaultPrevented)loading(event);});});
 // Saving forms report progress inline; only document navigation uses the route overlay.
})();
