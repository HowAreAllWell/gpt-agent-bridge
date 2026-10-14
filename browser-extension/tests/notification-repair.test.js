import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation} from '../extension/automation.js';
import {completionId,completionMessage} from '../extension/completion-policy.js';
import {harness,fixture,DOMEvent,CHAT} from './harness.js';
import {messageFixture} from './receipt-fixture.js';

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
 h.io.receipt=async()=>({ok:true,scope:'chat-user-message-v1',notices:0,replies:0,draft:false,tooMany:false});
 h.io.feed=async q=>{
  const events=h.events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)).slice(0,16);
  return {epoch,events:structuredClone(events),cursor:Math.max(q?.after||0,...events.map(e=>e.sequence),0),latest:Math.max(...h.events.map(e=>e.sequence),0)};
 };
 h.worker=new Automation(h.io);await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;
 h.tick=()=>h.worker.run('tick');h.wake=()=>{h.worker=new Automation(h.io);return h.tick();};
 // Check every persisted state, including outer catch saves, using the real loader.
 h.writeHook=async s=>new Automation({boot:async()=>s.boot,read:async()=>structuredClone(s)}).load();
 return h;
}
async function rollbackGroup() {
 const h=await setup();h.events=[batch(1),batch(2)];let busy;
 h.page.onYield=()=>{if(!busy)busy=stop(h);};await h.tick();
 assert.deepEqual(rows(h).map(e=>e.status),['waiting','waiting']);assert.equal(h.page.clicks,0);
 h.page.onYield=()=>{};h.page.footer.removeChild(busy);h.page.clock.now+=2100;return h;
}

for(const first of ['identity-lost','sha-changed','epoch-changed','temporary','readable'])
for(const failure of ['transport','abort','invalid-feed','membership'])
test(`repair: fixed group ${first} then ${failure} remains loadable and disableable`,async()=>{
 const h=await rollbackGroup(),feed=h.io.feed,fixed=completionMessage(rows(h)[0]),seen=[];
 h.io.feed=async q=>{
  if(q?.check)seen.push(q.check);
  if(q?.check===id('batch',1)) {
   if(first==='identity-lost')return {epoch,cursor:2,latest:2,events:[],check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}};
   if(first==='epoch-changed')return {epoch:'c'.repeat(32),cursor:0,reset:true,events:[]};
   if(first==='temporary')return {epoch,cursor:2,latest:2,events:[]};
   const f=await feed(q);if(first==='sha-changed')f.events[0].members[0].report_sha256='d'.repeat(64);return f;
  }
  if(q?.check===id('batch',2)) {
   if(failure==='transport')throw Error('BRIDGE_FEED_UNAVAILABLE');
   if(failure==='abort')throw Object.assign(Error('ABORTED'),{name:'AbortError'});
   if(failure==='invalid-feed')return {};
   const f=await feed(q);f.events[0].members[0].work_ref=id('work',99);return f;
  }
  return feed(q);
 };
 await h.wake();assert.deepEqual(seen,[id('batch',1),id('batch',2)]);
 const status=['identity-lost','sha-changed','epoch-changed'].includes(first)?'unavailable':'waiting';
 assert.deepEqual(rows(h).map(e=>e.status),[status,status]);assert.equal(completionMessage(rows(h)[0]),fixed);
 assert.equal(h.state.automation.error,{transport:'BRIDGE_FEED_UNAVAILABLE',abort:'ABORTED','invalid-feed':'FEED_INVALID',membership:'BATCH_MEMBERSHIP_CHANGED'}[failure]);
 h.io.feed=feed;await h.worker.load();await h.worker.run('disable');await h.wake();assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.enabled,false);
});

test('repair: worker interruption during second read never persists the first staged change',async()=>{
 const h=await rollbackGroup(),feed=h.io.feed;let rejectRead,entered;
 const atRead=new Promise(resolve=>entered=resolve);
 h.io.feed=async q=>{
  if(q?.check===id('batch',1))return {epoch,cursor:2,latest:2,events:[],check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}};
  if(q?.check===id('batch',2)){entered();return new Promise((_,reject)=>rejectRead=reject);}
  return feed(q);
 };
 const running=h.tick();await atRead;
 const restored=new Automation(h.io);await restored.load();
 assert.deepEqual(rows(h).map(e=>e.status),['waiting','waiting']);
 rejectRead(Error('ABORTED'));await running;await restored.load();
 assert.deepEqual(rows(h).map(e=>e.status),['unavailable','unavailable']);
});

test('repair: lost acknowledgement of exceptional group save leaves one consistent terminal group',async()=>{
 const h=await rollbackGroup(),feed=h.io.feed,write=h.io.write;
 h.io.feed=async q=>{
  if(q?.check===id('batch',1))return {epoch,cursor:2,latest:2,events:[],check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}};
  if(q?.check===id('batch',2))throw Error('BRIDGE_FEED_UNAVAILABLE');return feed(q);
 };
 h.io.write=async(k,s)=>{await write(k,s);if(s.automation.error==='BRIDGE_FEED_UNAVAILABLE')throw Error('ACK_LOST');};
 await assert.rejects(h.tick(),/ACK_LOST/);await h.worker.load();
 assert.deepEqual(rows(h).map(e=>e.status),['unavailable','unavailable']);assert.equal(h.page.clicks,0);
});

test('repair: exact busy rollback still retries the same fixed group once after recovery',async()=>{
 const h=await rollbackGroup(),before=rows(h),fixed=completionMessage(before[0]);h.events.push(batch(3));
 await h.wake();assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,fixed);
 assert.deepEqual(rows(h)[0].merge,before[0].merge);assert.equal(rows(h)[2].intentAt,undefined);
 await h.wake();assert.equal(h.page.clicks,1);
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
 await h.tick();assert.equal(rows(h)[0].status,'attempted_unknown');assert.equal(h.page.clicks,0);
 assert.notEqual(rows(h)[0].outcome,'rolled_back_before_click');
 const live=part==='editor'?replacement:replacement.querySelectorAll('[data-composer-markdown]')[0];
 assert.equal(live.textContent,originalText);
 assert.equal(h.page.editor.textContent,when==='before-withdraw'?originalText:'');
 h.page.onYield=()=>{};await h.wake();assert.equal(h.page.clicks,0);
});

test('repair: current editor ownership check throwing cannot withdraw or authorize retry',async()=>{
 const h=await setup();h.events=[batch(1)];h.page.onYield=()=>{stop(h);h.page.doc.contains=()=>{throw Error('NO_DOM_EVIDENCE');};};
 await h.tick();assert.equal(rows(h)[0].status,'attempted_unknown');assert.equal(rows(h)[0].outcome,'unknown');
 assert.equal(h.page.editor.textContent,completionMessage(rows(h)[0]));assert.equal(h.page.clicks,0);
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
 await h.tick();assert.deepEqual(rows(h).map(e=>e.status),['attempted_unknown','attempted_unknown']);
 assert(rows(h).every(e=>e.outcome==='unknown'&&e.code==='SUBMISSION_INTERFERENCE_OUTCOME_UNKNOWN'));
 if(mode!=='during-withdraw-submit')assert.equal(h.page.editor.textContent,externalText);
 await assert.rejects(h.worker.run('close_delivery',{id:rows(h)[0].batch_ref}),/CLOSE_REQUIRES_PRECLICK_EVIDENCE/);
 const clicks=h.page.clicks;h.page.onYield=()=>{};
 // Host settles and clears after its submission; absence of a receipt is not unsent evidence.
 h.page.editor.textContent='';h.page.renderVoice();
 for(const node of h.page.footer.querySelectorAll('[aria-label="Stop"]'))node.parentNode.removeChild(node);
 await h.wake();assert.equal(h.page.clicks,clicks);assert(rows(h).every(e=>e.status==='attempted_unknown'));
 const f=messageFixture(h.page);f.user(externalText);h.io.receipt=async(b,r)=>f.observe({...r,route:b.route});
 await h.wake();assert(rows(h).every(e=>e.status==='received'));assert.equal(h.page.clicks,clicks);
 assert.equal(completionMessage(rows(h)[0]),externalText);
});

test('repair: no-form Send click is also observed before the host clears its draft',async()=>{
 const h=await setup();h.events=[batch(1)];let once=true;
 h.page.onYield=()=>{if(once){once=false;h.page.button.click();stop(h);}};
 await h.tick();assert.equal(h.page.clicks,1);assert.equal(rows(h)[0].outcome,'unknown');
 assert.equal(h.page.editor.textContent,completionMessage(rows(h)[0]));await h.wake();assert.equal(h.page.clicks,1);
});

for(const mode of ['missing-remove','registration-throws'])test('repair: submission guard unavailable blocks before mutation: '+mode,async()=>{
 const h=await setup();h.events=[batch(1)];
 if(mode==='missing-remove')h.page.window.removeEventListener=undefined;
 else {const add=h.page.window.addEventListener.bind(h.page.window);h.page.window.addEventListener=(type,...args)=>{if(type==='submit')throw Error('NO_GUARD');return add(type,...args);};}
 await h.tick();assert.equal(rows(h)[0].status,'waiting');assert.equal(rows(h)[0].outcome,'blocked_before_mutation');
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

test('repair: explicit closure through a member settles the entire fixed pre-click group',async()=>{
 const h=await setup();h.events=[batch(1),batch(2)];let once=true;
 h.page.onYield=()=>{if(once){once=false;h.page.add(h.page.footer,'button',{type:'button'});}};
 await h.tick();assert(rows(h).every(e=>e.outcome==='preclick_stop'));
 const fixed=completionMessage(rows(h)[0]);
 await h.worker.run('close_delivery',{id:rows(h)[1].batch_ref});await h.worker.load();
 assert(rows(h).every(e=>e.status==='closed_before_send'));assert.equal(completionMessage(rows(h)[0]),fixed);
 await h.worker.run('disable');await h.wake();assert.equal(h.page.clicks,0);
});

test('repair: temporary submission listeners are removed after both click and safe rollback',async()=>{
 for(const busy of [false,true]) {
  const h=await setup();h.events=[batch(1)];let once=true;
  if(busy)h.page.onYield=()=>{if(once){once=false;stop(h);}};
  await h.tick();
  for(const type of ['click','submit','keydown'])assert.equal(h.page.window.listeners[type].length,0);
  assert.equal(rows(h)[0].outcome,busy?'rolled_back_before_click':'clicked');
 }
});
