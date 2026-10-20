const root=document.getElementById('react-bg-root');
if(root){
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 if(reduced){await import('./ambient.js')}
 else{try{await import('./lightfall.js')}catch(e){await import('./ambient.js')}}
}
