import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {notice} from '../extension/policy.js';
import {CHAT,OTHER} from './harness.js';
const html=fs.readFileSync(new URL('../extension/popup.html',import.meta.url),'utf8');
const source=fs.readFileSync(new URL('../extension/popup.js',import.meta.url),'utf8').replace(/^import .*;\n/,'');
const flush=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));};
function popup(send, url=CHAT) {
 const elements={};
 for(const [,id] of html.matchAll(/id="([^"]+)"/g)) elements[id]={value:id==='delay'?'0':'',textContent:'',disabled:false,checked:false,handlers:{},addEventListener(k,f){this.handlers[k]=f;},replaceChildren(){},add(){}};
 const messages=[];
 vm.runInNewContext(source,{document:{getElementById:id=>elements[id]},Option:function(text,value){return {text,value};},notice,
  chrome:{tabs:{query:async()=>[{url}]},runtime:{sendMessage:async m=>{messages.push(m);return send(m);}}}});
 return {elements,messages,async select(ref){elements.project.value=ref;elements.project.handlers.change();await flush();}};
}
const rows=[{project_ref:'alpha',root:'/synthetic/a'},{project_ref:'beta',root:'/synthetic/b'}];
const states={alpha:{binding:{project:'alpha',route:CHAT,tabId:77,generation:'private-generation'},events:[],automation:{enabled:true,route:CHAT,delayMs:0,error:null,deliveries:[{batch_ref:'batch-0000000000000001',status:'attempted_unknown',code:'COMMIT_API_UNKNOWN_REBIND',outcome:'unknown'}]}},beta:{binding:{project:'beta',route:CHAT},events:[],automation:{enabled:false,route:CHAT,delayMs:60000,error:null,deliveries:[]}}};
test('daily popup is compact; recovery and diagnostics remain reachable but collapsed',()=>{
 const normal=html.split('<details id="diagnostics">')[0];
 assert.deepEqual([...normal.matchAll(/<button id="([^"]+)"/g)].map(x=>x[1]),['enable','disable']);
 assert(!normal.includes('<pre'));assert(!/<details[^>]*\bopen\b/.test(html));
 for(const id of ['verify','inspect','bind','unbind','status','close_delivery','delay','armed','arm','retry','cancel','confirm'])
   assert(html.indexOf('id="'+id+'"')>normal.length,id);
});
test('selected project status and unknown recovery are independent without route, scope or raw JSON exposure',async()=>{
 const p=popup(async m=>({ok:true,projects:rows,selected:m.project_ref,state:states[m.project_ref]}));await flush();
 await p.select('alpha');const e=p.elements;
 assert.match(e.destination.textContent,/当前 Chat/);assert.match(e['automatic-status'].textContent,/已启用/);
 assert.match(e.feedback.textContent,/结果未知/);assert.match(e.status.textContent,/batch-0000000000000001.*attempted_unknown.*unknown/);
 e.automatic.checked=true;await p.select('beta');assert.equal(e.automatic.checked,false);
 assert.match(e['automatic-status'].textContent,/已停用/);assert.equal(e.delay.value,'60000');assert(!e.status.textContent.includes('batch-'));
 e.verify.handlers.click();await flush();assert.equal(p.messages.at(-1).project_ref,'beta');
 const shown=Object.values(e).map(x=>x.textContent).join('\n');
 assert(!shown.includes(CHAT));assert(!shown.includes('private-generation'));assert(!shown.includes('"automation"'));
});
test('explicit consent gates enable and technical failure leaves an actionable message without retry',async()=>{
 const p=popup(async m=>m.action==='enable'?{ok:false,code:'PENDING_OTHER_CHAT_DISABLE_AND_RESOLVE'}:{ok:true,projects:rows,selected:m.project_ref,state:states[m.project_ref]},OTHER);
 await flush();await p.select('alpha');const e=p.elements;
 assert.match(e.destination.textContent,/另一个/);
 e.enable.handlers.click();await flush();assert(!p.messages.some(m=>m.action==='enable'));
 e.automatic.checked=true;e.enable.handlers.click();await flush();
 assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
 assert.match(e.feedback.textContent,/原 Chat.*停用/);assert.match(e['automatic-status'].textContent,/未确认/);assert.match(e.status.textContent,/PENDING_OTHER_CHAT/);
});
test('a late status response never renders under a different project selection',async()=>{
 let resolve;const p=popup(async m=>m.project_ref==='alpha'?new Promise(r=>resolve=r):{ok:true,projects:rows});await flush();
 p.elements.project.value='alpha';p.elements.project.handlers.change();await flush();assert(p.elements.project.disabled);
 p.elements.project.value='beta';resolve({ok:true,projects:rows,selected:'alpha',state:states.alpha});await flush();
 assert.equal(p.elements.project.value,'beta');assert(!p.elements.status.textContent.includes('batch-'));assert(!p.elements['automatic-status'].textContent.includes('已启用'));
});
