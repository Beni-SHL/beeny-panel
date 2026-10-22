// One shared Glass Fold background for admin, customer, partner and login shells.
const root=document.getElementById('react-bg-root');
if(root&&!root.classList.contains('beeny-background-plain')&&!root.dataset.backgroundLoading){
 root.dataset.backgroundLoading='true';
 const boot=async()=>{const url=new URL('./glass-fold.js',import.meta.url);url.search=new URL(import.meta.url).search;
  try{const {mountGlassFold}=await import(url.href);mountGlassFold(root)}catch(_){root.classList.add('background-fallback')}};
 requestAnimationFrame(()=>requestAnimationFrame(boot));
}
