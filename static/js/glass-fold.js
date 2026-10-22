// Native host for the user's GlassFold component; the shader is unchanged.
const shaderURL=new URL('./glass-fold-shaders.js',import.meta.url);
shaderURL.search=new URL(import.meta.url).search;
const {vertex,fragment}=await import(shaderURL.href);
export function mountGlassFold(root){
 if(root.dataset.glassFoldMounted)return;
 root.dataset.glassFoldMounted='true';
 const canvas=document.createElement('canvas');canvas.setAttribute('aria-hidden','true');
 const gl=canvas.getContext('webgl',{antialias:false,alpha:false});
 if(!gl){root.classList.add('background-fallback');return;}
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),mobile=matchMedia('(max-width:768px)');
 const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
 const palettes={dark:['#1e3cc8','#06081e','#96d7ff'],light:['#dadce7','#fffdfd','#e2f3f4']};
 let program,buffer,u,frame=0,elapsed=0,last=null,frameAt=0,stopped=false,lost=false,suspended=false;
 function compile(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);
  if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){gl.deleteShader(s);throw Error('Glass Fold shader failed');}return s;}
 function setup(){
  const vs=compile(gl.VERTEX_SHADER,vertex),fs=compile(gl.FRAGMENT_SHADER,fragment);
  program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);gl.deleteShader(vs);gl.deleteShader(fs);
  if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Glass Fold link failed');
  gl.useProgram(program);buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
  const position=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
  u=Object.fromEntries(['time','color1','color2','color3','scale','noise','resolution'].map(n=>[n,gl.getUniformLocation(program,'u_'+n)]));
 }
 function light(){return document.body.classList.contains('light')||(!document.querySelector('.sidebar')&&document.documentElement.dataset.theme!=='dark');}
 function draw(now){
  const rect=root.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2,Math.sqrt((mobile.matches?800000:2000000)/Math.max(1,rect.width*rect.height)));
  const width=Math.max(1,Math.round(rect.width*dpr)),height=Math.max(1,Math.round(rect.height*dpr));
  if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
  gl.viewport(0,0,width,height);
  if(last!==null)elapsed+=Math.min((now-last)/1000,.1)*.5;
  last=now;
  const colors=palettes[light()?'light':'dark'];
  colors.forEach((c,i)=>gl.uniform3fv(u['color'+(i+1)],rgb(c)));
  gl.uniform1f(u.time,elapsed);gl.uniform1f(u.scale,1);gl.uniform1f(u.noise,.12);gl.uniform2f(u.resolution,width,height);gl.drawArrays(gl.TRIANGLES,0,6);
 }
 function animated(){return !reduced.matches&&!window.__beenyBackgroundPaused;}
 function tick(now){frame=0;if(stopped||lost||suspended||document.hidden){last=null;return;}
  if(now-frameAt>=(mobile.matches?50:33)||!animated()){draw(now);frameAt=now;}
  if(animated())frame=requestAnimationFrame(tick);else last=null;
 }
 function refresh(){if(stopped||lost||suspended)return;
  cancelAnimationFrame(frame);frame=0;last=null;
  if(!document.hidden){draw(performance.now());if(animated())frame=requestAnimationFrame(tick);}
 }
 function cleanup(){stopped=true;cancelAnimationFrame(frame);resize.disconnect();theme.disconnect();
  document.removeEventListener('visibilitychange',refresh);reduced.removeEventListener('change',refresh);
  window.removeEventListener('pageshow',resume);gl.deleteBuffer(buffer);gl.deleteProgram(program);}
 function resume(){suspended=false;refresh();}
 try{setup();root.append(canvas);}catch(_){root.classList.add('background-fallback');return;}
 const resize=new ResizeObserver(refresh),theme=new MutationObserver(refresh);
 resize.observe(root);theme.observe(document.body,{attributes:true,attributeFilter:['class']});
 theme.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','class']});
 document.addEventListener('visibilitychange',refresh);reduced.addEventListener('change',refresh);
 canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();lost=true;cancelAnimationFrame(frame);root.classList.add('background-fallback');});
 canvas.addEventListener('webglcontextrestored',()=>{try{setup();lost=false;root.classList.remove('background-fallback');refresh();}catch(_){root.classList.add('background-fallback');}});
 window.addEventListener('pagehide',event=>{suspended=true;cancelAnimationFrame(frame);last=null;if(!event.persisted)cleanup();});
 window.addEventListener('pageshow',resume);refresh();
}
