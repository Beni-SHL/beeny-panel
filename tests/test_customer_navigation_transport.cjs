const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/../static/js/customer-navigation.js','utf8');
async function boot({invalid=false,fail=false}={}){
 const events={},logs=[],base='https://panel.test/panel/c/token';let removedDock=false,version=0;
 class Node{constructor(name){this.name=name;this.dataset={};this.attrs={};this.children=[];this.className='';this.parentNode=null;}setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}querySelectorAll(){return [];}remove(){if(this===dock)removedDock=true;const i=body.children.indexOf(this);if(i>=0)body.children.splice(i,1);}append(...nodes){this.children.push(...nodes);} }
 const dock=new Node('dock');dock.dataset.accountHome='/panel/c/token';const canvas=new Node('canvas'),defs=new Node('defs'),oldView=new Node('old');
 const body=new Node('body');body.children=[canvas,defs,oldView,dock];body.insertBefore=(fragment)=>{logs.push('insert');body.children.splice(body.children.indexOf(dock),0,...fragment.children);};
 const location={href:base,origin:'https://panel.test',pathname:'/panel/c/token',search:'',hash:'',assign:url=>logs.push(['redirect',url])};
 const document={currentScript:{src:'https://panel.test/static/js/customer-navigation.js'},scripts:[],styleSheets:[],body,head:{insertBefore(){}},documentElement:{lang:'en',dir:'ltr'},title:'Old',
 querySelector:s=>s.startsWith('.account-dock')?dock:null,querySelectorAll:s=>s.startsWith('body>')?[canvas,defs]:[],createElement:n=>new Node(n),createDocumentFragment:()=>new Node('fragment'),importNode:n=>n,
 addEventListener:(type,fn)=>events[type]=fn,dispatchEvent:e=>logs.push(e.type),getElementById:()=>null};
 const incomingDock=new Node('incomingDock');incomingDock.dataset.accountHome=invalid?'/panel/c/foreign':'/panel/c/token';
 const incomingBody=new Node('incoming');incomingBody.childNodes=[new Node('newView')];incomingBody.className='customer-subpage';incomingBody.querySelectorAll=()=>[];
 const doc={title:'Support',body:incomingBody,documentElement:{lang:'fa',dir:'rtl'},querySelector:s=>s==='.account-dock'?incomingDock:new Node('newRoot'),querySelectorAll:()=>[]};
 const window={scrollTo:()=>logs.push('scroll'),BeenyTheme:{apply:()=>logs.push('theme')}};
 const history={state:{},replaceState(){},pushState(state,_,url){logs.push('push');const u=new URL(url);Object.assign(location,{href:u.href,pathname:u.pathname,hash:u.hash,search:u.search});history.state=state;}};
 vm.runInNewContext(source,{window,document,location,history,URL,AbortController,Promise,RegExp,Set,Error,CustomEvent:class{constructor(type,opts){this.type=type;this.detail=opts?.detail;}},DOMParser:class{parseFromString(){return doc}},scrollY:30,addEventListener:(k,f)=>events[k]=f,setTimeout:()=>1,fetch:async()=>{if(fail)throw Error('offline');return {ok:true,redirected:false,headers:{get:()=> 'text/html'},text:async()=>'<html>trusted response</html>'};}});
 return {api:window.BeenyCustomerNavigation,events,logs,dock,canvas,body,location,document,get removedDock(){return removedDock}};
}
(async()=>{
const ok=await boot();assert.equal(ok.api.allowed(new URL('https://evil.test/panel/c/token/tickets')),false);assert.equal(ok.api.allowed(new URL('https://panel.test/panel/c/other/tickets')),false);assert.equal(ok.api.allowed(new URL('https://panel.test/panel/c/token/download')),false);
assert.equal(await ok.api.navigate(new URL('https://panel.test/panel/c/token/tickets')),true);assert.equal(ok.removedDock,false);assert.ok(ok.body.children.includes(ok.dock));assert.ok(ok.body.children.includes(ok.canvas));assert.equal(ok.document.title,'Support');assert.equal(ok.document.documentElement.lang,'fa');assert.ok(ok.logs.includes('customer:content-ready'));assert.ok(ok.logs.indexOf('push')<ok.logs.indexOf('insert'));assert.equal(ok.dock.attrs['aria-busy'],undefined);
for(const opts of [{invalid:true},{fail:true}]){const bad=await boot(opts);await bad.api.navigate(new URL('https://panel.test/panel/c/token/wallet'));assert.equal(bad.logs.includes('push'),false);assert.equal(bad.logs.includes('insert'),false);assert.ok(bad.body.children.some(n=>n.className==='customer-navigation-error'));assert.equal(bad.removedDock,false);}
console.log('PASS: persistent dock/canvas, authenticated same-account route allowlist, verified document swap, history ordering, locale reinit and failure preserves the current view.');
})().catch(e=>{console.error(e);process.exitCode=1});
