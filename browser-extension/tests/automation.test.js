import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation} from '../extension/automation.js';
import {completionNotice, completionMessage, completionId, validCompletion} from '../extension/completion-policy.js';
import {harness,CHAT,OTHER} from './harness.js';
import {messageFixture} from './receipt-fixture.js';
const epoch='a'.repeat(32),sha='b'.repeat(64);
const brief=e=>completionMessage({...e,noticeVersion:2});
const event=(n=1)=>({work_ref:'work-'+String(n).padStart(16,'0'),project_ref:'gpt-agent-bridge',report_sha256:sha,
 sequence:n,ready_at:5,result_class:'result_ready',report_status:'readable'});
async function setup(delayMs=0) {
 const h=harness();let events=[],offline=false,receipt={ok:true,scope:'chat-user-message-v1',notices:0,replies:0,draft:false,tooMany:false,visibility:'hidden',focused:false};
 h.io.exactTabs=async r=>r===h.page.location.href?[{id:1,incognito:false}]:[];
 h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.io.receipt=async()=>receipt;
 h.io.feed=async q=>{if(offline)throw Error('OFFLINE');const found=events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0));
  return {epoch,events:found,cursor:Math.max(q?.after||0,...found.map(e=>e.sequence),0),latest:Math.max(...events.map(e=>e.sequence),0)};};
 h.worker=new Automation(h.io);
 await h.worker.run('enable',{delayMs});h.page.clock.now+=2100;
 return Object.assign(h,{publish(n=1){events.push(typeof n==='object'?n:event(n));},disconnect(v){offline=v;},received(){receipt={...receipt,notices:1};},
 wake(){h.worker=new Automation(h.io);return h.worker.run('tick');},tick(){return h.worker.run('tick');}});
}
test('real completion uses changed serialized adapter once and verifies on later worker wake',async()=>{
 const h=await setup();h.publish();await h.tick();
 assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,completionNotice(event().work_ref,sha));
 assert.equal(h.state.automation.deliveries[0].outcome,'clicked');
 await h.wake();assert.equal(h.page.clicks,1);h.received();await h.wake();
 assert.equal(h.state.automation.deliveries[0].status,'received');assert.equal(h.page.clicks,1);
});
test('popup absence, delay, worker replacement and network recovery preserve same work identity',async()=>{
 const h=await setup(60000);h.publish();await h.tick();assert.equal(h.page.clicks,0);
 h.disconnect(true);h.page.clock.now+=61000;await h.wake();assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.cursor,1);h.disconnect(false);await h.wake();assert.equal(h.page.clicks,1);
 await h.wake();assert.equal(h.page.clicks,1);assert.equal(h.state.automation.deliveries.length,1);
});
for(const [kind,block,unblock] of [
 ['draft',h=>h.page.edit('user draft'),h=>h.page.edit('')],
 ['IME',h=>h.page.doc.emit({type:'compositionstart',target:h.page.editor}),h=>h.page.doc.emit({type:'compositionend',target:h.page.editor})],
 ['busy',h=>h.busy=h.page.add(h.page.doc,'button',{'data-testid':'stop-button'}),h=>h.page.doc.removeChild(h.busy)]
])test('automatic wait never changes '+kind+' and resumes only before intent',async()=>{
 const h=await setup();h.publish();block(h);h.page.clock.now+=2100;await h.tick();
 assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].status,'waiting');
 unblock(h);h.page.clock.now+=2100;await h.wake();assert.equal(h.page.clicks,1);
});
test('different destination and duplicate target refuse without any send',async()=>{
 const h=await setup();h.publish();h.page.navigate(OTHER);await h.tick();assert.equal(h.page.clicks,0);
 h.io.exactTabs=async()=>[{id:1},{id:2}];await h.tick();assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.error,'TARGET_NOT_UNIQUE_OR_OPEN');
});
test('unknown commit never retries even after sleep, re-enable or new completion',async()=>{
 const h=await setup();h.publish();const original=h.io.page;
 h.io.page=async(b,r)=>{const result=await original(b,r);if(r.op==='commit')throw Error('lost acknowledgement');return result;};
 await h.tick();assert.equal(h.page.clicks,1);h.publish(2);await h.wake();assert.equal(h.page.clicks,1);
 assert.equal(h.state.automation.deliveries[0].status,'attempted_unknown');
 await h.worker.run('enable',{delayMs:0});await h.wake();assert.equal(h.page.clicks,1);
});
test('preclick stop can close only with exact evidence and retains work and outcome',async()=>{
 const h=await setup();h.publish();h.page.onYield=()=>h.page.add(h.page.footer,'button',{type:'button'});
 await h.tick();let e=h.state.automation.deliveries[0];assert.equal(e.outcome,'preclick_stop');assert.equal(h.page.clicks,0);
 await assert.rejects(h.worker.run('close_delivery',{id:event(9).work_ref}));
 await h.worker.run('close_delivery',{id:e.work_ref});e=h.state.automation.deliveries[0];
 assert.equal(e.status,'closed_before_send');assert.equal(e.code,'UNKNOWN_COMPOSER_CONTROL');assert.ok(e.intentAt);
 await h.wake();assert.equal(h.page.clicks,0);
});
test('expired report and changed sha never send; epoch restart does not revive old work',async()=>{
 const h=await setup();h.publish();const feed=h.io.feed;
 h.io.feed=async q=>q?.check?{epoch,events:[],cursor:0,latest:1,check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}}:feed(q);
 await h.tick();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].status,'unavailable');
});
test('transient or unspecified empty check recovers the same work before any intent',async()=>{
 const h=await setup();h.publish();h.publish(2);const feed=h.io.feed;let failed=true;
 h.io.feed=async q=>q?.check&&failed?{epoch,events:[],cursor:0,latest:2}:feed(q);
 await h.tick();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].status,'waiting');
 assert.equal(h.state.automation.deliveries[0].code,'REPORT_READ_TEMPORARY');
 assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
 assert.equal(h.state.automation.deliveries[1].intentAt,undefined);
 failed=false;await h.wake();assert.equal(h.page.clicks,1);
 assert.equal(h.state.automation.deliveries[0].work_ref,event().work_ref);
 await h.wake();assert.equal(h.page.clicks,1); // unknown still blocks the second work
});
test('report version change and epoch loss during check are evidenced unavailability',async()=>{
 for(const kind of ['version','epoch']) {
  const h=await setup();h.publish();const feed=h.io.feed;
  h.io.feed=async q=>q?.check?(kind==='epoch'?{epoch:'c'.repeat(32),events:[],cursor:0,reset:true}:
   {epoch,events:[{...event(),report_sha256:'c'.repeat(64)}],cursor:1,latest:1}):feed(q);
  await h.tick();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].status,'unavailable');
  assert.equal(h.state.automation.deliveries[0].code,kind==='epoch'?'BRIDGE_RESTART_REPORT_UNAVAILABLE':'REPORT_VERSION_CHANGED');
 }
});
test('non-message preview cannot release unknown; an actual user message can, without reply',async()=>{
 const h=await setup();h.publish();const page=h.io.page;let lost=true;
 h.io.page=async(b,r)=>{if(r.op==='commit'&&lost)throw Error('lost result');return page(b,r);};
 await h.tick();assert.equal(h.page.clicks,0);
 const f=messageFixture(h.page),message=completionNotice(event().work_ref,sha);
 h.page.add(f.root,'div').textContent=message;
 h.io.receipt=async(b,r)=>f.observe({...r,route:b.route});
 lost=false;h.publish(2);await h.wake();
 assert.equal(h.state.automation.deliveries[0].status,'attempted_unknown');assert.equal(h.page.clicks,0);
 f.user(message);await h.wake();
 assert.equal(h.state.automation.deliveries[0].status,'received');assert.equal(h.state.automation.deliveries[0].receipt.replies,0);
 assert.equal(h.state.automation.deliveries[1].outcome,'clicked');assert.equal(h.page.clicks,1);
});
test('ambiguous persisted intent still blocks even if a later feed check recovers',async()=>{
 const h=await setup();h.publish();const write=h.io.write;let once=true;
 h.io.write=async(k,s)=>{await write(k,s);if(once&&s.automation.deliveries.some(e=>e.status==='attempted_unknown')){once=false;throw Error('ACK_LOST');}};
 await h.tick();await h.wake();assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.deliveries[0].status,'attempted_unknown');
});
test('persisted intent is acknowledged before adapter mutation',async()=>{
 const h=await setup();h.publish();h.writeHook=s=>{if(s.automation.deliveries.some(e=>e.status==='attempted_unknown'))throw Error('write failed');};
 await assert.rejects(h.tick());assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,'');
});
test('new report with a previously used UUID under another Project cannot alias the bound route',async()=>{
 const h=await setup();h.publish();const uuid=CHAT.split('/').at(-1);
 h.page.navigate('https://chatgpt.com/g/g-p-'+'1'.repeat(32)+'-project/c/'+uuid);
 await h.tick();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.route,CHAT);
});
test('disabled automation preserves cursor and resumes only unattempted work',async()=>{
 const h=await setup();h.publish();await h.worker.run('disable');await h.tick();assert.equal(h.page.clicks,0);
 await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;await h.tick();assert.equal(h.page.clicks,1);
 await assert.rejects(h.worker.run('arm',{delayMs:0}),/AUTOMATION_ACTIVE_OR_UNKNOWN/);
});
test('bridge epoch loss closes queued work as unavailable and never retries a clicked old work',async()=>{
 const h=await setup(60000);h.publish();await h.tick();const previous=h.state.automation.deliveries[0].work_ref;
 h.io.feed=async()=>({epoch:'c'.repeat(32),reset:true,events:[],cursor:0});await h.tick();
 assert.equal(h.state.automation.deliveries[0].work_ref,previous);assert.equal(h.state.automation.deliveries[0].status,'unavailable');assert.equal(h.page.clicks,0);
});

const batch=(n=1,count=4)=>({batch_ref:'batch-'+String(n).padStart(16,'0'),project_ref:'gpt-agent-bridge',sequence:n,
 ready_at:5,requested:count,not_submitted:0,members:Array.from({length:count},(_,i)=>({
 work_ref:'work-'+(n*1000+i).toString(16).padStart(16,'0'),state:'agent_turn_settled',result_class:'result_ready',
 classification_report_status:'readable',report_status:'readable',report_sha256:sha}))});
function unfinishedTurn(h, stop=true) {
 h.page.turn.removeChild(h.page.assistantHeading);
 h.page.turn.removeChild(h.page.readAloud);
 h.page.turn.removeChild(h.page.moreActions);
 const button=stop?h.page.add(h.page.footer,'button',{type:'button','aria-label':'Stop'}):null;
 return {finish() {
   if(button?.parentNode)h.page.footer.removeChild(button);
   h.page.turn.appendChild(h.page.assistantHeading);
   h.page.turn.appendChild(h.page.readAloud);
   h.page.turn.appendChild(h.page.moreActions);
 }};
}

test('scenario 1: a batch finishes during a Web turn; Stop and a stop-less gap both wait for final turn evidence',async()=>{
 const h=await setup(),e=batch(),turn=unfinishedTurn(h);h.publish(e);
 await h.tick();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].code,'BUSY_STOP_PRESENT');
 h.page.footer.removeChild(h.page.footer.querySelectorAll('button[aria-label="Stop"]')[0]);
 h.page.clock.now+=2100;await h.wake();assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.deliveries[0].code,'BUSY_TURN_UNSETTLED');
 turn.finish();h.page.clock.now+=2100;await h.wake();assert.equal(h.page.clicks,1);
 assert.equal(h.page.editor.textContent,brief(e));
});

test('scenario 2: two delegate batches finish before the same Web turn ends and create one durable grouped intent',async()=>{
 const h=await setup(),a=batch(1,2),b=batch(2,3),turn=unfinishedTurn(h);
 h.publish(a);h.publish(b);await h.tick();assert.equal(h.page.clicks,0);
 turn.finish();h.page.clock.now+=2100;await h.wake();
 assert.equal(h.page.clicks,1);
 const rows=h.state.automation.deliveries;
 assert.equal(rows.length,2);assert.equal(rows[0].noticeVersion,3);assert.equal(rows[1].mergedInto,a.batch_ref);
 assert.deepEqual(rows[0].merge.map(x=>x.id),[a.batch_ref,b.batch_ref]);
 const message='Agent 已结束：'+a.batch_ref+'（'+a.members.map(x=>x.work_ref).join('、')+'）、'+
   b.batch_ref+'（'+b.members.map(x=>x.work_ref).join('、')+'）。';
 assert.equal(h.page.editor.textContent,message);
 const f=messageFixture(h.page);f.user(message);h.page.edit('');
 h.io.receipt=async(binding,request)=>f.observe({...request,route:binding.route});
 await h.wake();assert.deepEqual(h.state.automation.deliveries.map(x=>x.status),['received','received']);
 await h.wake();assert.equal(h.page.clicks,1);
});

test('scenario 3: A wakes a completed Web turn, B finishes during the resumed turn and waits until it finishes',async()=>{
 const h=await setup(),a=batch(1),b=batch(2);
 h.publish(a);await h.tick();assert.equal(h.page.clicks,1);
 h.received();const turn=unfinishedTurn(h);h.publish(b);await h.wake();
 assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries.map(x=>x.status),['received','waiting']);
 h.page.edit('');h.page.renderVoice();turn.finish();h.page.clock.now+=2100;await h.wake();
 assert.equal(h.page.clicks,2);assert.equal(h.page.editor.textContent,brief(b));
 assert.equal(h.state.automation.deliveries[1].noticeVersion,2);
});

test('owned prefill rollback retains intent and never retries; user edits stay unknown',async()=>{
 for(const userEdit of [false,true]) {
  const h=await setup(),e=batch();h.publish(e);
  let stop;h.page.onYield=()=>{
   if(!stop?.parentNode)stop=h.page.add(h.page.footer,'button',{type:'button','aria-label':'Stop'});
   if(userEdit){h.page.editor.textContent+=' USER';h.page.doc.emit({type:'input',target:h.page.editor});}
  };
  await h.tick();const d=h.state.automation.deliveries[0];assert.equal(h.page.clicks,0);
  if(userEdit) {
   assert.equal(d.status,'attempted_unknown');assert.equal(d.outcome,'preclick_stop');
   assert(h.page.editor.textContent.includes(' USER'));
  } else {
   assert.equal(d.status,'waiting');assert.equal(d.outcome,'rolled_back_before_click');
   assert.equal(h.page.editor.textContent,'');
   const pinned=structuredClone(d);
   h.page.footer.removeChild(stop);h.page.onYield=()=>{};h.page.clock.now+=2100;await h.wake();await h.wake();
   assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,'');
   assert.deepEqual(h.state.automation.deliveries[0],pinned);
  }
 }
});

test('a temporarily unreadable batch does not delay another ready batch or join its intent',async()=>{
 const h=await setup(),a=batch(1),b=batch(2);h.publish(a);h.publish(b);
 const feed=h.io.feed;h.io.feed=async q=>q?.check===a.batch_ref?{epoch,cursor:2,latest:2,events:[],check:{work_ref:a.batch_ref,state:'retry'}}:feed(q);
 await h.tick();assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,brief(b));
 assert.equal(h.state.automation.deliveries[0].status,'waiting');
 assert.equal(h.state.automation.deliveries[1].noticeVersion,2);
});

test('batch uses actual serialized adapter once, exact bounded user-message receipt, and keeps old history',async()=>{
 const h=await setup(),e=batch();h.publish();await h.tick();h.page.edit('');h.received();await h.wake();
 const old=structuredClone(h.state.automation.deliveries[0]);
 h.page.button.attrs={type:'button','aria-label':'Start Voice','data-state':'closed'};e.sequence=2;h.publish(e);h.page.clock.now+=2100;
 await h.wake();assert.equal(h.page.clicks,2);assert.equal(h.page.editor.textContent,brief(e));
 const f=messageFixture(h.page);f.user(brief(e));h.page.edit('');
 h.io.receipt=async(b,r)=>f.observe({...r,route:b.route});await h.wake();
 assert.equal(h.state.automation.deliveries[1].status,'received');
 assert.deepEqual(h.state.automation.deliveries[0],old);await h.wake();assert.equal(h.page.clicks,2);
});
test('batch unknown does not split or retry through worker rebuild, re-enable or epoch change',async()=>{
 const h=await setup(),e=batch();h.publish(e);h.publish(batch(2));const original=h.io.page;
 h.io.page=async(b,r)=>{const v=await original(b,r);if(r.op==='commit')throw Error('lost receipt');return v;};
 await h.tick();assert.equal(h.page.clicks,1);await h.wake();await h.worker.run('enable',{delayMs:0});await h.wake();
 h.io.feed=async()=>({epoch:'d'.repeat(32),reset:true,cursor:0,events:[]});await h.wake();
 assert.equal(h.page.clicks,1);assert.equal(h.state.automation.deliveries[0].status,'attempted_unknown');
 assert.equal(h.state.automation.deliveries[1].status,'attempted_unknown');
 assert.equal(h.state.automation.deliveries[1].mergedInto,e.batch_ref);
 assert.equal(h.state.automation.deliveries[0].members.length,4);
});
test('batch transient sending check and network recover without a new batch identity',async()=>{
 const h=await setup(60000),e=batch();h.publish(e);await h.tick();h.page.clock.now+=61000;
 const feed=h.io.feed;let blocked=true;
 h.io.feed=async q=>q?.check&&blocked?{epoch,cursor:0,latest:1,events:[],check:{work_ref:q.check,state:'retry'}}:feed(q);
 await h.wake();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].status,'waiting');
 assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
 blocked=false;h.disconnect(true);await h.wake();assert.equal(h.page.clicks,0);
 h.disconnect(false);await h.wake();assert.equal(h.page.clicks,1);
 assert.equal(h.state.automation.deliveries[0].batch_ref,e.batch_ref);
});
test('batch pre-intent check may update late report or expiry but rejects changed readable SHA or membership',async()=>{
 for(const mode of ['late','expiry','sha','membership']) {
  const h=await setup(),e=batch();
  if(mode==='late'){Object.assign(e.members[0],{result_class:'attention_required',classification_report_status:'missing',report_status:'missing'});delete e.members[0].report_sha256;}
  h.publish(e);const feed=h.io.feed;
  h.io.feed=async q=>{const f=structuredClone(await feed(q));if(q?.check){const m=f.events[0].members[0];
   if(mode==='late')Object.assign(m,{report_status:'readable',report_sha256:sha});
   if(mode==='expiry'){Object.assign(m,{state:'expired',result_class:'unavailable',report_status:'unavailable'});delete m.report_sha256;}
   if(mode==='sha')m.report_sha256='c'.repeat(64);
   if(mode==='membership')m.work_ref='work-'+'f'.repeat(16);
  }return f;};
  await h.tick();assert.equal(h.page.clicks,['late','expiry'].includes(mode)?1:0);
 }
});
test('largest admitted batch and all-abnormal summaries keep complete fixed metadata without report text',async()=>{
 for(const count of [1,528]) {
  const h=await setup(),e=batch(1,count);h.publish(e);assert.equal(validCompletion(e),true);
  await h.tick();assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,brief(e));
  assert.equal((h.page.editor.textContent.match(/work-[0-9a-f]{16}/g)||[]).length,count);
  assert(brief(e).length<=160000);
 }
 const h=await setup(),e=batch();e.requested=6;e.not_submitted=2;
 for(const m of e.members){Object.assign(m,{state:'continuity_lost',result_class:'attention_required',classification_report_status:'unknown',report_status:'missing'});delete m.report_sha256;}
 h.publish(e);await h.tick();assert.equal(h.page.clicks,1);assert(!h.page.editor.textContent.includes('SHA256='));
});
test('batch arbitrary text, running member, duplicate and oversized list fail before adapter mutation',async()=>{
 for(const mutate of [e=>e.members[0].state='running',e=>e.members[0].work_ref='injected prompt',
  e=>e.members[0].report_sha256='not a sha',e=>e.members.push(e.members[0]),e=>{e.requested=529;e.not_submitted=525;}]) {
  const e=batch();mutate(e);assert.equal(validCompletion(e),false);
  const h=await setup();const b=h.state.binding,ready=await h.io.page(b,{op:'prepare'});
  const r=await h.io.page(b,{op:'commit',eventId:e.batch_ref,batch:e,lease:ready.lease});
  assert.equal(r.stage,'blocked_before_mutation');assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,'');
 }
});
test('non-message batch preview never unlocks unknown; exact user message does',async()=>{
 const h=await setup(),e=batch();h.publish(e);const original=h.io.page;let lost=true;
 h.io.page=async(b,r)=>{if(r.op==='commit'&&lost)throw Error('unknown before acknowledgement');return original(b,r);};
 await h.tick();const f=messageFixture(h.page);h.page.add(f.root,'div').textContent=brief(e);
 h.io.receipt=async(b,r)=>f.observe({...r,route:b.route});await h.wake();assert.equal(h.state.automation.deliveries[0].status,'attempted_unknown');
 assert.equal(h.page.clicks,0);f.user(brief(e));await h.wake();assert.equal(h.state.automation.deliveries[0].status,'received');
 assert.equal(h.page.clicks,0);
});

// Live 0.3.0 evidence: the host rewrites each inserted newline to one ASCII space.
// Keep exact ownership checks; the fixed formatter must survive this actual rewrite.
test('batch survives observed newline normalization without weakening exact ownership',async()=>{
 const h=await setup(),e=batch();h.publish(e);
 h.page.onYield=()=>{h.page.editor.textContent=h.page.editor.textContent.replace(/\n/g,' ');};
 await h.tick();assert.equal(h.page.clicks,1);
 assert.equal(h.page.editor.textContent,brief(e));
 await h.wake();assert.equal(h.page.clicks,1);
});
test('batch genuine prefill changes stop before click, close with evidence and never replay',async()=>{
 const h=await setup(),e=batch();h.publish(e);
 h.page.onYield=()=>{h.page.editor.textContent+=' USER';};
 await h.tick();const before=h.state.automation.deliveries[0];
 assert.equal(h.page.clicks,0);assert.equal(before.code,'OWNED_TEXT_CHANGED_LEFT_IN_PLACE');
 assert.equal(before.outcome,'preclick_stop');
 await h.worker.run('close_delivery',{id:e.batch_ref});const after=h.state.automation.deliveries[0];
 assert.deepEqual(after,{...before,status:'closed_before_send'});
 await h.wake();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries.length,1);
});

// Literal v1 text contract retained from deployed 0.3.1, independent of the current formatter.
function legacyText(e) {
 if(!e.batch_ref)return '【Bridge 报告可取】project_ref=gpt-agent-bridge；work_ref='+e.work_ref+'；报告 SHA256='+e.report_sha256+
  '。请用 work_report 读取对应报告，再依据原授权判断与继续。此通知只表示报告可读，不表示任务成功；不授予新任务或循环派工权限。';
 return '【Bridge 派工批次已收束】project_ref=gpt-agent-bridge；batch_ref='+e.batch_ref+
  '；本次条目='+e.requested+'；保留Work='+e.members.length+'；未派出='+e.not_submitted+'。 '+
  e.members.map(m=>'work_ref='+m.work_ref+'；终态='+m.state+'；最终分类='+m.result_class+
   '；分类时报告='+m.classification_report_status+'；当前报告='+m.report_status+
   (m.report_status==='readable'?'；SHA256='+m.report_sha256:'')).join(' ')+
  ' 请用 work_report 按原 work_ref 读取可读报告，异常或缺报告按状态核查，再依据原授权判断与继续。全批收束不表示全批成功；不授予新任务或循环派工权限；过期项不重派。';
}
const shortText=e=>e.batch_ref?'本批 Agent 已结束（'+e.batch_ref+'）：'+e.members.map(m=>m.work_ref).join('、')+'。':
 'Agent 已结束：'+e.work_ref+'。';
const legacyRow=(e,status='attempted_unknown')=>({...e,epoch,route:CHAT,status,code:'CLICK_ATTEMPTED_RECEIPT_UNKNOWN',outcome:'clicked',intentAt:123,createdAt:1,dueAt:1});

for(const mode of ['queued','busy','draft'])test('explicit recipient switch moves only unsent real rows: '+mode,async()=>{
 const h=await setup(mode==='queued'?60000:0);h.publish(event());h.publish(batch(2));
 if(mode==='busy')h.page.add(h.page.doc,'button',{'data-testid':'stop-button'});
 if(mode==='draft')h.page.edit('keep my draft');
 h.page.clock.now+=2100;await h.tick();
 const before=h.state;assert(before.automation.deliveries.every(e=>e.intentAt===undefined));
 // A first prompt in the new Chat has already dispatched another Work, whose
 // completion is published but has not yet been polled by the old recipient.
 h.publish(3);h.page.navigate(OTHER);
 let writes=0;h.writeHook=s=>{writes++;assert.equal(s.binding.route,OTHER);assert.equal(s.automation.route,OTHER);};
 await h.worker.run('enable',{delayMs:0});
 assert.equal(writes,1);assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.cursor,before.automation.cursor);assert.equal(h.state.automation.epoch,epoch);
 assert.deepEqual(h.state.automation.deliveries,before.automation.deliveries.map(e=>({...e,route:OTHER})));
 h.writeHook=()=>{};
 if(mode==='busy')h.page.doc.removeChild(h.page.doc.querySelectorAll('button[data-testid="stop-button"]')[0]);
 if(mode==='draft')h.page.edit('');
 h.page.clock.now+=61000;await h.wake();
 assert.equal(h.state.automation.cursor,3);assert.equal(h.state.automation.deliveries.length,3);
 assert(h.state.automation.deliveries.every(e=>e.route===OTHER));assert.equal(h.page.clicks,1);
 await h.worker.run('enable',{delayMs:0});await h.wake();assert.equal(h.page.clicks,1);
});
test('disabled switch preserves unpolled cursor, settled history and synthetic identity',async()=>{
 const h=await setup();const s=h.state;
 s.automation.deliveries=[legacyRow(event(),'received'),{...legacyRow(event(2),'closed_before_send'),outcome:'preclick_stop'},legacyRow(event(3),'unavailable')];
 s.automation.cursor=3;s.events=[{id:'test-00000000-0000-0000-0000-000000000000',route:CHAT,status:'paused',code:'DRAFT_PRESENT'}];h.state=s;
 await h.worker.run('disable');h.publish(4);h.page.navigate(OTHER);
 await h.worker.run('enable',{delayMs:0});
 assert.deepEqual(h.state.automation.deliveries,s.automation.deliveries);
 assert.deepEqual(h.state.events,s.events.map(e=>({...e,code:'EXPLICIT_RETRY_REQUIRED'})));
 assert.equal(h.state.automation.cursor,3);h.page.clock.now+=2100;await h.tick();
 assert.equal(h.state.automation.cursor,4);assert.equal(h.page.clicks,1);
});

for(const changedBoot of [false,true])for(const status of ['queued','paused'])
test('enable stages synthetic pause with one coherent save: '+status+', changed boot '+changedBoot,async()=>{
 const h=await setup();const s=h.state;
 const row=(n,status,code)=>({id:'test-00000000-0000-0000-0000-'+String(n).padStart(12,'0'),
  route:CHAT,generation:'old-test',status,code,createdAt:1,dueAt:60001});
 s.events=[row(1,'queued','EXPLICITLY_ARMED'),row(2,'paused','DRAFT_PRESENT'),
  {...row(3,'attempted_unknown','COMMIT_API_UNKNOWN_NO_RETRY'),intentAt:10,outcome:'unknown'},
  row(4,'receipt_confirmed','EXACT_USER_MESSAGE_OBSERVED'),row(5,status,'EXPLICITLY_ARMED')];
 h.state=s;if(changedBoot)h.boot='boot-2';let writes=0,clears=0;
 const expected=s.events.map((e,i)=>i===4?{...e,status:'paused',code:'EXPLICIT_RETRY_REQUIRED'}:
  changedBoot&&i<2?{...e,status:'paused',code:'BROWSER_RESTART_REBIND'}:e);
 h.writeHook=next=>{writes++;assert.deepEqual(next.events,expected);assert.equal(next.binding.route,CHAT);};
 h.io.clearAlarm=async()=>{clears++;assert.deepEqual(h.state.events,expected);};
 await h.worker.run('enable',{delayMs:0});
 assert.equal(writes,1);assert.equal(clears,1);assert.equal(h.state.boot,changedBoot?'boot-2':s.boot);
 assert.deepEqual(h.state.events,expected);assert.equal(h.page.clicks,0);
 assert.deepEqual(h.state.automation.deliveries,s.automation.deliveries);
});
for(const failure of ['bind','save'])test('failed enable does not publish synthetic pause or boot normalization: '+failure,async()=>{
 const h=await setup();const before=h.state;
 before.events=[{id:'test-00000000-0000-0000-0000-000000000000',route:CHAT,status:'queued',code:'EXPLICITLY_ARMED'}];
 h.state=before;h.boot='boot-2';let clears=0;
 h.io.clearAlarm=async()=>{clears++;};
 if(failure==='bind')h.pageHook=()=>{throw Error('BIND_FAILED');};
 else h.writeHook=()=>{throw Error('SAVE_FAILED');};
 await assert.rejects(h.worker.run('enable',{delayMs:0}));
 assert.deepEqual(h.state,before);assert.equal(clears,0);assert.equal(h.page.clicks,0);
});
for(const invalid of [null,undefined,false,0,{},[], '', 'https://chatgpt.com/'])
test('recipient transfer refuses invalid persisted route before bind: '+JSON.stringify(invalid),async()=>{
 const h=await setup(60000);h.publish();await h.tick();const before=h.state;
 before.automation.deliveries[0].route=invalid;
 before.automation.deliveries.push(legacyRow(event(2),'received'));h.state=before;h.page.navigate(OTHER);
 const calls=h.calls.length;let writes=0;h.writeHook=()=>{writes++;};
 await assert.rejects(h.worker.run('enable',{delayMs:0}),/RECIPIENT_SWITCH_REAL_FROZEN/);
 assert.deepEqual(h.state,before);assert.equal(writes,0);assert.equal(h.calls.length,calls);assert.equal(h.page.clicks,0);
});
for(const failure of ['clearAlarm','pollAlarm'])test('post-save '+failure+' failure retains truthful recipient on reopen without retry',async()=>{
 const h=await setup(60000);h.publish();await h.tick();const before=h.state;h.page.navigate(OTHER);
 let writes=0,clears=0,polls=0;h.writeHook=()=>{writes++;};
 h.io.clearAlarm=async()=>{clears++;if(failure==='clearAlarm')throw Error('ALARM_UNKNOWN');};
 h.io.pollAlarm=async()=>{polls++;if(failure==='pollAlarm')throw Error('ALARM_UNKNOWN');};
 await assert.rejects(h.worker.run('enable',{delayMs:0}),/ALARM_UNKNOWN/);
 const saved=h.state;assert.equal(saved.binding.route,OTHER);assert.equal(saved.automation.route,OTHER);
 assert.equal(saved.automation.cursor,before.automation.cursor);assert.equal(saved.automation.epoch,before.automation.epoch);
 assert.deepEqual(saved.automation.deliveries,before.automation.deliveries.map(e=>({...e,route:OTHER})));
 const reopened=await new Automation(h.io).run('status');assert.deepEqual(reopened,saved);
 assert.equal(writes,1);assert.equal(clears,1);assert.equal(polls,failure==='clearAlarm'?0:1);assert.equal(h.page.clicks,0);
});
for(const field of ['unknown','intentAt','outcome','pageAtPrepare','receiptAt','receipt','merge','synthetic'])test('recipient switch pins durable evidence and moves only clean rows: '+field,async()=>{
 const h=await setup(60000);h.publish();h.publish(2);await h.tick();const s=h.state,e=s.automation.deliveries[0];
 if(field==='unknown')e.status='attempted_unknown';
 else if(field==='synthetic')s.events=[{id:'test-00000000-0000-0000-0000-000000000000',route:CHAT,status:'attempted_unknown'}];
 else if(field==='merge'){
  e.noticeVersion=3;e.merge=s.automation.deliveries.map(x=>({id:x.work_ref,workRefs:[x.work_ref]}));
  Object.assign(s.automation.deliveries[1],{noticeVersion:3,mergedInto:e.work_ref});
 } else {e.status='waiting';e[field]=field==='intentAt'?0:field==='outcome'?'rolled_back_before_click':{};}
 h.state=s;h.page.navigate(OTHER);const before=h.state,calls=h.calls.length;
 await h.worker.run('enable',{delayMs:0});
 const frozen=x=>x.status==='attempted_unknown'||['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode'].some(k=>Object.hasOwn(x,k));
 assert.deepEqual(h.state.automation.deliveries,before.automation.deliveries.map(x=>frozen(x)?x:{...x,route:OTHER}));
 assert.deepEqual(h.state.events,before.events);assert.equal(h.state.automation.route,OTHER);
 assert.equal(h.state.automation.cursor,before.automation.cursor);assert.equal(h.state.automation.epoch,before.automation.epoch);
 assert.equal(h.calls.length,calls+1);assert.equal(h.page.clicks,0);
});
test('recipient switch defers epoch reconciliation to the next normal tick and preserves poll metadata',async()=>{
 const h=await setup(60000);h.publish();await h.tick();const before=h.state;
 h.io.feed=async()=>({epoch:'c'.repeat(32),reset:true,events:[],cursor:0});h.page.navigate(OTHER);
 await h.worker.run('enable',{delayMs:0});
 assert.equal(h.state.automation.epoch,epoch);assert.equal(h.state.automation.cursor,1);
 assert.equal(h.state.automation.lastPoll,before.automation.lastPoll);
 assert.deepEqual(h.state.automation.deliveries,before.automation.deliveries.map(e=>({...e,route:OTHER})));
 await h.tick();assert.equal(h.state.automation.epoch,'c'.repeat(32));assert.equal(h.state.automation.cursor,0);
 assert.equal(h.state.automation.deliveries[0].status,'unavailable');assert.equal(h.page.clicks,0);
});
test('state changed during recipient bind is never overwritten with a stale queue',async()=>{
 const h=await setup(60000);h.publish();await h.tick();h.page.navigate(OTHER);let changed;
 h.pageHook=()=>{changed=h.state;changed.revision++;changed.automation.enabled=false;h.state=changed;};
 await assert.rejects(h.worker.run('enable',{delayMs:0}),/STALE_STATE_NO_ATTEMPT/);
 assert.deepEqual(h.state,changed);assert.equal(h.page.clicks,0);
});
for(const failure of ['feed','bind','selection','navigation','lateSelection','save','ack','boot'])test('recipient publication stays coherent on '+failure,async()=>{
 const h=await setup();const before=h.state;h.page.navigate(OTHER);
 if(failure==='feed') { // First enable cannot publish a binding if feed validation fails.
  delete before.automation;h.state=before;h.io.feed=async()=>{throw Error('OFFLINE');};
 }
 if(failure==='boot'){h.boot='boot-2';h.pageHook=()=>{throw Error('BIND_FAILED');};}
 if(failure==='bind')h.pageHook=()=>{throw Error('BIND_FAILED');};
 if(failure==='selection')h.pageHook=()=>{h.selected=2;};
 if(failure==='navigation')h.pageHook=()=>{h.page.navigate(CHAT);};
 if(failure==='lateSelection') {const read=h.io.read;let reads=0;h.io.read=async(...args)=>{const s=await read(...args);if(++reads===2)h.selected=2;return s;};}
 if(['save','ack'].includes(failure))h.writeHook=s=>{if(failure==='ack')h.state=s;throw Error('SAVE_UNKNOWN');};
 await assert.rejects(h.worker.run('enable',{delayMs:0}));
 if(failure==='ack') {assert.equal(h.state.binding.route,OTHER);assert.equal(h.state.automation.route,OTHER);assert.equal(h.state.automation.cursor,before.automation.cursor);}
 else assert.deepEqual(h.state,before);
 assert.equal(h.page.clicks,0);
});

test('brief unversioned feed pins v2 with first intent; four members remain one exact notice and strict receipt',async()=>{
 for(const e of [event(),batch()]) {
  const h=await setup();h.publish(e);let persisted;
  h.writeHook=async s=>{const d=s.automation?.deliveries[0];if(d?.status==='attempted_unknown')persisted=structuredClone(d);};
  h.pageHook=async(b,r)=>{if(r.op==='commit'){assert.equal(persisted.noticeVersion,2);assert.ok(persisted.intentAt);assert.equal(r.noticeVersion,2);}};
  await h.tick();assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,shortText(e));
  assert.equal(h.state.automation.deliveries.length,1);assert.equal(h.state.automation.deliveries[0].noticeVersion,2);
  if(e.members)assert.deepEqual(h.state.automation.deliveries[0].members,e.members);
  const f=messageFixture(h.page);f.user(shortText(e));h.page.edit('');h.io.receipt=async(b,r)=>f.observe({...r,route:b.route});
  await h.wake();assert.equal(h.state.automation.deliveries[0].status,'received');await h.wake();assert.equal(h.page.clicks,1);
 }
});
test('legacy unknown verifies its original long user message, not the new short text; intent and version stay untouched',async()=>{
 for(const e of [event(),batch()]) {
  const h=await setup();h.publish(e);const original=legacyRow(e);const s=h.state;s.automation.deliveries=[original];s.automation.cursor=1;h.state=s;
  const f=messageFixture(h.page);f.user(shortText(e));h.io.receipt=async(b,r)=>{assert.equal(r.message,legacyText(e));return f.observe({...r,route:b.route});};
  await h.wake();assert.deepEqual(h.state.automation.deliveries[0],original);assert.equal(h.page.clicks,0);
  f.user(legacyText(e));await h.wake();const d=h.state.automation.deliveries[0];assert.equal(d.status,'received');
  assert.equal(d.intentAt,123);assert.equal(Object.hasOwn(d,'noticeVersion'),false);assert.equal(completionMessage(d),legacyText(e));
  await h.wake();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries.length,1);
 }
});
test('legacy received and closed rows are byte-equivalent across load, re-enable and worker rebuild',async()=>{
 const h=await setup();h.publish(event());h.publish(batch(2));const rows=[legacyRow(event(),'received'),{...legacyRow(batch(2),'closed_before_send'),outcome:'preclick_stop'}];
 const s=h.state;s.automation.deliveries=rows;s.automation.cursor=2;h.state=s;
 await h.worker.run('enable',{delayMs:0});await h.wake();assert.deepEqual(h.state.automation.deliveries,rows);assert.equal(h.page.clicks,0);
 for(const row of rows)assert.equal(completionMessage(row),legacyText(row));
});
test('actual serialized adapter preserves implicit/explicit legacy and exact v2 for both feed types',async()=>{
 for(const e of [event(),batch()])for(const version of [undefined,1,2]) {
  const h=await setup(),b=h.state.binding,ready=await h.io.page(b,{op:'prepare'});
  const r=await h.io.page(b,{op:'commit',eventId:completionId(e),reportSha:e.report_sha256,
   ...(e.batch_ref?{batch:e}:{}),...(version===undefined?{}:{noticeVersion:version}),lease:ready.lease});
  assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,version===2?shortText(e):legacyText(e));assert.equal(r.code,'CLICK_ATTEMPTED_RECEIPT_UNKNOWN');
 }
});
test('brief abnormal/expired metadata stays internal and invalid SHA or format version still blocks before mutation',async()=>{
 const e=batch();Object.assign(e.members[1],{result_class:'attention_required',classification_report_status:'unknown'});
 Object.assign(e.members[2],{result_class:'attention_required',classification_report_status:'missing',report_status:'missing'});delete e.members[2].report_sha256;
 Object.assign(e.members[3],{state:'expired',result_class:'unavailable',classification_report_status:'unavailable',report_status:'unavailable'});delete e.members[3].report_sha256;
 const h=await setup();h.publish(e);await h.tick();assert.equal(h.page.editor.textContent,shortText(e));assert.deepEqual(h.state.automation.deliveries[0].members,e.members);
 for(const version of [0,3,'2',null]) {
  assert.equal(validCompletion({...e,noticeVersion:version}),false);
  const x=await setup(),b=x.state.binding,ready=await x.io.page(b,{op:'prepare'});
  const r=await x.io.page(b,{op:'commit',eventId:e.batch_ref,batch:e,noticeVersion:version,lease:ready.lease});
  assert.equal(r.stage,'blocked_before_mutation');assert.equal(x.page.clicks,0);assert.equal(x.page.editor.textContent,'');
 }
 const invalid=structuredClone(e);invalid.members[0].report_sha256='not-a-sha';assert.equal(validCompletion(invalid),false);
 const x=await setup(),b=x.state.binding,ready=await x.io.page(b,{op:'prepare'});
 const r=await x.io.page(b,{op:'commit',eventId:invalid.batch_ref,batch:invalid,noticeVersion:2,lease:ready.lease});assert.equal(r.stage,'blocked_before_mutation');assert.equal(x.page.clicks,0);
});

// Future receiver changes never resolve or reuse evidence belonging to an old Chat.
test('old real unknown stays exact while a new receiver gets new Work once and blocks its own unknown',async()=>{
 const h=await setup();h.publish();await h.tick();const old=structuredClone(h.state.automation.deliveries[0]);
 const next=h.pages.get(2);next.location.href=OTHER;h.selected=2;
 h.io.exactTabs=async r=>[...h.pages].filter(([,p])=>p.location.href===r).map(([id])=>({id,incognito:false}));
 h.io.receipt=async b=>{assert.equal(b.route,OTHER);return {ok:true,scope:'chat-user-message-v1',notices:0,replies:0,draft:false,tooMany:false};};
 await h.worker.run('enable',{delayMs:0});assert.deepEqual(h.state.automation.deliveries[0],old);
 assert.equal(h.state.automation.cursor,1);assert.equal(h.page.clicks,1);assert.equal(next.clicks,0);
 h.publish(2);next.clock.now+=2100;await h.wake();assert.equal(next.clicks,1);
 assert.deepEqual(h.state.automation.deliveries[0],old);assert.equal(h.state.automation.deliveries[1].route,OTHER);
 h.publish(3);await h.worker.run('enable',{delayMs:0});await h.wake();await h.wake();
 assert.equal(next.clicks,1);assert.equal(h.page.clicks,1);assert.equal(h.state.automation.deliveries[2].status,'queued');
 assert.deepEqual(h.state.automation.deliveries[0],old);
});
test('old synthetic unknown stays pinned and blocks only its own active route',async()=>{
 const h=await setup();const s=h.state;
 const old={id:'test-00000000-0000-0000-0000-000000000000',route:CHAT,status:'attempted_unknown',generation:'legacy',createdAt:1,dueAt:1,intentAt:2,outcome:'unknown',code:'COMMIT_API_UNKNOWN_NO_RETRY'};
 s.events=[old];h.state=s;h.publish();await h.tick();assert.equal(h.page.clicks,0);
 h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});assert.deepEqual(h.state.events,[old]);
 h.page.clock.now+=2100;await h.wake();assert.equal(h.page.clicks,1);assert.deepEqual(h.state.events,[old]);
 h.page.edit('');h.page.renderVoice();h.page.navigate(CHAT);await h.worker.run('enable',{delayMs:0});
 h.publish(2);h.page.clock.now+=2100;await h.wake();assert.equal(h.page.clicks,1);
 assert.equal(h.state.automation.deliveries[1].status,'queued');assert.deepEqual(h.state.events,[old]);
});
test('frozen waiting group stays exact through a new receiver and return to its original Chat',async()=>{
 const h=await setup();const s=h.state;
 const rows=[legacyRow(event(),'waiting'),legacyRow(event(2),'waiting')];
 for(const e of rows){e.noticeVersion=3;e.outcome='rolled_back_before_click';}
 rows[0].merge=rows.map(e=>({id:e.work_ref,workRefs:[e.work_ref]}));rows[1].mergedInto=rows[0].work_ref;
 s.automation.deliveries=rows;s.automation.cursor=2;h.state=s;
 h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});h.publish(3);h.page.clock.now+=2100;await h.wake();
 assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries.slice(0,2),rows);
 h.page.edit('');h.page.renderVoice();h.page.navigate(CHAT);await h.worker.run('enable',{delayMs:0});
 h.publish(4);h.page.clock.now+=2100;await h.wake();await h.wake();
 assert.equal(h.page.clicks,2);assert.deepEqual(h.state.automation.deliveries.slice(0,2),rows);
 assert.equal(h.state.automation.deliveries[3].route,CHAT);
 assert(!h.page.editor.textContent.includes(rows[0].work_ref));assert(!h.page.editor.textContent.includes(rows[1].work_ref));
});
test('epoch change preserves frozen groups and settled history but retires only clean unattempted rows',async()=>{
 const h=await setup();const s=h.state,rows=[legacyRow(event(),'waiting'),legacyRow(event(2),'waiting')];
 for(const e of rows)e.noticeVersion=3;
 rows[0].merge=rows.map(e=>({id:e.work_ref,workRefs:[e.work_ref]}));rows[1].mergedInto=rows[0].work_ref;
 const closed=legacyRow(event(4),'received');
 s.automation.deliveries=[...rows,{...event(3),epoch,route:CHAT,status:'queued',code:'REPORT_READY',dueAt:1},closed];s.automation.cursor=4;h.state=s;
 h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});
 const fresh={...event(5),sequence:1},nextEpoch='c'.repeat(32);
 h.io.feed=async q=>q?.epoch===epoch?{epoch:nextEpoch,events:[],cursor:0,reset:true}:{epoch:nextEpoch,events:[fresh],cursor:1,latest:1};
 await h.tick();assert.equal(h.state.automation.epoch,nextEpoch);assert.equal(h.state.automation.cursor,0);
 assert.deepEqual(h.state.automation.deliveries.slice(0,2),rows);assert.deepEqual(h.state.automation.deliveries[3],closed);
 assert.equal(h.state.automation.deliveries[2].status,'unavailable');
 h.page.clock.now+=2100;await h.wake();await h.wake();assert.equal(h.page.clicks,1);
 assert.deepEqual(h.state.automation.deliveries.slice(0,2),rows);assert.deepEqual(h.state.automation.deliveries[3],closed);
 assert.equal(h.state.automation.cursor,1);assert.equal(h.state.automation.deliveries[4].route,OTHER);
});
test('own durable keys with undefined values pin waiting rows without replay or status inference',async()=>{
 for(const field of ['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode']) {
  const h=await setup(),s=h.state,row={...event(),epoch,route:CHAT,status:'waiting',dueAt:1,[field]:undefined};
  s.automation.deliveries=[row];s.automation.cursor=1;h.state=s;h.page.navigate(OTHER);
  await h.worker.run('enable',{delayMs:0});await h.wake();
  h.page.navigate(CHAT);await h.worker.run('enable',{delayMs:0});await h.wake();
  assert.deepEqual(h.state.automation.deliveries,[row],field);assert.equal(h.page.clicks,0,field);
 }
});
test('deliver independently rejects wrong-route and already-intended rows before any IO',async()=>{
 const h=await setup(),s=h.state,row=legacyRow(event(),'waiting'),calls=h.calls.length;
 await assert.rejects(h.worker.deliver(s,[{...row,route:OTHER}]),/DELIVERY_ROUTE_MISMATCH/);
 await assert.rejects(h.worker.deliver(s,[row]),/DELIVERY_ALREADY_ATTEMPTED/);
 assert.equal(h.calls.length,calls);assert.equal(h.page.clicks,0);
});
test('old unknown capacity is retained rather than discarded to admit a new-route notification',async()=>{
 const h=await setup(),s=h.state;const rows=Array.from({length:128},(_,i)=>legacyRow(event(i+1)));
 s.automation.deliveries=rows;s.automation.cursor=128;h.state=s;h.page.navigate(OTHER);
 await h.worker.run('enable',{delayMs:0});h.publish(129);await h.wake();
 assert.equal(h.state.automation.route,OTHER);assert.equal(h.state.automation.error,'DELIVERY_HISTORY_FULL');
 assert.deepEqual(h.state.automation.deliveries,rows);assert.equal(h.page.clicks,0);
});

// Historical corruption must stay inspectable without becoming permission to send.
test('unattributed unknown blocks sends and switching before IO, but status and disable remain usable',async()=>{
 for(const lostRoute of [undefined,null,'https://chatgpt.com/']) {
  const h=await setup(),s=h.state,row={...legacyRow(event()),route:lostRoute};
  s.automation.deliveries=[row];s.automation.cursor=1;h.state=s;h.publish(2);
  assert.deepEqual((await h.worker.run('status')).automation.deliveries,[row]);
  let feeds=0;const feed=h.io.feed;h.io.feed=async q=>{feeds++;return feed(q);};
  const calls=h.calls.length;
  await h.tick();
  assert.equal(h.page.clicks,0);assert.equal(feeds,0);assert.equal(h.calls.length,calls);
  assert.equal(h.state.automation.error,'DELIVERY_UNATTRIBUTED_UNKNOWN');
  assert.equal(h.state.automation.cursor,1);assert.deepEqual(h.state.automation.deliveries,[row]);
  h.page.navigate(OTHER);const before=h.state;
  await assert.rejects(h.worker.run('enable',{delayMs:0}),/DELIVERY_UNATTRIBUTED_UNKNOWN/);
  assert.deepEqual(h.state,before);assert.equal(h.calls.length,calls);
  await assert.rejects(h.worker.run('verify'),/DELIVERY_UNATTRIBUTED_UNKNOWN/);
  await h.worker.run('disable');assert.equal(h.state.automation.enabled,false);
  assert.deepEqual(h.state.automation.deliveries,[row]);
 }
 const h=await setup(),s=h.state;
 const row={id:'test-00000000-0000-0000-0000-000000000000',route:null,status:'attempted_unknown'};
 s.events=[row];h.state=s;h.publish();await h.tick();
 assert.equal(h.page.clicks,0);assert.equal(h.state.automation.error,'DELIVERY_UNATTRIBUTED_UNKNOWN');
 assert.deepEqual((await h.worker.run('status')).events,[row]);await h.worker.run('disable');
 assert.deepEqual(h.state.events,[row]);
});

for(const [kind,make] of [['Work',event],['batch',batch]])
test('retained '+kind+' identity cannot be readmitted after epoch restart; clean new identity sends once',async()=>{
 for(const status of ['attempted_unknown','waiting','received','closed_before_send','unavailable']) {
  const h=await setup(),s=h.state,old=legacyRow(make(),status);
  s.automation.deliveries=[old];s.automation.cursor=1;h.state=s;h.page.navigate(OTHER);
  await h.worker.run('enable',{delayMs:0});
  const nextEpoch='c'.repeat(32),duplicate={...make(),sequence:1},fresh={...make(2),sequence:2};let published=[duplicate];
  h.io.feed=async q=>q?.epoch===epoch?{epoch:nextEpoch,reset:true,events:[],cursor:0}:
   {epoch:nextEpoch,events:q?.check?published.filter(e=>completionId(e)===q.check):
    published.filter(e=>e.sequence>(q?.after||0)),cursor:published.length,latest:published.length};
  h.page.clock.now+=2100;await h.tick();assert.equal(h.state.automation.cursor,0);
  await h.wake();assert.equal(h.page.clicks,0,status);assert.equal(h.state.automation.cursor,1);
  assert.deepEqual(h.state.automation.deliveries,[old]);published=[duplicate,fresh];
  await h.wake();await h.wake();
  assert.equal(h.page.clicks,1,status);assert.equal(h.page.editor.textContent,shortText(fresh));
  assert.equal(h.state.automation.cursor,2);assert.equal(h.state.automation.epoch,nextEpoch);
  assert.equal(h.state.automation.deliveries.length,2);assert.deepEqual(h.state.automation.deliveries[0],old);
  assert.equal(h.state.automation.deliveries[1].route,OTHER);
  assert.equal(completionId(h.state.automation.deliveries[1]),completionId(fresh));
 }
});

function savedGroup(ids,groupEpoch,groupRoute,status='attempted_unknown') {
 const rows=ids.map(n=>({...legacyRow(event(n),status),epoch:groupEpoch,route:groupRoute,noticeVersion:3}));
 rows[0].merge=rows.map(e=>({id:e.work_ref,workRefs:[e.work_ref]}));
 for(const row of rows.slice(1))row.mergedInto=rows[0].work_ref;
 return rows;
}

test('exact group receipt credits only the matching epoch and original route, regardless of row order',async()=>{
 for(const activeEpoch of [epoch,'c'.repeat(32)]) {
  const h=await setup();
  const older=savedGroup([1,2],epoch,CHAT),newer=savedGroup([1,2],'c'.repeat(32),OTHER);
  const active=activeEpoch===epoch?older:newer,untouched=active===older?newer:older;
  h.page.navigate(active[0].route);await h.worker.run('enable',{delayMs:0});
  const bound=h.state;bound.automation.epoch=activeEpoch;
  bound.automation.deliveries=[...untouched,...active];h.state=bound;
  let receipts=0;h.io.receipt=async(b,r)=>{
   receipts++;assert.equal(b.route,active[0].route);assert.equal(r.message,completionMessage(active[0]));
   return {ok:true,scope:'chat-user-message-v1',notices:1,replies:0,draft:false,tooMany:false};
  };
  await h.worker.run('verify');
  assert.equal(receipts,1);assert.deepEqual(h.state.automation.deliveries.slice(0,2),untouched);
  assert(h.state.automation.deliveries.slice(2).every(e=>e.status==='received'&&e.receiptCode==='EXACT_USER_MESSAGE_OBSERVED'));
  await h.worker.run('status');assert.equal(h.page.clicks,0);
 }
});

test('same-route cross-epoch receipt identity is ambiguous and cannot credit either group',async()=>{
 const h=await setup(),s=h.state,rows=[...savedGroup([1,2],epoch,CHAT),...savedGroup([1,2],'c'.repeat(32),CHAT)];
 s.automation.deliveries=rows;h.state=s;let receipts=0;
 h.io.receipt=async()=>{receipts++;return {ok:true,scope:'chat-user-message-v1',notices:1,replies:0,draft:false,tooMany:false};};
 await assert.rejects(h.worker.run('verify'),/DELIVERY_ID_AMBIGUOUS/);
 assert.equal(receipts,0);assert.deepEqual(h.state,s);assert.equal(h.page.clicks,0);
});

test('close by ambiguous ID refuses without changing either epoch',async()=>{
 const h=await setup(),s=h.state;
 const rows=[legacyRow(event()),{...legacyRow(event()),epoch:'c'.repeat(32),route:OTHER}].map(e=>({...e,outcome:'preclick_stop'}));
 s.automation.deliveries=rows;h.state=s;
 await assert.rejects(h.worker.run('close_delivery',{id:event().work_ref}),/DELIVERY_ID_AMBIGUOUS/);
 assert.deepEqual(h.state,s);assert.equal(h.page.clicks,0);
});

test('close group member resolution cannot select a same-ID child from another epoch',async()=>{
 const h=await setup(),s=h.state;
 const old=savedGroup([3,2],epoch,CHAT),chosen=savedGroup([1,2],'c'.repeat(32),OTHER);
 for(const e of [...old,...chosen])e.outcome='preclick_stop';
 s.automation.deliveries=[...old,...chosen];h.state=s;
 await h.worker.run('close_delivery',{id:chosen[0].work_ref});
 assert.deepEqual(h.state.automation.deliveries.slice(0,2),old);
 assert.deepEqual(h.state.automation.deliveries.slice(2),chosen.map(e=>({...e,status:'closed_before_send'})));
 await h.worker.run('status');assert.equal(h.page.clicks,0);
});

test('capacity eviction removes only the selected settled epoch group, preserving same-ID unknown history',async()=>{
 const h=await setup(),s=h.state,nextEpoch='c'.repeat(32);
 const settled=savedGroup([1,2],epoch,CHAT,'received'),pinned=savedGroup([1,2],nextEpoch,OTHER);
 const rest=Array.from({length:124},(_,i)=>legacyRow(event(i+100),'unavailable'));
 s.automation.deliveries=[...settled,...pinned,...rest];s.automation.epoch=nextEpoch;s.automation.cursor=0;h.state=s;
 const fresh={...event(1000),sequence:1};
 h.io.feed=async q=>({epoch:nextEpoch,events:q?.check||!q?.after?[fresh]:[],cursor:1,latest:1});
 await h.tick();
 assert.equal(h.state.automation.deliveries.length,127);assert.equal(h.state.automation.cursor,1);
 assert.deepEqual(h.state.automation.deliveries.slice(0,2),pinned);
 assert.deepEqual(h.state.automation.deliveries.slice(2,126),rest);
 assert.equal(h.page.clicks,1);await h.worker.run('status');
});

test('already-persisted cross-epoch queued duplicate cannot click even when new admission is deduplicated',async()=>{
 const h=await setup(),s=h.state,nextEpoch='c'.repeat(32),old=legacyRow(event());
 const queued={...event(),epoch:nextEpoch,route:OTHER,status:'queued',code:'REPORT_READY',dueAt:1};
 s.automation.deliveries=[old,queued];s.automation.epoch=nextEpoch;s.automation.cursor=1;h.state=s;
 h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});
 h.io.feed=async q=>({epoch:nextEpoch,events:q?.check?[event()]:[],cursor:1,latest:1});
 h.page.clock.now+=2100;await h.tick();
 assert.equal(h.page.clicks,0);assert.equal(h.state.automation.error,'DELIVERY_ID_AMBIGUOUS');
 assert.deepEqual(h.state.automation.deliveries,[old,queued]);
});

test('capacity cannot evict receipt evidence needed to block a queued or waiting cross-epoch duplicate',async()=>{
 for(const grouped of [false,true])for(const status of ['queued','waiting']) {
  const h=await setup(),nextEpoch='c'.repeat(32);
  h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});
  const settled=grouped?savedGroup([1,2],epoch,CHAT,'received'):[legacyRow(event(),'received')];
  for(const row of settled)Object.assign(row,{receiptAt:1234,receiptCode:'EXACT_USER_MESSAGE_OBSERVED',
   receipt:{scope:'chat-user-message-v1',notices:1,replies:0,turnKeys:['synthetic-original-turn']}});
  // The group variant collides with the child, not the owner, so the whole
  // original receipt group must remain together and ineligible for eviction.
  const repeated=event(grouped?2:1),queued={...repeated,epoch:nextEpoch,route:OTHER,status,code:'REPORT_READY',dueAt:1};
  const rest=Array.from({length:127-settled.length},(_,i)=>legacyRow(event(i+100)));
  const s=h.state;s.automation.deliveries=[...settled,queued,...rest];
  s.automation.epoch=nextEpoch;s.automation.cursor=1;h.state=s;
  const fresh={...event(1000),sequence:2};
  h.io.feed=async q=>({epoch:nextEpoch,events:q?.check?[repeated,fresh].filter(e=>completionId(e)===q.check):
   [fresh].filter(e=>e.sequence>(q?.after||0)),cursor:2,latest:2});
  h.page.clock.now+=2100;await h.tick();
  assert.equal(h.page.clicks,0);assert.equal(h.state.automation.error,'DELIVERY_HISTORY_FULL');
  assert.equal(h.state.automation.cursor,1);assert.equal(h.state.automation.deliveries.length,128);
  assert.deepEqual(h.state.automation.deliveries,s.automation.deliveries);
  assert.equal(h.state.automation.deliveries.some(e=>completionId(e)===completionId(fresh)),false);
  await h.worker.run('status');
 }
});

test('capacity still evicts an independent settled group and sends only the new completion once',async()=>{
 const h=await setup(),nextEpoch='c'.repeat(32);
 h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});
 const settled=savedGroup([1,2],epoch,CHAT,'received');
 const pinned=Array.from({length:126},(_,i)=>legacyRow(event(i+100)));
 const s=h.state;s.automation.deliveries=[...settled,...pinned];s.automation.epoch=nextEpoch;s.automation.cursor=1;h.state=s;
 const fresh={...event(1000),sequence:2};
 h.io.feed=async q=>({epoch:nextEpoch,events:q?.check||q?.after<2?[fresh]:[],cursor:2,latest:2});
 h.page.clock.now+=2100;await h.tick();
 assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,shortText(fresh));
 assert.equal(h.state.automation.deliveries.length,127);assert.equal(h.state.automation.cursor,2);
 assert.deepEqual(h.state.automation.deliveries.slice(0,126),pinned);
 assert.equal(completionId(h.state.automation.deliveries[126]),completionId(fresh));
 await h.wake();assert.equal(h.page.clicks,1);await h.worker.run('status');
});
