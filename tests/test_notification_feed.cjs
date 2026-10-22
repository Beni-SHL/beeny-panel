const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
class Element{
 constructor(tag='div'){this.tagName=tag;this.dataset={};this.attrs={};this.children=[];this.listeners={};this.style={setProperty(){}};this.classList={toggle(){},add(){}};this.hidden=false;this.isConnected=true;this.scrollTop=0;this.textContent='';}
 setAttribute(k,v){this.attrs[k]=v;}append(...children){for(const child of children)this.children.push(...(child.tagName==='fragment'?child.children:[child]));}
 replaceChildren(...children){this.children=[];this.append(...children);}
 addEventListener(k,fn){this.listeners[k]=fn;}focus(){this.focused=true;}contains(){return true;}
}
const keys=['notification-bell','notification-popover','notification-items','notification-badge','notification-unread','notification-feedback','notification-close','notification-read','notification-clear'];
const nodes=Object.fromEntries(keys.map(k=>[k,new Element()])),center=new Element();center.dataset={notifications:'/panel/notifications',csrf:'test-csrf',locale:'en'};center.querySelector=s=>nodes[s.slice(1)];center.querySelectorAll=()=>[nodes['notification-read'],nodes['notification-clear']];nodes['notification-popover'].hidden=true;
const handlers={},document={hidden:false,querySelectorAll:()=>[center],addEventListener:(k,fn)=>handlers[k]=fn,createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag),createDocumentFragment:()=>new Element('fragment')};
let read=false,cleared=false,failed=false,pending,posts=[];const states=[];
const response=data=>({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data});
const context={window:{BeenyActionButton:{set:(b,state)=>states.push(state)}},document,Intl,Date,Set,Number,Math,String,Boolean,Error,URLSearchParams,setInterval:()=>1,clearInterval(){},fetch:async(url,options)=>{
 if(options.method==='POST'){posts.push([url,options.body]);if(failed)throw Error('offline');await new Promise(resolve=>pending=resolve);if(url.endsWith('/read'))read=true;else cleared=true;return response({ok:true});}
 return response({latest_id:42,unread:read?0:1,items:cleared?[]:[{id:42,title:'<img src=x onerror=alert(1)>',body:'Real body',read,created:'2026-10-22T00:00:00Z'}]});
}};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/notification-feed.js'),'utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{await tick();const items=nodes['notification-items'];assert.equal(items.children.length,1);let card=items.children[0];assert.equal(card.dataset.notification,'42');assert.equal(card.dataset.read,'false');assert.equal(card.children[1].children[1].textContent,'<img src=x onerror=alert(1)>');
 nodes['notification-bell'].listeners.click();await tick();assert.equal(nodes['notification-popover'].hidden,false);
 const reading=nodes['notification-read'].listeners.click({currentTarget:nodes['notification-read']});await tick();assert.equal(nodes['notification-read'].disabled,true);assert.equal(states.at(-1),'loading');assert.equal(posts[0][1].get('csrf'),'test-csrf');assert.equal(posts[0][1].get('upto'),'42');pending();await reading;assert.equal(items.children[0].dataset.read,'true');assert.equal(nodes['notification-badge'].hidden,true);assert.equal(states.at(-1),'success');
 failed=true;await nodes['notification-clear'].listeners.click({currentTarget:nodes['notification-clear']});assert.equal(items.children.length,1);assert.equal(states.at(-1),'error');assert.ok(nodes['notification-feedback'].textContent);assert.equal(nodes['notification-clear'].disabled,false);
 failed=false;const clearing=nodes['notification-clear'].listeners.click({currentTarget:nodes['notification-clear']});await tick();pending();await clearing;assert.equal(items.children[0].className,'notification-empty');
 center.listeners.keydown({key:'Escape'});assert.equal(nodes['notification-popover'].hidden,true);assert.equal(nodes['notification-bell'].focused,true);
 console.log('PASS: live notification data, safe text rendering, real pending/success/error states, CSRF/high-water mark, durable clear, empty state and Escape focus.');
})().catch(error=>{console.error(error);process.exitCode=1;});
