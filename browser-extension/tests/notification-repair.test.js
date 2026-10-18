import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation} from '../extension/automation.js';
import {completionId,completionMessage,mergedNotice,noticeItem} from '../extension/completion-policy.js';
import {harness,fixture,DOMEvent,CHAT} from './harness.js';

const epoch='a'.repeat(32),sha='b'.repeat(64);
const id=(kind,n)=>kind+'-'+n.toString(16).padStart(16,'0');
const batch=n=>({batch_ref:id('batch',n),project_ref:'gpt-agent-bridge',sequence:n,
 ready_at:5,requested:1,not_submitted:0,members:[{work_ref:id('work',n),state:'agent_turn_settled',
 result_class:'result_ready',classification_report_status:'readable',report_status:'readable',report_sha256:sha}]});
const rows=h=>h.state.automation.deliveries;
const stop=h=>h.page.add(h.page.footer,'button',{type:'button','aria-label':'Stop'});
async function setup(options={}) {
 const h=harness(options);h.events=[];
 h.io.exactTabs=async route=>route===h.page.location.href?[{id:1,incognito:false}]:[];
 h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.io.feed=async q=>{
  const events=h.events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)).slice(0,16);
  return {epoch,events:structuredClone(events),cursor:Math.max(q?.after||0,...events.map(e=>e.sequence),0),latest:Math.max(...h.events.map(e=>e.sequence),0)};
 };
 const page=h.io.page;h.io.page=async(b,r)=>{const result=await page(b,r);if(r.op==='commit')h.commitResult=result;return result;};
 h.worker=new Automation(h.io);await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;
 h.tick=()=>h.worker.run('tick');h.wake=()=>{h.worker=new Automation(h.io);return h.tick();};
 // Check every persisted state, including outer catch saves, using the real loader.
 h.writeHook=async s=>new Automation({boot:async()=>s.boot,read:async()=>structuredClone(s)}).load();
 return h;
}
async function rollbackGroup() {
 const h=await setup();h.events=[batch(1),batch(2)];let busy;
 h.page.onYield=()=>{if(!busy)busy=stop(h);};await h.tick();
 assert.deepEqual(rows(h),[]);assert.equal(h.commitResult.stage,'rolled_back_before_click');
 assert.deepEqual(h.state.automation.consumed,[id('batch',1),id('batch',2)]);assert.equal(h.page.clicks,0);
 h.page.onYield=()=>{};h.page.footer.removeChild(busy);h.page.clock.now+=2100;return h;
}
test('repair: rolled-back group keeps only suppression IDs and never rechecks or replays after worker reload',async()=>{
 const h=await rollbackGroup(),feed=h.io.feed,checks=[];
 h.io.feed=async q=>{if(q?.check)checks.push(q.check);return feed(q);};
 await h.wake();await h.wake();await h.worker.load();
 assert.deepEqual(checks,[]);assert.deepEqual(rows(h),[]);assert.equal(h.page.clicks,0);
 await h.worker.run('disable');await h.wake();assert.equal(h.state.automation.enabled,false);
 assert.deepEqual(h.state.automation.consumed,[id('batch',1),id('batch',2)]);
});
test('repair: independent completion sends once without joining or replaying retired group identities',async()=>{
 const h=await rollbackGroup(),feed=h.io.feed,checks=[];
 h.io.feed=async q=>{if(q?.check)checks.push(q.check);return feed(q);};
 h.events.push(batch(3));await h.wake();assert.equal(h.page.clicks,1);assert.deepEqual(checks,[id('batch',3)]);
 assert.deepEqual(rows(h),[]);assert.equal(h.page.editor.textContent,completionMessage({...batch(3),noticeVersion:2}));
 await h.wake();assert.equal(h.page.clicks,1);assert.deepEqual(checks,[id('batch',3)]);assert.equal(h.state.automation.cursor,3);
});
test('repair: never-attempted multi-event refresh abort preserves the surviving active event',async()=>{
 const h=await setup(),feed=h.io.feed;h.events=[batch(1),batch(2)];
 let rejectRead,entered;const atRead=new Promise(resolve=>entered=resolve);
 h.io.feed=async q=>{
  if(q?.check===id('batch',1))return {epoch,cursor:2,latest:2,events:[],check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}};
  if(q?.check===id('batch',2)){entered();return new Promise((_,reject)=>rejectRead=reject);}
  return feed(q);
 };
 const running=h.tick();await atRead;await new Automation(h.io).load();
 assert.deepEqual(rows(h).map(e=>e.status),['queued','queued']);assert.equal(h.page.clicks,0);
 rejectRead(Error('ABORTED'));await running;await h.worker.load();
 assert.equal(h.state.automation.error,'ABORTED');assert.equal(rows(h).length,1);
 assert.equal(rows(h)[0].batch_ref,id('batch',2));assert.deepEqual(h.state.automation.consumed,[id('batch',1)]);
 h.io.feed=feed;await h.wake();await h.wake();assert.equal(h.page.clicks,1);assert.deepEqual(rows(h),[]);
 assert.equal(h.page.editor.textContent,completionMessage({...batch(2),noticeVersion:2}));
});

test('repair: ACKed preparation refusal retires the unresolved clicked offer and a normal poll requires a fresh choice',async()=>{
 for(const choice of ['append','ignore']) {
  const h=await setup(),p=h.page;p.editor.textContent='';const original=p.add(p.editor,'p');original.textContent='保留原有中文草稿';p.renderSend();
  h.events=[batch(1),batch(2)];await h.tick();const old=p.choiceButtons()[choice==='append'?0:1];
  let stale=false,prepared,entered,release,finished,result,messages=0;
  const saving=new Promise(r=>entered=r),gate=new Promise(r=>release=r),done=new Promise(r=>finished=r),write=h.io.write;
  h.io.write=async(k,s)=>{if(s.automation.deliveries.length===2 && s.automation.deliveries.every(e=>e.code==='DRAFT_CHOICE_STALE')){entered();await gate;}return write(k,s);};
  // Invalidate the clicked page token, not the user draft. The serialized real
  // adapter must reject the worker's now-stale request before issuing a lease.
  h.pageHook=async(b,r)=>{if(r.op==='draft_prepare'&&!stale){stale=true;p.window.__bridgeDraftChoiceV1.token='ffffffff-ffff-ffff-ffff-ffffffffffff';}};
  const page=h.io.page;h.io.page=async(b,r)=>{const result=await page(b,r);if(r.op==='draft_prepare')prepared=result;return result;};
  p.onPageMessage=m=>{
   messages++;
   const operation=h.worker.run('draft_choice',{token:m.token,source:{tabId:1,documentId:'doc-1',url:CHAT}})
    .then(()=>{result=true;},()=>{result=false;});
   if(messages===1){operation.then(finished);return new Promise(()=>{});}
   return operation;
  };
  p.userClick(old);await saving;
  assert.deepEqual(prepared,{ok:false,code:'DRAFT_CHOICE_STALE',documentId:'doc-1'});
  assert.equal(p.editor.textContent,original.textContent);assert.equal(p.clicks,0);assert.deepEqual(h.state.automation.consumed,[]);
  assert.equal(p.window.__bridgeDraftChoiceV1.clicked,true);assert.equal(p.window.__bridgeDraftChoiceV1.host.isConnected,false);
  assert(!h.calls.some(c=>c.op==='draft_dismiss'));assert(!h.calls.some(c=>c.op==='draft_commit'));
  release();await done;assert.equal(result,false);assert.equal(p.window.__bridgeDraftChoiceV1===undefined,true);
  assert.equal(h.calls.filter(c=>c.op==='draft_dismiss').length,1);
  assert.equal(rows(h).length,2);assert(rows(h).every(e=>e.status==='waiting'&&!Object.hasOwn(e,'intentAt')));
  assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.editor.textContent,original.textContent);assert.equal(p.clicks,0);
  h.pageHook=async()=>{};h.io.write=write;await h.wake();
  const next=p.choiceButtons()[choice==='append'?0:1];assert.notEqual(next,old);assert.equal(p.window.__bridgeDraftChoiceV1.host.isConnected,true);
  assert.equal(messages,1);p.userClick(old);assert.equal(messages,1);p.userClick(next);
  for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));
  assert.equal(result,true);assert.equal(messages,2);assert.equal(p.clicks,0);assert.equal(p.editor.childNodes[0],original);
  assert.equal(original.textContent,'保留原有中文草稿');assert.equal(p.editor.childNodes.length,choice==='append'?2:1);
  if(choice==='append')assert.equal(p.editor.lastChild.textContent,mergedNotice(h.events.map(noticeItem)));
  assert.deepEqual(rows(h),[]);assert.deepEqual(h.state.automation.consumed,[id('batch',1),id('batch',2)]);
  const after=p.editor.cloneNode(true);await h.wake();assert(p.editor.isEqualNode(after));
 }
});

test('repair: uncertain preparation, waiting-save or dismissal never releases an unresolved clicked offer',async()=>{
 for(const fault of ['wrong document','extra field','missing result','missing ok','unknown effect code','API error','save refused','save ACK lost','dismiss ACK lost']) {
  const h=await setup(),p=h.page;p.editor.textContent='';p.add(p.editor,'p').textContent='draft';p.renderSend();h.events=[batch(1)];await h.tick();
  const page=h.io.page,write=h.io.write;let finished;
  const done=new Promise(r=>finished=r);
  p.onPageMessage=m=>{h.worker.run('draft_choice',{token:m.token,source:{tabId:1,documentId:'doc-1',url:CHAT}}).then(finished,finished);return new Promise(()=>{});};
  h.io.page=async(b,r)=>{
   if(r.op==='draft_dismiss'&&fault==='dismiss ACK lost')throw Error('ACK_LOST');
   if(r.op!=='draft_prepare')return page(b,r);
   if(fault==='API error')throw Error('API_OUTCOME_UNKNOWN');
   if(fault==='missing result')return null;
   const result={ok:false,code:'BUSY_STOP_PRESENT',documentId:b.documentId};
   if(fault==='wrong document')result.documentId='wrong';
   if(fault==='extra field')result.extra=true;
   if(fault==='missing ok')delete result.ok;
   if(fault==='unknown effect code')result.code='DRAFT_APPEND_OUTCOME_UNKNOWN';
   return result;
  };
  h.io.write=async(k,s)=>{
   if(s.automation.deliveries[0]?.code==='BUSY_STOP_PRESENT'&&fault.startsWith('save')) {
    if(fault==='save ACK lost')await write(k,s);throw Error('SAVE_UNKNOWN');
   }
   return write(k,s);
  };
  p.userClick(p.choiceButtons()[0]);await done;
  assert.equal(p.window.__bridgeDraftChoiceV1.clicked,true,fault);assert.equal(p.window.__bridgeDraftChoiceV1.host.isConnected,false,fault);
  assert(!h.calls.some(c=>c.op==='draft_commit'),fault);assert.deepEqual(h.state.automation.consumed,[],fault);
  assert.equal(rows(h).length,1,fault);assert(!Object.hasOwn(rows(h)[0],'intentAt'),fault);
  h.io.page=page;h.io.write=write;await h.wake();
  assert.equal(p.window.__bridgeDraftChoiceV1.host.isConnected,false,fault);
  assert.equal(rows(h)[0].code,'DRAFT_CHOICE_UNCONFIRMED',fault);assert.equal(p.editor.textContent,'draft',fault);assert.equal(p.clicks,0,fault);
 }
});

test('repair: exact no-mutation choice refusal restores the group, retires the old token, and requires a new click',async()=>{
 for(const code of ['BUSY_STOP_PRESENT','DRAFT_CHOICE_STALE','DRAFT_CHANGED']) {
 const h=await setup(),p=h.page;p.editor.textContent='';p.add(p.editor,'p').textContent='保留草稿';p.renderSend();
 h.events=[batch(1),batch(2)];const page=h.io.page;let refused=false,result;
 p.onPageMessage=async m=>{
  try {await h.worker.run('draft_choice',{token:m.token,source:{tabId:1,documentId:'doc-1',url:CHAT}});result=true;}
  catch {result=false;}
 };
 h.io.page=async(b,r)=>{
  if(r.op==='draft_commit'&&!refused){refused=true;return {ok:true,stage:'blocked_before_mutation',code,documentId:b.documentId};}
  return page(b,r);
 };
 await h.tick();const old=p.choiceButtons()[0];p.userClick(old);
 for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));
 assert.equal(result,false);assert.equal(p.editor.textContent,'保留草稿');assert.equal(p.clicks,0);
 assert.deepEqual(h.state.automation.consumed,[]);assert.equal(rows(h).length,2);
 assert(rows(h).every(e=>e.status==='waiting'&&!Object.hasOwn(e,'intentAt')&&!Object.hasOwn(e,'merge')&&!Object.hasOwn(e,'mergedInto')));
 assert.equal(p.choiceButtons().length,0);await h.wake();const next=p.choiceButtons()[0];assert.notEqual(next,old);
 p.userClick(old);assert.equal(p.editor.textContent,'保留草稿');p.userClick(next);
 for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));
 assert.equal(result,true);assert.equal(p.clicks,0);assert.deepEqual(rows(h),[]);
 assert.deepEqual(h.state.automation.consumed,[id('batch',1),id('batch',2)]);
 const after=p.editor.textContent;await h.wake();assert.equal(p.editor.textContent,after);
 }
});

test('repair: ambiguous, wrong-document and unapproved choice results never release consumed identities',async()=>{
 const variants=[null,{ok:false,code:'BUSY_STOP_PRESENT'},
  {ok:true,stage:'blocked_before_mutation',code:'BUSY_STOP_PRESENT',documentId:'wrong'},
  {ok:true,stage:'blocked_before_mutation',code:'BUSY_STOP_PRESENT',extra:true},
  {ok:true,stage:'blocked_before_mutation',code:'DRAFT_APPEND_OUTCOME_UNKNOWN'},'lost append ACK','lost dismiss ACK'];
 for(const variant of variants) {
  const h=await setup(),p=h.page;p.editor.textContent='';p.add(p.editor,'p').textContent='draft';p.renderSend();h.events=[batch(1)];
  const page=h.io.page;
  p.onPageMessage=async m=>{try{await h.worker.run('draft_choice',{token:m.token,source:{tabId:1,documentId:'doc-1',url:CHAT}});}catch{}};
  h.io.page=async(b,r)=>{
   if(r.op==='draft_dismiss'&&variant==='lost dismiss ACK')throw Error('ACK_LOST');
   if(r.op!=='draft_commit')return page(b,r);
   if(variant==='lost append ACK'){await page(b,r);throw Error('ACK_LOST');}
   if(variant==='lost dismiss ACK')return {ok:true,stage:'blocked_before_mutation',code:'BUSY_STOP_PRESENT',documentId:b.documentId};
   return variant&&{documentId:b.documentId,...variant};
  };
  await h.tick();p.userClick(p.choiceButtons()[0]);for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));
  assert.deepEqual(rows(h),[]);assert.deepEqual(h.state.automation.consumed,[id('batch',1)]);assert.equal(p.clicks,0);
  const after=p.editor.textContent;h.io.page=page;await h.wake();assert.equal(p.editor.textContent,after);
  assert.equal(p.choiceButtons().length,0);
 }
});

test('repair: recovery storage refusal retires the clicked token without another save or automatic retry',async()=>{
 const h=await setup(),p=h.page;p.editor.textContent='';p.add(p.editor,'p').textContent='draft';p.renderSend();h.events=[batch(1)];
 const page=h.io.page;let recoveries=0,result;
 p.onPageMessage=async m=>{try{await h.worker.run('draft_choice',{token:m.token,source:{tabId:1,documentId:'doc-1',url:CHAT}});}catch(e){result=e.message;}};
 h.io.page=async(b,r)=>r.op==='draft_commit'?{ok:true,stage:'blocked_before_mutation',code:'BUSY_STOP_PRESENT',documentId:b.documentId}:page(b,r);
 await h.tick();
 h.writeHook=s=>{if(!s.automation.consumed.length){recoveries++;throw Error('STATE_CHANGED_NO_OVERWRITE');}};
 p.userClick(p.choiceButtons()[0]);for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));
 assert.equal(result,'STATE_CHANGED_NO_OVERWRITE');assert.equal(recoveries,1);
 assert.equal(p.choiceButtons().length,0);assert.equal(p.editor.textContent,'draft');assert.equal(p.clicks,0);
 assert.deepEqual(h.state.automation.consumed,[id('batch',1)]);assert.deepEqual(rows(h),[]);
 h.writeHook=()=>{};await h.wake();assert.equal(p.choiceButtons().length,0);assert.equal(p.editor.textContent,'draft');
});

function cloneTree(p,parent,node) {
 if(node.nodeType===3){const text=p.doc.createTextNode(node.nodeValue);parent.appendChild(text);return text;}
 const copy=p.add(parent,node.tagName,{...node.attrs});for(const child of node.childNodes)cloneTree(p,copy,child);return copy;
}
for(const part of ['editor','body','footer'])for(const when of ['before-withdraw','after-withdraw'])
test(`repair: ${part} replacement ${when} cannot authorize rollback or retry`,async()=>{
 const h=await setup();h.events=[batch(1)];let n=0,replacement,originalText;
 h.page.onYield=()=>{
  n++;if(n===1){originalText=h.page.editor.textContent;stop(h);}
  if(n!==(when==='before-withdraw'?1:2))return;
  const old=h.page[part],parent=old.parentNode;replacement=cloneTree(h.page,parent,old);parent.removeChild(old);
  const live=part==='editor'?replacement:replacement.querySelectorAll('[data-composer-markdown]')[0];
  live.textContent=originalText; // Host can preserve/restage its own copied text.
 };
 await h.tick();assert.deepEqual(rows(h),[]);assert(h.state.automation.consumed.includes(id('batch',1)));assert.equal(h.page.clicks,0);
 assert.notEqual(h.commitResult?.stage,'rolled_back_before_click');
 const live=part==='editor'?replacement:replacement.querySelectorAll('[data-composer-markdown]')[0];
 assert.equal(live.textContent,originalText);
 assert.equal(h.page.editor.textContent,when==='before-withdraw'?originalText:'');
 h.page.onYield=()=>{};await h.wake();assert.equal(h.page.clicks,0);
});

test('repair: current editor ownership check throwing cannot withdraw or authorize retry',async()=>{
 const h=await setup();h.events=[batch(1)];h.page.onYield=()=>{stop(h);h.page.doc.contains=()=>{throw Error('NO_DOM_EVIDENCE');};};
 await h.tick();assert.deepEqual(rows(h),[]);assert(h.state.automation.consumed.includes(id('batch',1)));assert(h.state.automation.consumed.includes(id('batch',1)));
 assert.equal(h.page.editor.textContent,completionMessage({...batch(1),noticeVersion:2}));assert.equal(h.page.clicks,0);
});

for(const mode of ['click','nested-click','submit','request-submit','enter','cancelled-click','stopped-at-document','missing-path','incomplete-path','throwing-path','no-busy-click','synchronous-input-click','during-withdraw-submit'])
test('repair: observed external submission stays unknown without withdrawal or another click: '+mode,async()=>{
 const h=await setup({owner:true});h.events=[batch(1),batch(2)];let n=0,externalText;
 const interfere=()=>{
  externalText ||= h.page.editor.textContent;
  if(mode==='submit')h.page.owner.dispatchEvent(new DOMEvent('submit',{bubbles:true,cancelable:true}));
  else if(mode==='request-submit'||mode==='during-withdraw-submit')h.page.owner.requestSubmit();
  else if(mode==='enter')h.page.button.dispatchEvent(new DOMEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
  else if(['missing-path','incomplete-path','throwing-path'].includes(mode)) {
   const e=new DOMEvent('click',{bubbles:true,cancelable:true});
   e.composedPath=mode==='missing-path'?undefined:mode==='incomplete-path'?()=>[h.page.window]:()=>{throw Error('NO_PATH');};h.page.button.dispatchEvent(e);
  } else if(mode==='nested-click')h.page.add(h.page.button,'span').dispatchEvent(new DOMEvent('click',{bubbles:true,cancelable:true}));
  else h.page.button.click();
 };
 if(mode==='cancelled-click')h.page.doc.addEventListener('click',e=>e.preventDefault(),true);
 if(mode==='stopped-at-document')h.page.doc.addEventListener('click',e=>e.stopImmediatePropagation(),true);
 if(mode==='synchronous-input-click')h.page.editor.addEventListener('input',e=>{
  if(e.inputType==='insertText'){h.page.renderSend();interfere();}
 });
 h.page.onYield=()=>{
  n++;if(mode==='during-withdraw-submit') {if(n===1){externalText=h.page.editor.textContent;stop(h);}if(n===2)interfere();return;}
  if(n!==1)return;
  if(mode!=='synchronous-input-click')interfere();if(mode!=='no-busy-click')stop(h);
 };
 await h.tick();assert.deepEqual(rows(h),[]);
 assert.deepEqual(h.state.automation.consumed,[id('batch',1),id('batch',2)]);assert.equal(h.commitResult.code,'SUBMISSION_INTERFERENCE_OUTCOME_UNKNOWN');
 if(mode!=='during-withdraw-submit')assert.equal(h.page.editor.textContent,externalText);
 await assert.rejects(h.worker.run('close_delivery',{id:id('batch',1)}),/UNKNOWN_ACTION/);
 const clicks=h.page.clicks;h.page.onYield=()=>{};
 // Host settles and clears after its submission; absence of a receipt is not unsent evidence.
 h.page.editor.textContent='';h.page.renderVoice();
 for(const node of h.page.footer.querySelectorAll('[aria-label="Stop"]'))node.parentNode.removeChild(node);
 await h.wake();assert.equal(h.page.clicks,clicks);assert.deepEqual(rows(h),[]);
 const frozen=structuredClone(rows(h));
 await h.wake();assert.deepEqual(rows(h),frozen);assert.equal(h.page.clicks,clicks);
 assert.equal(mergedNotice([batch(1),batch(2)].map(noticeItem)),externalText);
});

test('repair: no-form Send click is also observed before the host clears its draft',async()=>{
 const h=await setup();h.events=[batch(1)];let once=true;
 h.page.onYield=()=>{if(once){once=false;h.page.button.click();stop(h);}};
 await h.tick();assert.equal(h.page.clicks,1);assert(h.state.automation.consumed.includes(id('batch',1)));
 assert.equal(h.page.editor.textContent,completionMessage({...batch(1),noticeVersion:2}));await h.wake();assert.equal(h.page.clicks,1);
});

for(const mode of ['missing-remove','registration-throws'])test('repair: submission guard unavailable blocks before mutation: '+mode,async()=>{
 const h=await setup();h.events=[batch(1)];
 if(mode==='missing-remove')h.page.window.removeEventListener=undefined;
 else {const add=h.page.window.addEventListener.bind(h.page.window);h.page.window.addEventListener=(type,...args)=>{if(type==='submit')throw Error('NO_GUARD');return add(type,...args);};}
 await h.tick();assert.equal(rows(h)[0].status,'waiting');assert.equal(rows(h)[0].intentAt,undefined);assert.equal(h.commitResult.stage,'blocked_before_mutation');
 assert.equal(rows(h)[0].code,'SUBMISSION_GUARD_UNAVAILABLE');assert.equal(h.page.editor.textContent,'');assert.equal(h.page.clicks,0);
});

test('fixture: capture, target, bubble order and detached nodes follow event ancestry',()=>{
 const p=fixture(undefined,{owner:true}),order=[];
 for(const [name,node] of [['window',p.window],['document',p.doc],['body',p.body],['button',p.button]]) {
  node.addEventListener('click',e=>order.push(name+':capture:'+e.eventPhase),true);
  node.addEventListener('click',e=>order.push(name+':bubble:'+e.eventPhase));
 }
 p.button.click();assert.deepEqual(order,['window:capture:1','document:capture:1','body:capture:1','button:capture:2','button:bubble:2','body:bubble:3','document:bubble:3','window:bubble:3']);
 order.length=0;p.footer.removeChild(p.button);p.button.click();assert.deepEqual(order,['button:capture:2','button:bubble:2']);
});

test('fixture: click cancellation suppresses default submit, and stopPropagation preserves same-target listeners',()=>{
 const p=fixture(undefined,{owner:true});p.editor.textContent='draft';p.renderSend();let submits=0;const observed=[];
 p.owner.addEventListener('submit',()=>submits++);
 const cancel=e=>e.preventDefault();p.button.addEventListener('click',cancel);
 p.button.click();assert.equal(submits,0);p.button.removeEventListener('click',cancel);p.button.click();assert.equal(submits,1);
 p.button.addEventListener('click',e=>{observed.push('first');e.stopPropagation();});
 p.button.addEventListener('click',()=>observed.push('second'));p.doc.addEventListener('click',()=>observed.push('document'));
 p.button.click();assert.deepEqual(observed,['first','second']);assert.equal(submits,2);
});

test('repair: temporary submission listeners are removed after both click and safe rollback',async()=>{
 for(const busy of [false,true]) {
  const h=await setup();h.events=[batch(1)];let once=true;
  if(busy)h.page.onYield=()=>{if(once){once=false;stop(h);}};
  await h.tick();
  for(const type of ['click','submit','keydown'])assert.equal(h.page.window.listeners[type].length,0);
  assert.equal(h.commitResult.stage,busy?'rolled_back_before_click':'clicked');assert.deepEqual(rows(h),[]);
 }
});
