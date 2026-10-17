const root=document.getElementById('react-bg-root');
if(root){
 // Administrative forms need a quiet background; reserve WebGL for the dashboard.
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const mobile=matchMedia('(max-width: 768px)').matches;
 const quiet=!!document.querySelector('#admin-page .cc-page')||reduced||mobile;
 let supported=false;
 if(!quiet){try{const canvas=document.createElement('canvas');const gl=canvas.getContext('webgl2')||canvas.getContext('webgl');supported=!!gl;if(gl)gl.getExtension('WEBGL_lose_context')?.loseContext()}catch(e){}}
 if(supported){try{await import('./index-CmGPzBYL.js')}catch(e){await import('./ambient.js')}}else{await import('./ambient.js')}
}
