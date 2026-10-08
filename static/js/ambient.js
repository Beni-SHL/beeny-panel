(() => {
  const root=document.getElementById('react-bg-root');if(!root)return;
  root.classList.add('beeny-ambient');root.setAttribute('aria-hidden','true');
  for(let i=0;i<3;i++){const glow=document.createElement('span');glow.className='ambient-glow glow-'+i;root.append(glow);}
})();
