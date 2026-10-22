import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation,draftChoiceReply} from '../extension/automation.js';
import {completionId,completionMessage} from '../extension/completion-policy.js';
import {harness,CHAT,OTHER} from './harness.js';
import {wiring,A,LEG,KEY,key,epoch as nativeEpoch,event as nativeEvent,settle} from './review-wiring-fixture.js';

const epoch='a'.repeat(32),sha='b'.repeat(64);
const event=n=>({work_ref:'work-'+n.toString(16).padStart(16,'0'),project_ref:'gpt-agent-bridge',
 sequence:n,ready_at:5,result_class:'result_ready',report_status:'readable',report_sha256:sha});
const old=(n,status='attempted_unknown')=>({...event(n),epoch,route:CHAT,status,code:'COMMIT_API_UNKNOWN_NO_RETRY',intentAt:10,outcome:'unknown'});
async function setup(delayMs=0) {
 const h=harness();h.pages.get(2).location.href=OTHER;
 let feedEpoch=epoch,events=[];
 h.io.exactTabs=async r=>[...h.pages].filter(([,p])=>p.location.href===r).map(([id])=>({id,incognito:false}));
 h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.io.receipt=async()=>assert.fail('no transcript verification');
 h.io.feed=async q=>q?.epoch && q.epoch!==feedEpoch?{epoch:feedEpoch,reset:true,events:[],cursor:0}:
  {epoch:feedEpoch,events:events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)),
   cursor:Math.max(q?.after||0,...events.filter(e=>!q?.check||completionId(e)===q.check).map(e=>e.sequence)),latest:Math.max(0,...events.map(e=>e.sequence))};
 h.worker=new Automation(h.io);await h.worker.run('enable',{delayMs});h.page.clock.now+=2100;
 return Object.assign(h,{publish(...rows){events.push(...rows);},reset(rows=[]){feedEpoch='c'.repeat(32);events=rows;},
  tick(){return h.worker.run('tick');},wake(){h.worker=new Automation(h.io);return h.worker.run('tick');}});
}
test('legacy 129 unknowns compact to IDs, never block fresh Work or replay a repeated old ID',async()=>{
 const h=await setup(),s=h.state;s.automation.deliveries=Array.from({length:129},(_,i)=>old(i+1));s.automation.cursor=129;
 s.automation.error='DELIVERY_HISTORY_FULL';h.state=s;
 assert.equal((await h.worker.run('status')).automation.error,null);
 h.publish({...event(1),sequence:130},event(131));await h.tick();
 assert.equal(h.page.clicks,1);assert.equal(h.page.editor.textContent,completionMessage({...event(131),noticeVersion:2}));
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.cursor,131);
 assert.equal(h.state.automation.error,null);assert.equal(h.state.automation.consumed.length,130);
 await h.wake();assert.equal(h.page.clicks,1);
});
test('current-epoch cursor plus pending queue are persisted atomically before any attempt',async()=>{
 const h=await setup(60000);h.publish(event(1),event(2));await h.tick();
 assert.equal(h.state.automation.cursor,2);assert.equal(h.state.automation.deliveries.length,2);
 assert.deepEqual(h.state.automation.consumed,[]);assert.equal(h.page.clicks,0);
 h.page.clock.now+=61000;const page=h.io.page;
 h.io.page=async(b,r)=>{if(r.op==='commit'){
  assert.deepEqual(h.state.automation.deliveries,[]);
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref,event(2).work_ref]);
 }return page(b,r);};
 await h.wake();assert.equal(h.page.clicks,1);await h.wake();assert.equal(h.page.clicks,1);
});
test('partial feed pages and worker swaps retain the complete undecided queue until one explicit choice',async()=>{
 const h=await setup(),feed=h.io.feed,p=h.page;p.editor.textContent='';p.add(p.editor,'p').textContent='draft';p.renderSend();
 p.onPageMessage=async m=>{const s=await h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});return draftChoiceReply(s.automation,m.offerId);};
 h.io.feed=async q=>{const r=await feed(q);if(!q?.check){r.events=r.events.slice(0,16);r.cursor=Math.max(q?.after||0,...r.events.map(e=>e.sequence));}return r;};
 h.publish(...Array.from({length:40},(_,i)=>event(i+1)));
 for(const cursor of [16,32,40]) {
  await h.wake();assert.equal(h.state.automation.cursor,cursor);assert.equal(h.state.automation.deliveries.length,cursor);
  assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.clicks,0);
 }
 p.userClick(p.choiceButtons()[1]);await settle();assert.deepEqual(h.state.automation.deliveries,[]);
 assert.equal(h.state.automation.consumed.length,40);await h.wake();assert.equal(p.choiceButtons().length,0);
});
test('known click, lost injection ACK, and lost intent ACK leave no historical row and never retry',async()=>{
 for(const seam of ['click','DOM ACK','intent ACK']) {
  const h=await setup(),page=h.io.page,write=h.io.write;h.publish(event(1));let lose=true;
  if(seam==='DOM ACK')h.io.page=async(b,r)=>{const v=await page(b,r);if(r.op==='commit')throw Error('ACK_LOST');return v;};
  if(seam==='intent ACK')h.io.write=async(k,s)=>{await write(k,s);if(lose&&s.automation?.consumed.includes(event(1).work_ref)){lose=false;throw Error('ACK_LOST');}};
  await h.tick();assert.equal(h.page.clicks,seam==='intent ACK'?0:1);
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
  h.io.page=page;h.io.write=write;await h.wake();assert.equal(h.page.clicks,seam==='intent ACK'?0:1);
  h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;h.publish(event(2));await h.wake();
  assert.equal(h.page.clicks,seam==='intent ACK'?1:2);assert.deepEqual(h.state.automation.deliveries,[]);
 }
});
test('epoch reset preserves suppression of duplicate IDs and admits distinct new Work',async()=>{
 const h=await setup();h.publish(event(1));await h.tick();h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;
 h.reset([{...event(1),sequence:1},{...event(2),sequence:2}]);await h.wake();await h.wake();
 assert.equal(h.page.clicks,2);assert.equal(h.state.automation.cursor,2);assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref,event(2).work_ref]);
});
test('legacy frozen groups compact atomically while genuine pending survives explicit recipient change',async()=>{
 const h=await setup(60000),s=h.state,rows=[old(1,'waiting'),old(2,'waiting')];
 for(const r of rows)r.noticeVersion=3;
 rows[0].merge=rows.map(r=>({id:r.work_ref,workRefs:[r.work_ref]}));rows[1].mergedInto=rows[0].work_ref;
 s.automation.deliveries=[...rows,{...event(3),epoch,route:CHAT,status:'waiting',code:'DRAFT_PRESENT',dueAt:0}];s.automation.cursor=3;h.state=s;
 h.publish(event(3));h.selected=2;await h.worker.run('enable',{delayMs:0});h.pages.get(2).clock.now+=61000;await h.wake();
 assert.equal(h.page.clicks,0);assert.equal(h.pages.get(2).clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(h.state.automation.consumed,rows.map(r=>r.work_ref).concat(event(3).work_ref));
});
test('epoch replacement rechecks unsent Work instead of deleting a still-readable undecided notification',async()=>{
 for(const retained of [false,true]) {
  const h=await setup(),p=h.page;p.editor.textContent='';p.add(p.editor,'p').textContent='draft';p.renderSend();
  p.onPageMessage=async m=>{
   const s=await h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});return draftChoiceReply(s.automation,m.offerId);
  };
  h.publish(event(1));await h.tick();assert.equal(p.choiceButtons().length,2);
  h.reset(retained?[event(1)]:[{...event(2),sequence:1}]);const feed=h.io.feed;
  if(!retained)h.io.feed=q=>q?.epoch==='c'.repeat(32)&&q.check===event(1).work_ref?
   {epoch:q.epoch,cursor:0,latest:1,events:[],check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}}:feed(q);
  await h.wake();assert.equal(h.state.automation.deliveries[0].work_ref,event(1).work_ref);
  assert.deepEqual(h.state.automation.consumed,[]);await h.wake();
  assert.equal(p.choiceButtons().length,2);assert.equal(p.clicks,0);
  const id=event(retained?1:2).work_ref;
  // The explicit click revalidates reports; the old undecided identity remains
  // until that check proves it unavailable. The replacement must also survive.
  assert(h.state.automation.deliveries.some(e=>e.work_ref===id));
  p.userClick(p.choiceButtons()[1]);await settle();assert.deepEqual(h.state.automation.deliveries,[]);
  assert(h.state.automation.consumed.includes(id));assert.equal(p.clicks,0);
 }
});
test('epoch replacement during the final report check preserves unsent Work for the next normal poll',async()=>{
 const h=await setup(),feed=h.io.feed;let once=true;h.publish(event(1));
 h.io.feed=async q=>{if(q?.check&&once){once=false;h.reset([event(1)]);}return feed(q);};
 await h.tick();assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries.length,1);
 assert.equal(h.state.automation.deliveries[0].code,'PRODUCER_EPOCH_CHANGED_WAIT_NEXT_POLL');
 assert.deepEqual(h.state.automation.consumed,[]);await h.wake();await h.wake();
 assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
});
test('legacy pending row with an older epoch is checked by exact ID against the current producer',async()=>{
 const h=await setup(),s=h.state;
 s.automation.cursor=1;s.automation.deliveries=[{...event(1),epoch:'d'.repeat(32),route:CHAT,status:'waiting',code:'DRAFT_PRESENT',dueAt:0}];
 h.state=s;h.publish(event(1));await h.wake();
 assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
});
test('a proved no-mutation refusal restores the complete pending group but never restores a lost ACK',async()=>{
 const h=await setup(),remove=h.page.window.removeEventListener;
 h.page.window.removeEventListener=undefined;h.publish(event(1),event(2));await h.tick();
 assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,'');assert.deepEqual(h.state.automation.consumed,[]);
 assert.equal(h.state.automation.deliveries.length,2);assert(h.state.automation.deliveries.every(e=>e.intentAt===undefined&&e.merge===undefined));
 await h.worker.load();h.page.window.removeEventListener=remove;await h.wake();
 assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.consumed.length,2);
});
test('legacy migration ACK loss before or after save never exposes an old identity to another attempt',async()=>{
 for(const persisted of [false,true]) {
  const h=await setup(),s=h.state,write=h.io.write;
  s.automation.deliveries=[old(1)];s.automation.cursor=1;h.state=s;h.publish(event(2));let fail=true;
  h.io.write=async(k,s)=>{if(fail&&s.automation?.consumed.includes(event(1).work_ref)){
   fail=false;if(persisted)await write(k,s);throw Error('ACK_LOST');
  }return write(k,s);};
  await assert.rejects(h.tick(),/ACK_LOST/);assert.equal(h.page.clicks,0);h.io.write=write;
  await h.wake();assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref,event(2).work_ref]);
 }
});
test('only live pending workload can reach the queue bound; old unknown history is not counted',async()=>{
 const h=await setup(60000),s=h.state;
 s.automation.deliveries=Array.from({length:128},(_,i)=>({...event(i+1),epoch,route:CHAT,status:'waiting',code:'DRAFT_PRESENT',dueAt:1e12}));
 s.automation.cursor=128;h.state=s;h.publish(...Array.from({length:129},(_,i)=>event(i+1)));await h.tick();
 assert.equal(h.state.automation.error,'PENDING_QUEUE_FULL');assert.equal(h.state.automation.cursor,128);
 assert.equal(h.state.automation.deliveries.length,128);assert.equal(h.page.clicks,0);
 h.page.clock.now=1e12+2100;await h.tick();assert.equal(h.page.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
 assert.equal(h.state.automation.error,null);
 h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;await h.wake();h.page.clock.now+=61000;await h.wake();assert.equal(h.page.clicks,2);assert.equal(h.state.automation.cursor,129);
});
test('native migration and popup/status projection do not expose consumed identity metadata or old history',async()=>{
 const f=wiring(),row={...nativeEvent(A,1),epoch:nativeEpoch,noticeVersion:4,route:CHAT,status:'attempted_unknown',intentAt:10};
 const child={...row,...nativeEvent(A,2),mergedInto:nativeEvent(A,9).work_ref};
 row.merge=[row,child].map(e=>({id:e.work_ref,workRefs:[e.work_ref]}));
 f.data[key(A)]={schema:1,boot:'boot-fixed',revision:1,binding:null,events:[],automation:{enabled:true,route:CHAT,epoch:nativeEpoch,cursor:2,delayMs:0,deliveries:[row,child]}};
 f.publish(A,3);const w=f.start();w.tick();await settle();f.advance();w.tick();await settle();
 const stored=await f.record(key(A));assert.deepEqual(stored.automation.deliveries,[]);assert.equal(stored.automation.consumed.length,4);
 const reply=await w.send(A,'status');assert.equal(reply.ok,true);
 const oldIds=[row.work_ref,child.work_ref,child.mergedInto];
 assert.equal(Object.hasOwn(reply.state.automation,'consumed'),false);assert(oldIds.every(id=>!JSON.stringify(reply).includes(id)));
 const observations=f.net.filter(x=>x.method==='POST').map(x=>x.body);assert(observations.length);
 assert(observations.every(x=>oldIds.every(id=>!JSON.stringify(x).includes(id)) && !Object.hasOwn(x,'consumed')));
 assert(observations.every(x=>x.deliveries.every(e=>['queued','waiting'].includes(e.status))));
 assert.equal(f.pages.get(1).clicks,1);f.refresh();const next=f.start();next.tick();await settle();f.advance();next.tick();await settle();
 assert.equal(f.pages.get(1).clicks,0);assert.deepEqual((await f.record(key(A))).automation.consumed,stored.automation.consumed);
});
test('read-only legacy synthetic Inspect cannot leak unmigrated real history through its early return',async()=>{
 const row={...nativeEvent(LEG,1),epoch:nativeEpoch,route:CHAT,status:'attempted_unknown',intentAt:10};
 for(const deliveries of [[row],null,[null]]) {
  const f=wiring([LEG]),state={schema:1,boot:'boot-fixed',revision:1,binding:null,
   events:[{id:'test-00000000-0000-0000-0000-000000000000',route:CHAT,status:'attempted_unknown',code:'COMMIT_OUTCOME_UNKNOWN'}],
   automation:{enabled:false,route:CHAT,epoch:nativeEpoch,cursor:1,delayMs:0,deliveries}};
  f.data[KEY]=structuredClone(state);const w=f.start(LEG),reply=await w.send(LEG,'inspect');
  if(deliveries?.[0]) {
   assert.equal(reply.ok,true);assert.deepEqual(reply.state.automation.deliveries,[]);
   assert(!JSON.stringify(reply).includes(row.work_ref));
  }else assert.equal(reply.code,'AUTOMATION_STATE_INVALID_NO_RESET');
  assert.deepEqual((await f.record(KEY)).automation,state.automation);assert.equal(f.scripts.length,0);
 }
});
test('P2: duplicate pending raw IDs across old epochs are suppressed before reset, preserving other pending Work',async()=>{
 const h=await setup(),s=h.state,writes=[],write=h.io.write;
 s.automation.epoch='b'.repeat(32);s.automation.cursor=2;
 s.automation.deliveries=[
  {...event(1),epoch,route:CHAT,status:'queued',dueAt:0},
  {...event(1),sequence:2,epoch:'b'.repeat(32),route:CHAT,status:'waiting',dueAt:0},
  {...event(4),sequence:1,epoch:'b'.repeat(32),route:CHAT,status:'waiting',dueAt:0}];
 h.state=s;h.reset([event(1),event(2),{...event(4),sequence:3}]);
 h.io.write=async(k,s)=>{writes.push(structuredClone(s.automation));return write(k,s);};
 await h.wake();assert.equal(h.page.clicks,0);await h.worker.load();
 assert.equal(h.state.automation.epoch,'c'.repeat(32));assert.equal(h.state.automation.cursor,0);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
 assert.deepEqual(h.state.automation.deliveries.map(completionId),[event(4).work_ref]);
 assert(writes.every(a=>new Set(a.deliveries.map(completionId)).size===a.deliveries.length));
 await h.wake();assert.equal(h.page.clicks,1);
 assert(!h.page.editor.textContent.includes(event(1).work_ref));
 assert(h.page.editor.textContent.includes(event(2).work_ref));assert(h.page.editor.textContent.includes(event(4).work_ref));
 assert.deepEqual(h.state.automation.deliveries,[]);
 h.io.boot=async()=>'new-browser-boot';await h.wake();await h.wake();assert.equal(h.page.clicks,1);
});
test('P2: obsolete malformed historical group links cannot block new Work or resurrect old group identities',async()=>{
 const h=await setup(),s=h.state,rows=[old(1),old(2)];
 for(const row of rows)row.noticeVersion=3;
 rows[0].merge=rows.map(row=>({id:row.work_ref,workRefs:[row.work_ref]}));
 rows[1].mergedInto=event(9).work_ref;
 s.automation.cursor=2;s.automation.deliveries=rows;h.state=s;
 h.publish({...event(1),sequence:3},{...event(2),sequence:4},{...event(3),sequence:5},{...event(9),sequence:6});
 await h.wake();assert.equal(h.page.clicks,1);
 assert.equal(h.page.editor.textContent,completionMessage({...event(3),noticeVersion:2}));
 assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(new Set(h.state.automation.consumed),new Set([1,2,3,9].map(n=>event(n).work_ref)));
 await h.worker.load();await h.wake();assert.equal(h.page.clicks,1);
});
test('normalization still rejects invalid scope, progress, suppression IDs and live pending data without writing',async()=>{
 const corrupt=[s=>s.automation.cursor=-1,s=>s.automation.epoch='bad',s=>s.automation.route=null,
  s=>s.automation.consumed=['bad'],s=>s.automation.deliveries[0].project_ref='other',
  s=>s.automation.deliveries[0].epoch='bad',s=>s.automation.deliveries[0].report_sha256='bad'];
 for(const change of corrupt) {
  const h=await setup(),s=h.state;
  s.automation.deliveries=[{...event(1),epoch,route:CHAT,status:'waiting',dueAt:0}];change(s);h.state=s;
  let writes=0;h.io.write=async()=>{writes++;throw Error('UNEXPECTED_WRITE');};
  await assert.rejects(h.worker.run('status'),/AUTOMATION_STATE_INVALID_NO_RESET/);
  assert.deepEqual(h.state,s);assert.equal(writes,0);assert.equal(h.page.clicks,0);
 }
});
