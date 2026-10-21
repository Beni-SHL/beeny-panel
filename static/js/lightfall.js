/* Beeny Lightfall: native WebGL, using the existing panel shaders.
 * No framework, network requests, dynamic code evaluation or third-party runtime.
 */
const shaderURL=new URL('./lightfall-shaders.js',import.meta.url);shaderURL.search=new URL(import.meta.url).search;
const {vertex,fragment}=await import(shaderURL.href);
const root = document.getElementById('react-bg-root');
const mobileViewport=matchMedia('(max-width:768px)');
if (!root) throw new Error('Background root missing.');
const canvas = document.createElement('canvas');
canvas.setAttribute('aria-hidden', 'true');
canvas.style.cssText = 'width:100%;height:100%;display:block';
const gl = canvas.getContext('webgl', {alpha:true, antialias:false});
if (!gl) throw new Error('WebGL unavailable.');
function shader(type, source) {
  const item = gl.createShader(type);
  gl.shaderSource(item, source); gl.compileShader(item);
  if (!gl.getShaderParameter(item, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(item); gl.deleteShader(item); throw new Error(message);
  }
  return item;
}
const vs = shader(gl.VERTEX_SHADER, vertex), fs = shader(gl.FRAGMENT_SHADER, fragment);
const program = gl.createProgram();
gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
gl.deleteShader(vs); gl.deleteShader(fs);
if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
gl.useProgram(program);
const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
// Full-screen triangle: coordinates and UVs match the prior OGL triangle.
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,0,0, 3,-1,2,0, -1,3,0,2]), gl.STATIC_DRAW);
for (const [name,offset] of [['position',0],['uv',8]]) {
  const location = gl.getAttribLocation(program,name);
  gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location,2,gl.FLOAT,false,16,offset);
}
const uniforms = new Map();
function uniform(name) {if (!uniforms.has(name)) uniforms.set(name,gl.getUniformLocation(program,name)); return uniforms.get(name);}
const scalar = (name,value) => gl.uniform1f(uniform(name),value);
function rgb(hex) {return [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)/255);}
function theme() {
  const light = document.body.classList.contains('light');
  const colors = (light?['#5a8cff','#a855f7','#6366f1']:['#BEBEBE','#888888','#ECECEC']).map(rgb);
  for (let i=0;i<8;i++) gl.uniform3fv(uniform('uColor'+i),colors[Math.min(i,2)]);
  gl.uniform1i(uniform('uColorCount'),3);
  gl.uniform3fv(uniform('uBgColor'),rgb(light?'#E8EBF2':'#121212'));
  gl.uniform3fv(uniform('uMouseColor'),[0,1,2].map(i => colors.reduce((sum,c)=>sum+c[i],0)/3));
}
for (const [name,value] of Object.entries({uSpeed:0.5,uStreakWidth:1,uStreakLength:1,uGlow:1,uDensity:0.6,uTwinkle:1,uZoom:3,uBgGlow:0.5,uOpacity:1,uMouseEnabled:1,uMouseStrength:0.5,uMouseRadius:1})) scalar(name,value);
gl.uniform1i(uniform('uStreakCount'),2); theme();
function resize() {
  const rect = root.getBoundingClientRect(), pixels=mobileViewport.matches?320000:1200000;
  const dpr = Math.min(mobileViewport.matches ? 0.8 : 1.25,devicePixelRatio||1,Math.sqrt(pixels/Math.max(1,rect.width*rect.height)));
  canvas.width = Math.max(1,Math.round(rect.width*dpr)); canvas.height = Math.max(1,Math.round(rect.height*dpr));
  gl.viewport(0,0,canvas.width,canvas.height); gl.uniform3f(uniform('iResolution'),canvas.width,canvas.height,1);
}
let target=[0,0], mouse=[0,0], previous=0, frameAt=0, frame=0, stopped=false;
function pointer(event) {
  const rect=canvas.getBoundingClientRect();
  target=[(event.clientX-rect.left)*canvas.width/rect.width,(rect.height-event.clientY+rect.top)*canvas.height/rect.height];
}
function tick(time) {
  if(stopped)return; frame=requestAnimationFrame(tick);
  if(document.hidden||document.body.classList.contains('light')||window.__beenyBackgroundPaused||time-frameAt<(mobileViewport.matches?50:33))return;
  frameAt=time; const dt=previous?Math.min((time-previous)/1000,1):0;previous=time;
  const damping=1-Math.exp(-dt/0.15);
  mouse=mouse.map((v,i)=>v+(target[i]-v)*damping);
  gl.uniform2fv(uniform('iMouse'),mouse); scalar('iTime',time/1000); gl.drawArrays(gl.TRIANGLES,0,3);
}
const observer=new ResizeObserver(resize), themeObserver=new MutationObserver(theme);
function cleanup() {
  if(stopped)return;stopped=true;cancelAnimationFrame(frame);observer.disconnect();themeObserver.disconnect();
  canvas.removeEventListener('pointermove',pointer);gl.deleteBuffer(buffer);gl.deleteProgram(program);
  gl.getExtension('WEBGL_lose_context')?.loseContext();canvas.remove();
}
canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();cleanup();import(new URL('./ambient.js'+new URL(import.meta.url).search,import.meta.url).href);},{once:true});
root.append(canvas);resize();observer.observe(root);themeObserver.observe(document.body,{attributes:true,attributeFilter:['class']});
canvas.addEventListener('pointermove',pointer);window.addEventListener('pagehide',cleanup,{once:true});
window.addEventListener('pageshow',event=>{if(event.persisted&&stopped)location.reload();});
frame=requestAnimationFrame(tick);
