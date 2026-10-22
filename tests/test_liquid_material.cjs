const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/js/liquid-glass.js'),'utf8');
async function run(success){const classes=new Set();let accept,reject;
 class Image{decode(){return new Promise((resolve,fail)=>{accept=resolve;reject=fail;});}}
 const doc={documentElement:{classList:{contains:c=>classes.has(c),add:c=>classes.add(c)}},querySelectorAll:()=>[],querySelector:()=>({getAttribute:()=> 'data:image/webp;base64,source-map'}),addEventListener(){}};
 vm.runInNewContext(source,{document:doc,window:{Image,CSS:{supports:()=>true}},Image,location:{hash:'',pathname:'/panel'},addEventListener(){}});
 assert.equal(classes.has('beeny-refraction-ready'),false,'Plain CSS blur remains the initial material.');
 if(success)accept();else reject(Error('decode failed'));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(classes.has('beeny-refraction-ready'),success);
}
(async()=>{await run(true);await run(false);console.log('PASS: refraction only enables after decode; failed decode preserves CSS blur; neither path waits for scrolling.');})().catch(e=>{console.error(e);process.exitCode=1;});
