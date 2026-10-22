/* Shared, validated theme data; native rendering, local assets only. */
(()=>{'use strict';if(window.BeenyTheme)return;const node=document.getElementById('beeny-theme-config');if(!node)return;let config,previewScope=null,previewMode=null;try{config=JSON.parse(node.textContent)}catch(_){return;}
 const root=document.documentElement,body=document.body,colors={iris:['#6854cf','#bcacff'],sunrise:['#bd4c28','#ffbf7b'],jade:['#16785e','#7de7b7'],ocean:['#2463bc','#98c8ff'],rose:['#b43b72','#ffafd1']};
 const customer=()=>Boolean(body.dataset.avatarChoice||body.classList.contains('customer-subpage')||body.classList.contains('rep-login')||body.dataset.authCustomer==='true');
 const mode=()=>body.classList.contains('light')||(!document.querySelector('.sidebar')&&root.dataset.theme!=='dark')?'light':'dark';
 const ink=hex=>{const v=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*v[0]+.7152*v[1]+.0722*v[2]>.179?'#171822':'#ffffff';};
 function hue(hex){const [r,g,b]=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255),mx=Math.max(r,g,b),mn=Math.min(r,g,b),d=mx-mn;return d?((mx===r?(g-b)/d:mx===g?(b-r)/d+2:(r-g)/d+4)*60+360)%360:210;}
 function hsl(h,s,l){s/=100;l/=100;const a=s*Math.min(l,1-l),f=n=>{const k=(n+h/30)%12;return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,9-k,1)))).toString(16).padStart(2,'0');};return '#'+f(0)+f(8)+f(4);}
 function tones(hex,selectedMode){const h=hue(hex);return selectedMode==='dark'?[hsl(h-20,44,11),hsl(h,65,43),hsl(h+1,20,20)]:[hsl(h+10,34,61),hsl(h+34,43,74),'#aeaeae'];}
 function palette(scope,selectedMode){const cfg=config[scope],m=cfg[selectedMode];if(scope!=='customer'||!cfg.avatar_colors||!body.dataset.avatarChoice)return m.colors;
  const hues=[165,230,32,335,145,190],h=hues[((Number(body.dataset.avatarChoice)||1)-1)%6];return selectedMode==='dark'?[hsl(h-20,44,11),hsl(h,65,43),hsl(h+1,20,20)]:[hsl(h+10,34,61),hsl(h+34,43,74),'#aeaeae'];}
 function apply(next=config,scopeOverride,modeOverride){config=next;if(scopeOverride){previewScope=scopeOverride;previewMode=modeOverride;}const scope=previewScope|| (customer()?'customer':'admin'),currentMode=previewMode||mode(),s=config[scope],m=s[currentMode],rgb=m.tint.slice(1).match(/../g).map(x=>parseInt(x,16));const gray=Math.round(m.shade*2.55),mixed=rgb.map(x=>m.colored===false?gray:Math.round(x*.48+gray*.52));
  const prop=(k,v)=>body.style.setProperty(k,v);prop('--beeny-glass-fill',`rgba(${mixed.join(',')},${m.opacity/100})`);prop('--beeny-material-fallback',`blur(${m.blur}px) saturate(${m.saturation}%)`);prop('--beeny-material-filter',`blur(${m.blur}px) var(--beeny-refraction,) saturate(${m.saturation}%)`);
  prop('--theme-icons',m.icons);prop('--theme-titles',m.titles);prop('--theme-button',m.buttons);prop('--theme-button-ink',ink(m.buttons));prop('--theme-button-'+currentMode,m.buttons);prop('--theme-button-ink-'+currentMode,ink(m.buttons));prop('--theme-bg-opacity',String(s.background_intensity/100));
  body.dataset.beenyThemeMode=currentMode;body.dataset.beenyThemeScope=scope;
  const bg=document.getElementById('react-bg-root');if(bg){bg.style.setProperty('background',currentMode==='dark'?'#08080c':'#fff','important');const c=palette(scope,currentMode);bg.style.setProperty('--stripe-color-1',c[0]);bg.style.setProperty('--stripe-color-2',c[1]);bg.style.setProperty('--stripe-color-3',c[2]);bg.style.setProperty('--background-opacity',s.background_intensity/100);}
  document.dispatchEvent(new CustomEvent('beeny:theme-updated',{detail:{scope,mode:currentMode,colors:palette(scope,currentMode),intensity:s.background_intensity}}));
 }
 window.BeenyTheme={apply,clearPreview(){previewScope=null;previewMode=null;apply();},get:()=>structuredClone(config),mode,palette,tones,ink,presets:colors};apply();
 const observer=new MutationObserver(()=>apply());observer.observe(root,{attributes:true,attributeFilter:['class','data-theme']});observer.observe(body,{attributes:true,attributeFilter:['class','data-avatar-choice']});document.addEventListener('admin:content-ready',()=>apply());
})();
