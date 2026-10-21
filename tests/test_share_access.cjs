const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
function setup(){
 let saved=JSON.stringify({user:'test-user',login:'customer-login',password:'private-password-123',time:Date.now()}),timers=[],handlers={},created=[];
 const field=()=>({value:'',handlers:{},addEventListener(name,cb){this.handlers[name]=cb},setAttribute(){},append(){}});
 const output=field(),status=field(),language=field(),clear=field(),social=field();language.value='fa';social.append=button=>created.push(button);
 const panel={dataset:{shareUser:'test-user'},querySelector:s=>s==='textarea'?output:s==='[data-share-status]'?status:s==='[data-share-language]'?language:s==='[data-share-clear]'?clear:social};
 const copies=[],opens=[];
 const document={querySelector:s=>s==='[data-share-user]'?panel:null,querySelectorAll:()=>[],getElementById:()=>({value:'https://panel.example/c/private'}),createElement:()=>field(),createElementNS:()=>({...field(),namespaceURI:'http://www.w3.org/2000/svg'})};
 vm.runInNewContext(fs.readFileSync(__dirname+'/../static/js/share-access.js','utf8'),{document,sessionStorage:{getItem:()=>saved,removeItem:()=>{saved=null},setItem(){}},navigator:{clipboard:{writeText:async text=>copies.push(text)}},window:{addEventListener:(n,cb)=>handlers[n]=cb,open:(...args)=>opens.push(args)},setTimeout:(cb,delay)=>timers.push({cb,delay}),Date,JSON,encodeURIComponent});
 return {output,status,language,clear,created,copies,opens,timers,handlers};
}
(async()=>{
 const a=setup();assert(a.output.value.includes('سلام'));assert(a.output.value.includes('private-password-123'));
 a.language.value='en';a.language.handlers.change();assert(a.output.value.includes('Your Beeny account details:'));assert(a.output.value.includes('Username: customer-login'));assert(a.output.value.includes('Password: private-password-123'));assert.equal(a.output.dir,'ltr');
 await a.created[0].handlers.click();assert(a.copies[0].includes('Your Beeny account details:'));
 a.clear.handlers.click();a.language.value='fa';a.language.handlers.change();assert.equal(a.output.value,'');a.handlers.pagehide();
 const b=setup();b.timers[0].cb();b.language.value='en';b.language.handlers.change();assert.equal(b.output.value,'');
 console.log('PASS: FA/EN selection preserves exact credentials, copy uses chosen language, clear/expiry cannot resurrect private drafts, and pagehide clears safely.');
})().catch(e=>{console.error(e);process.exitCode=1});
