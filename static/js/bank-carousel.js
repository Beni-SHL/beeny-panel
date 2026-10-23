/* Customer views are replaced without replacing the dock; initialize each DOM root once. */
(()=>{'use strict';const roots=new WeakSet();function mount(){const view=document.querySelector('.workspace,.customer-shell');if(view){if(roots.has(view))return;roots.add(view);}else if(document.querySelector('.account-dock'))return;
(()=>{
 const carousel=document.querySelector('.bank-carousel');if(!carousel)return;
 const track=carousel.querySelector('.bank-slider'),slides=[...track.querySelectorAll('.bank-slide')];if(!slides.length)return;
 const copy=carousel.querySelector('.bank-copy-active'),position=carousel.querySelector('.bank-position');let index=0,timer;
 function activate(next,scroll=false){
 index=Math.max(0,Math.min(slides.length-1,next));
 slides.forEach((slide,i)=>{slide.classList.toggle('is-current',i===index);});
 const slide=slides[index];document.getElementById('active-bank-card').value=slide.dataset.cardId;copy.dataset.copyCard=slide.querySelector('.card-digits').textContent.replace(/\D/g,'');position.textContent=`${index+1} / ${slides.length}`;
 carousel.querySelector('[data-bank-step="-1"]').disabled=index===0;carousel.querySelector('[data-bank-step="1"]').disabled=index===slides.length-1;
 if(scroll){const rect=slide.getBoundingClientRect(),parent=track.getBoundingClientRect();track.scrollBy({left:(rect.left+rect.width/2)-(parent.left+parent.width/2),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})}
 }
 carousel.querySelectorAll('[data-bank-step]').forEach(b=>b.addEventListener('click',()=>activate(index+Number(b.dataset.bankStep),true)));

 function nearest(){const rect=track.getBoundingClientRect(),center=rect.left+rect.width/2;let best=0,distance=Infinity;slides.forEach((slide,i)=>{const r=slide.getBoundingClientRect(),d=Math.abs(r.left+r.width/2-center);if(d<distance){distance=d;best=i}});return best}
 copy.addEventListener('click',()=>activate(nearest()),true);
 track.addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(()=>{const rect=track.getBoundingClientRect(),center=rect.left+rect.width/2;let best=0,distance=Infinity;slides.forEach((slide,i)=>{const r=slide.getBoundingClientRect(),d=Math.abs(r.left+r.width/2-center);if(d<distance){distance=d;best=i}});activate(best)},180)});
 carousel.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();activate(index+(e.key==='ArrowLeft'?1:-1),true)}});activate(0);
})();

}mount();document.addEventListener('customer:content-ready',mount);})();
