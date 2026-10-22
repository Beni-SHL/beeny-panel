const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/../static/js/liquid-glass.js','utf8');
function run(pathname,hash,reduced=false){const listeners={},animations=[];let scrolls=0;
 const links=['overview','renew','configs','tickets','wallet','devices'].map(name=>{const attrs=new Map(),vars={};return {dataset:{dockSection:name},style:{setProperty:(k,v)=>vars[k]=v},vars,hasAttribute:k=>attrs.has(k),setAttribute:(k,v)=>attrs.set(k,v),removeAttribute:k=>attrs.delete(k),querySelector:()=>({scrollWidth:name==='overview'?81:45}),getBoundingClientRect:()=>({width:40}),animate:(frames,opts)=>{animations.push({frames,opts});return{cancel(){}}},scrollIntoView(){scrolls++},attrs};});
 const body={},nav={parentElement:body,querySelectorAll:()=>links,scrollWidth:450,clientWidth:320};
 const doc={body,documentElement:{classList:{contains:()=>true}},querySelectorAll:sel=>sel==='.account-dock'?[nav]:[],addEventListener(){},fonts:{ready:Promise.resolve()}};
 const location={pathname,hash};vm.runInNewContext(source,{window:{matchMedia:()=>({matches:reduced})},document:doc,location,requestAnimationFrame:fn=>fn(),addEventListener:(name,fn)=>listeners[name]=fn});
 return {links,location,listeners,animations,get scrolls(){return scrolls}};
}
for(const [path,hash,name] of [['/panel/c/token','#renew','renew'],['/panel/c/token','#configs','configs'],['/panel/c/token/wallet','','wallet'],['/panel/c/token/tickets/12','','tickets'],['/panel/c/token/devices','','devices']]){const r=run(path,hash);assert.equal(r.links.find(a=>a.attrs.has('aria-current')).dataset.dockSection,name);assert.ok(r.scrolls>0);}
const r=run('/panel/c/token','');r.location.hash='#renew';r.listeners.hashchange();assert.equal(r.animations.length,2);for(const a of r.animations){assert.equal(a.frames.length,49);assert.equal(a.opts.duration,480);assert.ok(a.frames.every(x=>Number.isFinite(parseFloat(x.width))));}assert.equal(r.links[1].vars['--dock-active-width'],'91px');
const reduced=run('/panel/c/token','',true);reduced.location.hash='#renew';reduced.listeners.hashchange();assert.equal(reduced.animations.length,0);
console.log('PASS: renewal/download/wallet/support/devices active links, measured expansion, exact spring integration, overflow reveal and reduced motion.');
