// Execute the real client script with the form's named `action` control shadowing
// its URL property, as HTMLFormElement exposes named controls to JavaScript.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function exercise(script,response){
 const events={},button={disabled:false},output={textContent:''},small={textContent:''};
 const form={action:{name:'action',value:'price'},fields:{action:'price',csrf:'csrf-fixture',plan_id:'monthly',price:'290000'},getAttribute:n=>n==='action'?'/panel/c/fixture/reseller/commission':null,reportValidity:()=>true,querySelector:n=>n==='button'?button:n==='small'?small:output,addEventListener:(n,f)=>events[n]=f};
 const calls=[];const context={console,Intl,URL,Promise,location:{href:'https://panel.example/panel/c/fixture/reseller/credit/prices'},matchMedia:()=>({matches:true}),addEventListener:()=>{},setTimeout,clearTimeout,document:{documentElement:{lang:'fa'},baseURI:'https://panel.example/panel/c/fixture/reseller/credit/prices',fonts:{ready:Promise.resolve()},createElement:()=>({getContext:()=>null}),querySelectorAll:n=>n==='[data-price-ajax]'?[form]:[],querySelector:()=>null,getElementById:()=>null},FormData:class{constructor(f){this.fields=f.fields;}},fetch:async(url,options)=>{calls.push({url,options});if(typeof url!=='string'||url!=='https://panel.example/panel/c/fixture/reseller/commission')return {ok:false,status:404,redirected:false,headers:{get:()=> 'text/html'}};return response;}};
 vm.runInNewContext(script,context);await events.submit({preventDefault:()=>{}});return {calls,output,button,small};
}
const reply=(status,data,redirected=false)=>({ok:status>=200&&status<300,status,redirected,headers:{get:()=>data?'application/json':'text/html'},json:async()=>data});
(async()=>{
 const script=fs.readFileSync(__dirname+'/../static/js/representative-credit.js','utf8');
 const good=await exercise(script,reply(200,{ok:true,price:290000,base:200000,message:'قیمت فروش ذخیره شد'}));
 assert.equal(good.calls.length,1);assert.equal(good.calls[0].url,'https://panel.example/panel/c/fixture/reseller/commission');assert.equal(good.calls[0].options.body.fields.price,'290000');assert.equal(good.calls[0].options.body.fields.action,'price');assert.equal(good.calls[0].options.body.fields.csrf,'csrf-fixture');assert.match(good.output.textContent,/ذخیره شد/);assert.equal(good.button.disabled,false);
 const invalid=await exercise(script,reply(400,{ok:false,error:'قیمت باید بین 200,000 و 300,000 تومان باشد.'}));assert.match(invalid.output.textContent,/300,000/);
 const locked=await exercise(script,reply(403,{ok:false,error:'نمایندگی قفل است'}));assert.equal(locked.output.textContent,'نمایندگی قفل است');
 const expired=await exercise(script,reply(200,null,true));assert.match(expired.output.textContent,/نشست ورود/);
 const failed=await exercise(script,reply(500,null));assert.match(failed.output.textContent,/ذخیره قیمت انجام نشد/);assert.equal(failed.button.disabled,false);
 if(process.argv[2]){const old=fs.readFileSync(process.argv[2],'utf8'),bad=await exercise(old,reply(200,{ok:true,price:290000,base:200000,message:'Saved'}));assert.notEqual(typeof bad.calls[0].url,'string');assert.match(bad.output.textContent,/بازه مجاز/);console.log('Previous script reproduced the named-action failure.');}
 console.log('Price client: correct URL/body, valid save, range error, locked account, expired login and server failure passed.');
})().catch(e=>{console.error(e);process.exit(1)});
