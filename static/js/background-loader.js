// Present the workspace first. Compile WebGL only when a dark background is visible.
const root=document.getElementById('react-bg-root');
if(root){
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');let loaded=false,queued=false;
 const ambient=()=>import('./ambient.js');
 function start(){if(loaded||queued||document.body.classList.contains('light')||reduced.matches)return;queued=true;
  const boot=async()=>{queued=false;if(document.body.classList.contains('light')||document.hidden)return;loaded=true;
   try{await import('./lightfall.js')}catch(_){await ambient()}};
  requestAnimationFrame(()=>requestAnimationFrame(()=>{if('requestIdleCallback' in window)requestIdleCallback(boot,{timeout:1200});else setTimeout(boot,100)}));
 }
 if(reduced.matches)ambient();else start();
 new MutationObserver(start).observe(document.body,{attributes:true,attributeFilter:['class']});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)start()});
}
