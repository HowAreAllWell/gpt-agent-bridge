import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation} from '../extension/automation.js';
import {completionMessage, completionId, validCompletion} from '../extension/completion-policy.js';
import {harness,CHAT,OTHER} from './harness.js';
const epoch='a'.repeat(32),sha='b'.repeat(64);
const brief=e=>completionMessage({...e,noticeVersion:2});
const event=(n=1)=>({work_ref:'work-'+String(n).padStart(16,'0'),project_ref:'gpt-agent-bridge',report_sha256:sha,
 sequence:n,ready_at:5,result_class:'result_ready',report_status:'readable'});
async function setup(delayMs=0) {
 const h=harness();let events=[],offline=false;
 h.io.exactTabs=async r=>r===h.page.location.href?[{id:1,incognito:false}]:[];
 h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.io.receipt=async()=>assert.fail('transcript must never be scanned');
 h.io.feed=async q=>{if(offline)throw Error('OFFLINE');const found=events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0));
  return {epoch,events:found,cursor:Math.max(q?.after||0,...found.map(e=>e.sequence),0),latest:Math.max(...events.map(e=>e.sequence),0)};};
 h.worker=new Automation(h.io);
 await h.worker.run('enable',{delayMs});h.page.clock.now+=2100;
 return Object.assign(h,{publish(n=1){events.push(typeof n==='object'?n:event(n));},disconnect(v){offline=v;},
 wake(){h.worker=new Automation(h.io);return h.worker.run('tick');},tick(){return h.worker.run('tick');}});
}
const batch=(n=1,count=4)=>({batch_ref:'batch-'+String(n).padStart(16,'0'),project_ref:'gpt-agent-bridge',sequence:n,
 ready_at:5,requested:count,not_submitted:0,members:Array.from({length:count},(_,i)=>({
 work_ref:'work-'+(n*1000+i).toString(16).padStart(16,'0'),state:'agent_turn_settled',result_class:'result_ready',
 classification_report_status:'readable',report_status:'readable',report_sha256:sha}))});
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
function unfinishedTurn(h) {
 for(const node of [h.page.assistantHeading,h.page.readAloud,h.page.moreActions])node.remove();
 h.page.add(h.page.footer,'button',{type:'button','aria-label':'Stop'});
}
test('only visible Stop delays a safe composer; missing conversation or assistant actions do not',async()=>{
 const h=await setup();unfinishedTurn(h);h.publish(batch());await h.tick();
 assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].code,'BUSY_STOP_PRESENT');
 h.page.footer.querySelectorAll('[aria-label="Stop"]')[0].remove();h.page.clock.now+=2100;await h.wake();
 assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
 h.page.edit('');h.page.renderVoice();h.page.conversation.remove();h.page.clock.now+=2100;h.publish(batch(2));
 await h.wake();assert.equal(h.page.clicks,2);assert.deepEqual(h.state.automation.deliveries,[]);
});
test('temporary report failure keeps only active queue, while authoritative loss retires its ID',async()=>{
 const h=await setup();h.publish();const feed=h.io.feed;let phase='retry';
 h.io.feed=async q=>q?.check?{epoch,events:[],cursor:0,latest:1,
  check:{work_ref:q.check,state:phase==='retry'?'retry':'unavailable',code:phase==='retry'?'REPORT_READ_TEMPORARY':'WORK_IDENTITY_LOST'}}:feed(q);
 await h.tick();assert.equal(h.state.automation.deliveries[0].status,'waiting');assert.deepEqual(h.state.automation.consumed,[]);
 phase='gone';await h.wake();assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(h.state.automation.consumed,[event().work_ref]);assert.equal(h.page.clicks,0);
});
test('pre-intent storage refusal never mutates the composer; pending metadata remains recoverable',async()=>{
 const h=await setup();h.publish();h.writeHook=s=>{if(s.automation.consumed.length)throw Error('WRITE_FAILED');};
 await assert.rejects(h.tick(),/WRITE_FAILED/);assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,'');
 assert.equal(h.state.automation.deliveries[0].work_ref,event().work_ref);assert.deepEqual(h.state.automation.consumed,[]);
});
test('page/API refusal after durable intent never recreates a queue row or permits replay',async()=>{
 for(const fault of ['missing','document','throw']) {
  const h=await setup(),page=h.io.page;h.publish();
  h.io.page=async(b,r)=>{const response=await page(b,r);if(r.op!=='commit')return response;
   if(fault==='throw')throw Error('ACK_LOST');return fault==='missing'?undefined:{...response,documentId:'wrong-document'};};
  await h.tick();assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
  assert.deepEqual(h.state.automation.consumed,[event().work_ref]);h.io.page=page;await h.wake();assert.equal(h.page.clicks,1);
 }
});
test('disabled switch preserves unpolled progress and only clean backlog follows the explicit receiver',async()=>{
 const h=await setup(60000);h.publish();await h.tick();await h.worker.run('disable');
 h.publish(2);h.page.navigate(OTHER);await h.worker.run('enable',{delayMs:0});
 assert.equal(h.state.automation.cursor,1);assert.equal(h.state.automation.deliveries[0].route,OTHER);
 h.page.clock.now+=61000;await h.wake();assert.equal(h.page.clicks,1);
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.cursor,2);assert.equal(h.state.automation.consumed.length,2);
});
test('invalid pending recipient is retained rather than guessed, while old outcome history compacts',async()=>{
 const h=await setup(60000);h.publish();await h.tick();const s=h.state;
 s.automation.deliveries[0].route=null;s.automation.deliveries.push({...event(2),epoch,route:CHAT,status:'received'});h.state=s;
 h.page.navigate(OTHER);await assert.rejects(h.worker.run('enable',{delayMs:0}),/RECIPIENT_SWITCH_REAL_FROZEN/);
 assert.equal(h.state.automation.deliveries.length,1);assert.equal(h.state.automation.deliveries[0].route,null);
 assert.equal(h.state.automation.route,CHAT);assert.deepEqual(h.state.automation.consumed,[event(2).work_ref]);
});
test('strict metadata reader rejects malformed identity suppression state without resetting',async()=>{
 for(const consumed of [null,{},['bad'],[event().work_ref,event().work_ref]]) {
  const h=await setup(),s=h.state;s.automation.consumed=consumed;h.state=s;
  await assert.rejects(h.worker.run('status'),/AUTOMATION_STATE_INVALID_NO_RESET/);assert.deepEqual(h.state,s);
 }
});

for(const [kind,block,unblock] of [
 ['draft',h=>h.page.edit('user draft'),h=>h.page.edit('')],
 ['IME',h=>h.page.doc.emit({type:'compositionstart',target:h.page.editor}),h=>h.page.doc.emit({type:'compositionend',target:h.page.editor})],
 ['busy',h=>h.busy=h.page.add(h.page.doc,'button',{'data-testid':'stop-button'}),h=>h.page.doc.removeChild(h.busy)]
])test('automatic wait never changes '+kind+' and resumes only before intent',async()=>{
 const h=await setup();h.publish();block(h);h.page.clock.now+=2100;await h.tick();
 assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].status,'waiting');
 unblock(h);h.page.clock.now+=2100;await h.wake();
 if(kind==='draft'){assert.equal(h.page.clicks,0);assert.equal(h.page.choiceButtons().length,2);}
 else assert.equal(h.page.clicks,1);
});
test('different destination and duplicate target refuse without any send',async()=>{
 const h=await setup();h.publish();h.page.navigate(OTHER);await h.tick();assert.equal(h.page.clicks,0);
 h.io.exactTabs=async()=>[{id:1},{id:2}];await h.tick();assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.error,'TARGET_NOT_UNIQUE_OR_OPEN');
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

test('changed batch membership retires only that ID while independent Work survives restart and epoch reset',async()=>{
 for(const change of ['members','requested']) {
  const h=await setup(),bad=batch(),good=event(2),feed=h.io.feed;h.publish(bad);h.publish(good);
  let currentEpoch=epoch;
  h.io.feed=async q=>{
   if(q?.epoch && q.epoch!==currentEpoch)return {epoch:currentEpoch,reset:true,cursor:0,events:[]};
   const f=structuredClone(await feed(q));f.epoch=currentEpoch;
   if(q?.check===bad.batch_ref) {
    if(change==='members')f.events[0].members[0].work_ref='work-'+'f'.repeat(16);
    else {f.events[0].requested++;f.events[0].not_submitted++;}
   }
   return f;
  };
  await h.tick();assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,brief(good));
  assert.deepEqual(h.state.automation.deliveries,[]);
  assert.deepEqual(h.state.automation.consumed,[bad.batch_ref,good.work_ref]);
  await h.wake();assert.equal(h.page.clicks,1);
  h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;currentEpoch='c'.repeat(32);
  await h.wake();await h.wake();assert.equal(h.page.clicks,1);
  h.publish(3);await h.wake();assert.equal(h.page.clicks,2);assert.equal(h.page.editor.textContent,brief(event(3)));
 }
});

test('temporary per-identity read failure keeps its pending row while an independent Work is handled',async()=>{
 const h=await setup(),first=event(),second=event(2),feed=h.io.feed;h.publish(first);h.publish(second);
 h.io.feed=async q=>q?.check===first.work_ref?{epoch,cursor:0,latest:2,events:[],
  check:{work_ref:first.work_ref,state:'retry',code:'REPORT_READ_TEMPORARY'}}:feed(q);
 await h.tick();assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,brief(second));
 assert.deepEqual(h.state.automation.consumed,[second.work_ref]);assert.equal(h.state.automation.cursor,2);
 assert.equal(h.state.automation.deliveries[0].work_ref,first.work_ref);
 assert.equal(h.state.automation.deliveries[0].code,'REPORT_READ_TEMPORARY');
 await h.wake();assert.equal(h.page.clicks,1);
 h.io.feed=feed;h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;await h.wake();
 assert.equal(h.page.clicks,2);assert.equal(h.page.editor.textContent,brief(first));
 assert.deepEqual(h.state.automation.deliveries,[]);
});

test('idle and delayed ticks persist feed progress without inspecting a closed recipient until Work is due',async()=>{
 for(const queued of [false,true]) {
  const h=await setup(60000);if(queued)h.publish();
  const calls=h.calls.length;let queries=0;
  h.io.exactTabs=async()=>{queries++;return [];};
  await h.tick();assert.equal(queries,0);assert.equal(h.calls.length,calls);
  assert.equal(h.state.automation.error,null);assert.equal(h.state.automation.cursor,queued?1:0);
  if(queued) {
   assert.equal(h.state.automation.deliveries.length,1);h.page.clock.now+=61000;
   await h.wake();assert.equal(queries,1);assert.equal(h.page.clicks,0);
   assert.equal(h.state.automation.error,'TARGET_NOT_UNIQUE_OR_OPEN');
   h.io.exactTabs=async()=>[{id:1,incognito:false}];await h.wake();assert.equal(h.page.clicks,1);
  }
 }
});

test('draining the full pending backlog clears only its stale capacity error in the pre-intent save',async()=>{
 const h=await setup(),s=h.state;s.automation.cursor=128;
 s.automation.deliveries=Array.from({length:128},(_,i)=>({...event(i+1),epoch,route:CHAT,status:'waiting',dueAt:0}));
 h.state=s;for(let i=1;i<=129;i++)h.publish(i);let committed=false,writes=0;const page=h.io.page;
 h.writeHook=()=>{assert.equal(committed,false,'no post-DOM state write');writes++;};
 h.io.page=async(b,r)=>{if(r.op==='commit')committed=true;return page(b,r);};
 await h.tick();assert.equal(h.page.clicks,1);assert.equal(writes,2);
 assert.equal(h.state.automation.cursor,128);assert.deepEqual(h.state.automation.deliveries,[]);
 assert.equal(h.state.automation.consumed.length,128);assert.equal(h.state.automation.error,null);
 h.writeHook=()=>{};h.io.page=page;h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;
 await h.wake();assert.equal(h.state.automation.cursor,129);assert.equal(h.page.clicks,2);
 const current=h.state;current.automation.error='REPORT_READ_TEMPORARY';h.state=current;
 assert.equal((await h.worker.run('status')).automation.error,'REPORT_READ_TEMPORARY');
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
test('batch survives observed newline normalization without weakening exact ownership',async()=>{
 const h=await setup(),e=batch();h.publish(e);
 h.page.onYield=()=>{h.page.editor.textContent=h.page.editor.textContent.replace(/\n/g,' ');};
 await h.tick();assert.equal(h.page.clicks,1);
 assert.equal(h.page.editor.textContent,brief(e));
 await h.wake();assert.equal(h.page.clicks,1);
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

test('actual serialized adapter preserves implicit/explicit legacy and exact v2 for both feed types',async()=>{
 for(const e of [event(),batch()])for(const version of [undefined,1,2]) {
  const h=await setup(),b=h.state.binding,ready=await h.io.page(b,{op:'prepare'});
  const r=await h.io.page(b,{op:'commit',eventId:completionId(e),reportSha:e.report_sha256,
   ...(e.batch_ref?{batch:e}:{}),...(version===undefined?{}:{noticeVersion:version}),lease:ready.lease});
  assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,version===2?shortText(e):legacyText(e));assert.equal(r.code,'SEND_CLICK_INVOKED');
 }
});
test('brief abnormal/expired metadata stays internal and invalid SHA or format version still blocks before mutation',async()=>{
 const e=batch();Object.assign(e.members[1],{result_class:'attention_required',classification_report_status:'unknown'});
 Object.assign(e.members[2],{result_class:'attention_required',classification_report_status:'missing',report_status:'missing'});delete e.members[2].report_sha256;
 Object.assign(e.members[3],{state:'expired',result_class:'unavailable',classification_report_status:'unavailable',report_status:'unavailable'});delete e.members[3].report_sha256;
 const h=await setup();h.publish(e);await h.tick();assert.equal(h.page.editor.textContent,shortText(e));assert.deepEqual(h.state.automation.deliveries,[]);assert(h.state.automation.consumed.includes(e.batch_ref));
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
