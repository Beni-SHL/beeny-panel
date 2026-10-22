// One shared Glass Fold background for admin, customer, partner and login shells.
const root=document.getElementById('react-bg-root');
if(root&&!root.classList.contains('beeny-background-plain')&&!root.dataset.backgroundLoading){
 root.dataset.backgroundLoading='true';
 const boot=async()=>{const customer=root.classList.contains('beeny-background-customer');const url=new URL(customer?'./stripe-background.js':'./glass-fold.js',import.meta.url);url.search=new URL(import.meta.url).search;
  try{const component=await import(url.href);(customer?component.mountStripe:component.mountGlassFold)(root)}catch(_){root.classList.add('background-fallback')}};
 requestAnimationFrame(()=>requestAnimationFrame(boot));
}
