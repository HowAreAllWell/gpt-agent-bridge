import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {notice} from '../extension/policy.js';
import {CHAT,OTHER} from './harness.js';
const html=fs.readFileSync(new URL('../extension/popup.html',import.meta.url),'utf8');
const source=fs.readFileSync(new URL('../extension/popup.js',import.meta.url),'utf8').replace(/^import .*;\n/,'');
const flush=async()=>{for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));};
function popup(send, url=CHAT, options={}) {
 const elements={};
 for(const [,id] of html.matchAll(/id="([^"]+)"/g)) elements[id]={value:id==='delay'?'0':'',textContent:'',disabled:false,checked:false,options:[],handlers:{},addEventListener(k,f){this.handlers[k]=f;},replaceChildren(...options){this.options=options;this.value=options[0]?.value || '';},add(option){this.options.push(option);}};
 const messages=[];
 vm.runInNewContext(source,{document:{getElementById:id=>elements[id]},Option:function(text,value){return {text,value};},notice,
  setTimeout:options.clock?.setTimeout || setTimeout,clearTimeout:options.clock?.clearTimeout || clearTimeout,
  chrome:{tabs:{query:options.query || (async()=>[{url}])},runtime:{sendMessage:async m=>{messages.push(m);return send(m);}}}});
 return {elements,messages,async select(ref){elements.project.value=ref;elements.project.handlers.change();await flush();}};
}
function clock() {
 let now=0,id=0;const timers=new Map();
 return {
  setTimeout(fn,ms){timers.set(++id,{fn,at:now+ms});return id;},clearTimeout(id){timers.delete(id);},
  async advance(ms){now+=ms;for(const [id,t] of [...timers])if(t.at<=now){timers.delete(id);t.fn();}await flush();},
  get pending(){return timers.size;}
 };
}
const rows=[{project_ref:'alpha',root:'/synthetic/a',available:true},{project_ref:'beta',root:'/synthetic/b',available:true}];
const states={alpha:{binding:{project:'alpha',route:CHAT,tabId:77,generation:'private-generation'},events:[],automation:{enabled:true,route:CHAT,delayMs:0,error:null,deliveries:[{batch_ref:'batch-0000000000000001',route:CHAT,status:'attempted_unknown',code:'COMMIT_API_UNKNOWN_REBIND',outcome:'unknown'}]}},beta:{binding:{project:'beta',route:CHAT},events:[],automation:{enabled:false,route:CHAT,delayMs:60000,error:null,deliveries:[]}}};
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
test('consent and busy gate enable; definitive refusal preserves receiver, diagnostics and project for status refresh',async()=>{
 let resolve;
 const p=popup(async m=>m.action==='enable'?new Promise(r=>resolve=r):{ok:true,projects:rows,selected:m.project_ref,state:states[m.project_ref]},OTHER);
 await flush();await p.select('alpha');const e=p.elements;
 assert.match(e.destination.textContent,/另一个/);
 e.enable.handlers.click();await flush();assert(!p.messages.some(m=>m.action==='enable'));
 const destination=e.destination.textContent,diagnostics=e.status.textContent;
 e.automatic.checked=true;e.enable.handlers.click();await flush();
 assert.equal(e.destination.textContent,destination);assert(e.status.textContent.includes(diagnostics));
 assert.match(e.status.textContent,/操作中/);assert(e.enable.disabled);assert(e.disable.disabled);
 e.enable.handlers.click();await flush();
 assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
 resolve({ok:false,code:'RECIPIENT_SWITCH_REAL_UNKNOWN'});await flush();
 assert.match(e.destination.textContent,/上次确认.*另一个/);assert.match(e['automatic-status'].textContent,/上次确认.*本次操作未完成/);
 assert.match(e.feedback.textContent,/本次切换未完成.*旧记录保留/);assert(e.status.textContent.includes(diagnostics));
 assert.match(e.status.textContent,/RECIPIENT_SWITCH_REAL_UNKNOWN/);assert(!e.status.textContent.includes('操作中'));
 assert.equal(e.project.value,'alpha');assert(!e.project.disabled);assert(!e.enable.disabled);assert(!e.disable.disabled);
 assert.equal(e.automatic.checked,false);
 await p.select('alpha');assert.match(e.destination.textContent,/另一个/);assert(!e.destination.textContent.includes('上次确认'));
 assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
});
test('recipient consent covers unsent backlog; diagnostic bind does not claim to change recipient',async()=>{
 assert.match(html,/明确切换.*确定从未尝试发送的积压提醒可跟随/);
 assert.match(html,/已尝试或固定分组的旧记录留在原 Chat，不迁移、不重放/);assert.match(html,/仅绑定诊断页面（不改自动接收 Chat）/);
 const p=popup(async m=>({ok:true,projects:rows,selected:m.project_ref,state:{...states.beta,
   binding:{route:OTHER},automation:{...states.beta.automation,route:m.action==='enable'?OTHER:CHAT,enabled:m.action==='enable'}}}),OTHER);
 await flush();await p.select('beta');p.elements.bind.handlers.click();await flush();
 assert.match(p.elements.destination.textContent,/另一个/);
 p.elements.automatic.checked=true;p.elements.enable.handlers.click();await flush();
 assert.match(p.elements.destination.textContent,/当前 Chat/);assert.match(p.elements['automatic-status'].textContent,/已启用/);
 assert.equal(p.elements.automatic.checked,false);assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
});
for(const [code,words] of [['RECIPIENT_SWITCH_SYNTHETIC_UNKNOWN',/本次切换未完成.*原 Chat.*合成试验.*不迁移、不重发/],
 ['RECIPIENT_SWITCH_REAL_FROZEN',/缺少可核对的原 Chat 归属.*不能安全迁移.*本次切换未完成.*不要清历史或重发/],
 ['RECIPIENT_SELECTION_CHANGED',/标签或 Chat 已变化/]])test('recipient refusal explains '+code,async()=>{
 const p=popup(async m=>m.action==='enable'?{ok:false,code}:{ok:true,projects:rows,selected:m.project_ref,state:states[m.project_ref]});
 await flush();await p.select('beta');p.elements.automatic.checked=true;p.elements.enable.handlers.click();await flush();
 assert.match(p.elements.feedback.textContent,words);assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
 if(code==='RECIPIENT_SWITCH_REAL_FROZEN')assert(!/已有发送意图|固定分组/.test(p.elements.feedback.textContent));
});
test('a late status response never renders under a different project selection',async()=>{
 let resolve;const p=popup(async m=>m.project_ref==='alpha'?new Promise(r=>resolve=r):{ok:true,projects:rows});await flush();
 p.elements.project.value='alpha';p.elements.project.handlers.change();await flush();assert(p.elements.project.disabled);
 p.elements.project.value='beta';resolve({ok:true,projects:rows,selected:'alpha',state:states.alpha});await flush();
 assert.equal(p.elements.project.value,'beta');assert(!p.elements.status.textContent.includes('batch-'));assert(!p.elements['automatic-status'].textContent.includes('已启用'));
 assert(!p.elements.status.textContent.includes('操作中'));assert(!p.elements.project.disabled);
});
test('no-project enable never calls worker or replaces neutral state with fake pending or unknown',async()=>{
 const p=popup(async()=>({ok:true,projects:rows}));await flush();const e=p.elements;
 assert.equal(e.project.value,'');assert(e.enable.disabled);assert(e.disable.disabled);
 const destination=e.destination.textContent,status=e['automatic-status'].textContent,diagnostics=e.status.textContent;
 e.automatic.checked=true;e.enable.handlers.click();await flush();
 assert.equal(p.messages.length,1);assert.equal(p.messages[0].action,'status');assert(!p.messages[0].project_ref);
 assert.equal(e.feedback.textContent,'请选择本地项目。');assert.equal(e.destination.textContent,destination);
 assert.equal(e['automatic-status'].textContent,status);assert.equal(e.status.textContent,diagnostics);
 assert(!Object.values(e).some(x=>/待核对|状态未确认|结果未知/.test(x.textContent)));assert(!e.project.disabled);
});
test('one explicitly available project is selected for exactly one status read, never enable or bind',async()=>{
 const projects=[rows[0],{...rows[1],available:false}];
 const p=popup(async m=>({ok:true,projects,selected:m.project_ref,state:states[m.project_ref]}));await flush();
 assert.deepEqual(p.messages.map(m=>[m.action,m.project_ref]),[['status',undefined],['status','alpha']]);
 assert.equal(p.elements.project.value,'alpha');assert.match(p.elements.destination.textContent,/当前 Chat/);
 assert(!p.elements.enable.disabled);assert(!p.elements.project.disabled);assert(!p.elements.automatic.checked);
 await flush();assert.equal(p.messages.length,2);
});
test('empty catalog is a connection or registration hint, not proof that no projects exist',async()=>{
 const p=popup(async()=>({ok:true,projects:[]}));await flush();const e=p.elements;
 assert.equal(p.messages.length,1);assert.equal(e.project.value,'');assert.equal(e.project.options.length,1);
 assert.match(e.feedback.textContent,/未读取到可用项目.*连接和项目登记/);
 assert(!e.destination.textContent.includes('待核对'));assert(!e['automatic-status'].textContent.includes('未确认'));
 assert(!e.project.disabled);assert(e.enable.disabled);assert(e.disable.disabled);assert(!e.status.textContent.includes('操作中'));
});
test('failed automatic status read retains selected project without retrying or performing an action',async()=>{
 const p=popup(async m=>m.project_ref?Promise.reject(Error('disconnected')):{ok:true,projects:[rows[0]]});await flush();
 assert.deepEqual(p.messages.map(m=>m.action),['status','status']);assert.equal(p.elements.project.value,'alpha');
 assert.match(p.elements.feedback.textContent,/读取持久状态.*不自动重试/);assert(!p.elements.project.disabled);
 assert(!p.elements.enable.disabled);assert(!p.elements.status.textContent.includes('操作中'));
 await flush();assert.equal(p.messages.length,2);
});
test('acknowledged new receiver is shown even while old-route unknown history remains',async()=>{
 const p=popup(async m=>({ok:true,projects:rows,selected:m.project_ref,state:m.action==='enable'?
  {...states.alpha,binding:{route:OTHER},automation:{...states.alpha.automation,route:OTHER}}:states[m.project_ref]}),OTHER);
 await flush();await p.select('alpha');assert.match(p.elements.destination.textContent,/另一个/);
 p.elements.automatic.checked=true;p.elements.enable.handlers.click();await flush();
 assert.match(p.elements.destination.textContent,/当前 Chat/);assert.match(p.elements['automatic-status'].textContent,/已启用/);
 assert.match(p.elements.feedback.textContent,/结果未知.*1 条留在原 Chat/);assert.match(p.elements.status.textContent,/batch-.*attempted_unknown/);
 assert(!p.elements.status.textContent.includes('操作中'));assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
 assert(!p.elements.automatic.checked);
});
for(const failure of ['transport','API_OUTCOME_UNKNOWN','ALARM_UNKNOWN'])test('uncertain '+failure+' never claims enable succeeded or retries; status can recover',async()=>{
 const p=popup(async m=>{
  if(m.action==='enable') {if(failure==='transport')throw Error('disconnected');return {ok:false,code:failure};}
  return {ok:true,projects:rows,selected:m.project_ref,state:states[m.project_ref]};
 },OTHER);
 await flush();await p.select('beta');const e=p.elements,diagnostics=e.status.textContent;
 e.automatic.checked=true;e.enable.handlers.click();await flush();
 assert.match(e.destination.textContent,/本次无法确认/);assert.match(e['automatic-status'].textContent,/本次操作结果未知/);
 assert(!e['automatic-status'].textContent.includes('已启用'));assert.match(e.feedback.textContent,/读取持久状态.*不自动重试/);
 assert(e.status.textContent.includes(diagnostics));assert(!e.status.textContent.includes('操作中'));
 assert.equal(e.project.value,'beta');assert(!e.project.disabled);assert(!e.enable.disabled);
 await p.select('beta');assert.match(e['automatic-status'].textContent,/已停用/);
 assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
});
test('late failure cannot replace another selected project with old cached receiver or error',async()=>{
 let reject;const p=popup(async m=>m.project_ref==='alpha'?new Promise((_,r)=>reject=r):{ok:true,projects:rows});await flush();
 p.elements.project.value='alpha';p.elements.project.handlers.change();await flush();
 p.elements.project.value='beta';p.elements.project.handlers.change();reject(Error('disconnected'));await flush();
 assert.equal(p.elements.project.value,'beta');assert(!p.elements.feedback.textContent.includes('重试'));
 assert(!p.elements.destination.textContent.includes('上次确认'));assert(!p.elements.status.textContent.includes('操作中'));
 assert(!p.elements.project.disabled);
});
test('post-save STATE_CHANGED_NO_OVERWRITE is uncertain; explicit readback can show the saved receiver',async()=>{
 let state=states.beta;
 const p=popup(async m=>{
  if(m.action==='enable') {
   state={...states.beta,binding:{route:OTHER},automation:{...states.beta.automation,enabled:true,route:OTHER}};
   return {ok:false,code:'STATE_CHANGED_NO_OVERWRITE'}; // Receiver saved, later legacy-index cleanup failed.
  }
  return {ok:true,projects:rows,selected:m.project_ref,state:m.project_ref?state:undefined};
 },OTHER);
 await flush();await p.select('beta');const e=p.elements;
 e.automatic.checked=true;e.enable.handlers.click();await flush();
 assert.match(e.destination.textContent,/本次无法确认/);assert.match(e['automatic-status'].textContent,/结果未知/);
 assert(!e['automatic-status'].textContent.includes('未完成'));assert(!e.feedback.textContent.includes('切换未完成'));
 assert.match(e.feedback.textContent,/读取持久状态.*不自动重试/);assert.match(e.status.textContent,/STATE_CHANGED_NO_OVERWRITE/);
 assert.equal(e.project.value,'beta');assert(!e.project.disabled);assert(!e.status.textContent.includes('操作中'));
 await p.select('beta');assert.match(e.destination.textContent,/当前 Chat/);assert.match(e['automatic-status'].textContent,/已启用/);
 assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
});
test('unresolved optional tab query cannot hide acknowledged saved state or hold controls; late tab result is ignored',async()=>{
 const time=clock();let hold=false,resolveTab;
 const received={...states.beta,binding:{route:OTHER},automation:{...states.beta.automation,enabled:true,route:OTHER,
  deliveries:[{work_ref:'work-0000000000000002',route:OTHER,status:'received',receipt:{notices:1}}]}};
 const p=popup(async m=>({ok:true,projects:rows,selected:m.project_ref,state:m.action==='enable'?received:states[m.project_ref]}),OTHER,
  {clock:time,query:()=>hold?new Promise(r=>resolveTab=r):Promise.resolve([{url:OTHER}])});
 await flush();await p.select('beta');const e=p.elements;hold=true;
 e.automatic.checked=true;e.enable.handlers.click();await flush();assert(e.project.disabled);
 await time.advance(500);
 assert.equal(e.destination.textContent,'接收 Chat：已保存（当前标签未核对）');assert.match(e['automatic-status'].textContent,/已启用/);
 assert.match(e.status.textContent,/work-.*received.*收件匹配数：1/);assert(!e.status.textContent.includes('操作中'));
 assert(!e.project.disabled);assert(!e.enable.disabled);assert(!e.automatic.checked);assert.equal(time.pending,0);
 const shown=e.destination.textContent;resolveTab([{url:CHAT}]);await flush();assert.equal(e.destination.textContent,shown);
 assert.equal(p.messages.filter(m=>m.action==='enable').length,1);
});
for(const action of ['status','enable'])test('unresolved '+action+' releases UI as uncertain without retry; late completion cannot overwrite later same-project state',async()=>{
 const time=clock(),enabled={...states.beta,binding:{route:OTHER},automation:{...states.beta.automation,enabled:true,route:OTHER}};
 let hold=false,resolveLate,state=states.beta;
 const p=popup(async m=>{
  if(hold && m.action===action)return new Promise(r=>resolveLate=r);
  return {ok:true,projects:rows,selected:m.project_ref,state:m.project_ref?state:undefined};
 },OTHER,{clock:time});
 await flush();await p.select('beta');const e=p.elements;
 hold=true;
 if(action==='status')await p.select('beta');else {e.automatic.checked=true;e.enable.handlers.click();await flush();}
 const sent=p.messages.length;assert(e.project.disabled);assert(e.enable.disabled);
 await time.advance(59999);assert(e.project.disabled);await time.advance(1);
 assert.match(e.destination.textContent,/本次无法确认/);assert.match(e.status.textContent,/MESSAGE_RESPONSE_TIMEOUT_UNKNOWN/);
 assert.match(e.feedback.textContent,/读取持久状态.*不自动重试/);assert(!e.status.textContent.includes('操作中'));
 assert.equal(e.project.value,'beta');assert(!e.project.disabled);assert(!e.enable.disabled);assert(!e.automatic.checked);
 assert.equal(p.messages.length,sent);assert.equal(time.pending,0);
 hold=false;state=action==='status'?enabled:states.beta;await p.select('beta');
 const view=[e.destination.textContent,e['automatic-status'].textContent,e.status.textContent];
 assert.match(e['automatic-status'].textContent,action==='status'?/已启用/:/已停用/);
 resolveLate({ok:true,projects:rows,selected:'beta',state:action==='status'?states.beta:enabled});await flush();
 assert.deepEqual([e.destination.textContent,e['automatic-status'].textContent,e.status.textContent],view);
 assert.equal(p.messages.filter(m=>m.action==='enable').length,action==='enable'?1:0);
 assert.equal(p.messages.length,sent+1);assert.equal(time.pending,0);
});
