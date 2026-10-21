const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
async function test(lostInstall=false){
 const fields=new Map(),timers=[],calls=[];let state={success:true,installed:'3.7.4',release:{version:'3.7.5',commit:'a'.repeat(40),available:true,checked_at:Date.now()/1000},job:null};
 function field(key){if(!fields.has(key))fields.set(key,{hidden:false,disabled:false,textContent:'',classList:{toggle(){}},setAttribute(){},removeAttribute(){}});return fields.get(key)}
 const root={dataset:{url:'/panel/api/settings/update'},isConnected:true,querySelector:field,querySelectorAll:()=>['queued','fetching','installing','completed'].map(field)};
 const context={window:{adminT:s=>s},document:{getElementById:()=>root,querySelector:()=>({content:'csrf'}),addEventListener(){}},setTimeout:(cb,delay)=>{timers.push({cb,delay});return timers.length},clearTimeout(){},confirm:()=>true,Date,JSON,fetch:async(url,options)=>{let request=JSON.parse(options.body);calls.push(request);assert.equal(options.headers['X-CSRF-Token'],'csrf');if(request.action==='install'){assert.equal(request.commit,'a'.repeat(40));state.job={id:'abc',state:'queued',message:'Update queued.'};if(lostInstall)throw Error('connection lost')}return {ok:true,json:async()=>structuredClone(state)}}};
 vm.runInNewContext(fs.readFileSync(__dirname+'/../static/js/panel-update.js','utf8'),context);
 const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};await flush();
 assert.equal(field('[data-install]').disabled,false);
 field('[data-install]').onclick();await flush();
 assert.equal(calls.filter(c=>c.action==='install').length,1);
 assert(timers.some(t=>t.delay===5000),'queued or unacknowledged install must retry status');
 timers.find(t=>t.delay===5000).cb();await flush();
 assert.equal(field('[data-install]').disabled,true);
 assert.equal(field('[data-job]').hidden,false);
 state.job.state='completed';state.installed='3.7.5';state.release.available=false;
 timers[timers.length-1].cb();await flush();assert.equal(field('[data-reopen]').hidden,false);assert.equal(field('[data-installed]').textContent,'3.7.5');
}
(async()=>{await test();await test(true);console.log('PASS: AJAX update queue, CSRF, commit pin, reconnect retry after lost install response and completion.');})().catch(e=>{console.error(e);process.exitCode=1});
