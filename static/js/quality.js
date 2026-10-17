(()=>{
 'use strict';
 function init(){
 const tabRoot=document.querySelector('[data-settings-tabs]');
 if(tabRoot){
   const panels=[...tabRoot.querySelectorAll('.admin-tab-panel')],buttons=[...tabRoot.querySelectorAll('[role=tab]')];
   function select(id){panels.forEach(p=>p.hidden=p.id!==id);buttons.forEach(b=>{b.setAttribute('aria-selected',String(b.dataset.target===id));b.tabIndex=b.dataset.target===id?0:-1;});}
   buttons.forEach((button,index)=>{button.addEventListener('click',()=>select(button.dataset.target));button.addEventListener('keydown',event=>{if(['ArrowRight','ArrowLeft'].includes(event.key)){event.preventDefault();const next=buttons[(index+(event.key==='ArrowRight'?1:buttons.length-1))%buttons.length];select(next.dataset.target);next.focus();}});});
   const form=tabRoot.querySelector('form');form.addEventListener('invalid',event=>{const panel=event.target.closest('.admin-tab-panel');if(panel)select(panel.id);},true);
   const button=form.querySelector('[type=submit]');form.addEventListener('input',()=>{button.textContent='Save changes';});select(panels.some(p=>p.id===location.hash.slice(1))?location.hash.slice(1):panels[0].id);
 }
}
init();document.addEventListener('admin:content-ready',init);
})();
