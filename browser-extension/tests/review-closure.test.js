import test from 'node:test';
import assert from 'node:assert/strict';
import {stateStore as rawStore,nativeExclusive} from '../extension/state-store.js';
import {wiring,primitives,A,B,LEG,KEY,INDEX,WITNESS,key,epoch,event,defer,settle,CHAT,OTHER} from './review-wiring-fixture.js';
const storeLock=nativeExclusive(primitives().native.navigator.locks);
const stateStore=(db,read,witness)=>rawStore(db,read,witness,storeLock);
const snapshot=(project,enabled=true)=>({schema:1,boot:'boot-fixed',revision:7,binding:null,events:[],automation:{enabled,route:CHAT,epoch,cursor:0,delayMs:0,deliveries:[]}});

test('PASS CAS compares exact expected value and next revision; rejected stale writer does not mutate source or DB',async()=>{
 const p=primitives(),legacy=snapshot(A),a=stateStore(p.native.indexedDB,async()=>structuredClone(legacy)),b=stateStore(p.native.indexedDB,async()=>structuredClone(legacy));
 const stale=await a.read(key(A)),fresh=await b.read(key(A));fresh.revision++;fresh.automation.enabled=false;await b.write(key(A),fresh);stale.revision++;await assert.rejects(a.write(key(A),stale),/STATE_CHANGED/);assert.equal((await p.record(key(A))).automation.enabled,false);assert.equal(legacy.automation.enabled,true);
 const valid=await a.read(key(A));await assert.rejects(a.write(key(A),{...valid,revision:valid.revision+2}),/STATE_CHANGED/);assert.equal((await p.record(key(A))).revision,fresh.revision);
});
test('PASS partial lazy import never overwrites an already imported authoritative unknown',async()=>{
 const p=primitives(),local={[key(A)]:snapshot(A),[key(B)]:snapshot(B)},w={value:false},witness={read:async()=>w.value,write:async x=>w.value=x};
 const a=stateStore(p.native.indexedDB,async k=>structuredClone(local[k]),witness);let s=await a.read(key(A));s.revision++;s.automation.enabled=false;s.events=[];s.automation.deliveries=[{...event(A,1),epoch,route:CHAT,status:'attempted_unknown',intentAt:10,noticeVersion:4}];await a.write(key(A),s);
 const b=stateStore(p.native.indexedDB,async k=>structuredClone(local[k]),witness);assert.deepEqual(await b.read(key(A)),s);assert.deepEqual(await b.read(key(B)),local[key(B)]);assert.equal(w.value,true);assert.equal(local[key(A)].automation.enabled,true);
});
test('PASS IDB commit acknowledgement lost: actual committed unknown survives a second store',async()=>{
 const p=primitives(),local=snapshot(A),a=stateStore(p.native.indexedDB,async()=>local);const s=await a.read(key(A));s.revision++;s.automation.enabled=false;s.automation.deliveries=[{...event(A,1),epoch,route:CHAT,status:'attempted_unknown',intentAt:11,noticeVersion:4}];
 // Commit executes in fake-indexeddb; suppress only the promise acknowledgement to caller.
 const operation=a.write(key(A),s).then(()=>{throw Error('ACK_LOST_AFTER_COMMIT');});await assert.rejects(operation,/ACK_LOST/);
 const b=stateStore(p.native.indexedDB,async()=>local);assert.deepEqual(await b.read(key(A)),s);assert.equal(local.automation.deliveries.length,0);
});
test('PASS full wiring confirmed disable waits for old project lock and survives both workers subsequent ticks',async()=>{
 const f=wiring(),a=f.start();await f.enable(a,A);f.publish(A,1);const enter=defer(),release=defer();let once=true;f.hooks.feed=async(p,q)=>{if(p.project_ref==='alpha'&&q.after!==undefined&&once){once=false;enter.resolve();await release.promise;}};
 a.tick();await enter.promise;const b=f.start();let acknowledged=false;const disabling=b.send(A,'disable').then(r=>{assert(r.ok);acknowledged=true;});await settle();assert.equal(acknowledged,false);release.resolve();await disabling;assert.equal((await f.record(key(A))).automation.enabled,false);const clicks=f.pages.get(1).clicks;a.tick();b.tick();await settle();assert.equal((await f.record(key(A))).automation.enabled,false);assert.equal(f.pages.get(1).clicks,clicks);console.log('disable acknowledged after predecessor ended; later enabled=false; clicks stable',clicks);
});
test('full wiring lost commit response preserves suppression through rewire and refresh without history',async()=>{
 const f=wiring(),a=f.start();await f.enable(a,A);f.publish(A,1);let lost=true;
 f.hooks.scriptAfter=async(s)=>{if(s.args[0].op==='commit'&&lost){lost=false;throw Error('COMMIT_RESPONSE_LOST');}};
 a.tick();await settle();const before=await f.record(key(A));assert.deepEqual(before.automation.deliveries,[]);
 assert.deepEqual(before.automation.consumed,[event(A,1).work_ref]);assert.equal(f.pages.get(1).clicks,1);
 const oldBinding=structuredClone(before.binding),injections=f.scripts.length;
 f.refresh();const b=f.start();b.tick();await settle();f.advance();b.tick();await settle();const after=await f.record(key(A));
 assert.deepEqual(after.automation.consumed,before.automation.consumed);assert.deepEqual(after.automation.deliveries,[]);
 assert.equal(f.pages.get(1).clicks,0);assert.equal(f.scripts.length,injections);assert.deepEqual(after.binding,oldBinding);
 // Idle suppression needs no page injection. A new identity, not the consumed
 // one, triggers exact-document rebind and current empty-editor checks.
 f.publish(A,2);b.tick();await settle();const rebound=await f.record(key(A));
 assert.equal(rebound.binding.documentId,f.docs.get(1));assert.equal(rebound.binding.route,CHAT);
 assert.equal(f.pages.get(1).clicks,1);assert.deepEqual(rebound.automation.deliveries,[]);
 assert.deepEqual(rebound.automation.consumed,[event(A,1).work_ref,event(A,2).work_ref]);
 assert(f.scripts.slice(injections).every(s=>s.id===1&&s.doc===f.docs.get(1)));
 assert(!f.pages.get(1).editor.textContent.includes(event(A,1).work_ref));
 assert(f.pages.get(1).editor.textContent.includes(event(A,2).work_ref));
 assert.deepEqual((await f.record(key(A))).automation.consumed,[event(A,1).work_ref,event(A,2).work_ref]);
 b.tick();await settle();assert.equal(f.pages.get(1).clicks,1);
});
test('native dispatch preserves old unknown with or without route while a distinct same-Chat Work sends once',async()=>{
 for(const oldRoute of [CHAT,undefined]) {
  const f=wiring(),s=snapshot(A),old={...event(A,1),epoch,noticeVersion:4,route:oldRoute,status:'attempted_unknown',
   intentAt:10,outcome:'unknown',code:'COMMIT_API_UNKNOWN_NO_RETRY'};
  s.automation.deliveries=[old];s.automation.cursor=1;f.data[key(A)]=s;
  f.publish(A,1);f.publish(A,2);const w=f.start();w.tick();await settle();f.advance();w.tick();await settle();
  const rows=(await f.record(key(A))).automation.deliveries;
  assert.deepEqual(rows,[]);assert.deepEqual((await f.record(key(A))).automation.consumed,[old.work_ref,event(A,2).work_ref]);
  assert.equal(f.pages.get(1).clicks,1);
  assert(!f.pages.get(1).editor.textContent.includes(old.work_ref));
  f.refresh();const next=f.start();next.tick();await settle();f.advance();next.tick();await settle();
  assert.deepEqual((await f.record(key(A))).automation.deliveries,rows);
  assert.equal(f.pages.get(1).clicks,0);assert(f.scripts.every(x=>x.op));
 }
});
test('PASS full wiring refresh of unique same URL automatically rebinds and later sends without manual bind',async()=>{
 const f=wiring(),w=f.start();await f.enable(w,A);const old=(await f.record(key(A))).binding.documentId;f.refresh();f.publish(A,1);w.tick();await settle();assert.notEqual((await f.record(key(A))).binding.documentId,old);assert.equal(f.pages.get(1).clicks,1);f.advance();w.tick();await settle();assert.equal(f.pages.get(1).clicks,1);
});
test('full wiring click retires its row across new document and worker without transcript injection',async()=>{
 const f=wiring(),w=f.start();await f.enable(w,A);f.publish(A,1);w.tick();await settle();
 assert.deepEqual((await f.record(key(A))).automation.deliveries,[]);assert.equal(f.pages.get(1).clicks,1);
 const injections=f.scripts.length,oldBinding=structuredClone((await f.record(key(A))).binding);
 f.refresh();const next=f.start();next.tick();await settle();f.advance(180000);next.tick();await settle();
 assert.deepEqual((await f.record(key(A))).automation.consumed,[event(A,1).work_ref]);
 assert.equal(f.pages.get(1).clicks,0);assert.equal(f.scripts.length,injections);
 assert.deepEqual((await f.record(key(A))).binding,oldBinding);
 f.publish(A,2);next.tick();await settle();const rebound=await f.record(key(A));
 assert.equal(rebound.binding.documentId,f.docs.get(1));assert.equal(rebound.binding.route,CHAT);
 assert.equal(f.pages.get(1).clicks,1);assert.deepEqual(rebound.automation.deliveries,[]);
 assert(f.scripts.slice(injections).every(s=>s.id===1&&s.doc===f.docs.get(1)));
 assert.deepEqual((await f.record(key(A))).automation.consumed,[event(A,1).work_ref,event(A,2).work_ref]);
 assert(!f.pages.get(1).editor.textContent.includes(event(A,1).work_ref));
 assert(f.pages.get(1).editor.textContent.includes(event(A,2).work_ref));
 next.tick();await settle();assert.equal(f.pages.get(1).clicks,1);
 assert.equal((await next.send(A,'verify')).code,'INVALID_MESSAGE');
});
test('PASS disabled refreshed Chat stays disabled, duplicate same URL fails closed, changed URL does not retarget',async()=>{
 const f=wiring(),w=f.start();await f.enable(w,A);assert((await w.send(A,'disable')).ok);f.refresh();f.publish(A,1);w.tick();await settle();assert.equal(f.pages.get(1).clicks,0);assert.equal((await f.record(key(A))).automation.enabled,false);
 await f.enable(w,A);f.publish(A,2);f.pages.get(2).location.href=CHAT;w.tick();await settle();assert.equal((await f.record(key(A))).automation.error,'TARGET_NOT_UNIQUE_OR_OPEN');assert.equal(f.pages.get(1).clicks,0);
 f.pages.get(2).location.href=OTHER;f.pages.get(1).location.href=OTHER;w.tick();await settle();assert.equal(f.pages.get(1).clicks,0);assert.equal((await f.record(key(A))).automation.route,CHAT);
});
test('old uncertain identity stays suppressed while a new receiver sends a different Work once',async()=>{
 const f=wiring(),w=f.start();await f.enable(w,A);f.publish(A,1);let lose=true;
 f.hooks.scriptAfter=async(s)=>{if(lose&&s.args[0].op==='commit'){lose=false;throw Error('ACK_LOST');}};
 w.tick();await settle();assert.deepEqual((await f.record(key(A))).automation.deliveries,[]);
 f.selected=2;const r=await w.send(A,'enable',{delayMs:0});assert.equal(r.ok,true);assert.equal(r.state.automation.route,OTHER);
 assert.equal(Object.hasOwn(r.state.automation,'consumed'),false);assert.equal(f.pages.get(2).clicks,0);
 f.publish(A,2);f.advance();w.tick();await settle();w.tick();await settle();
 assert.deepEqual((await f.record(key(A))).automation.consumed,[event(A,1).work_ref,event(A,2).work_ref]);
 assert.equal(f.pages.get(1).clicks,1);assert.equal(f.pages.get(2).clicks,1);
});
test('PASS fresh unverified legacy later proof does not auto enable',async()=>{
 const f=wiring([LEG]);f.data[KEY]=snapshot(LEG);const a=f.start();assert((await a.send(LEG,'status')).ok);f.publish(LEG,1);const b=f.start(LEG);b.tick();await settle();assert.equal(f.pages.get(1).clicks,0);assert.equal((await f.record(INDEX)).projects[0].requiresRebind,true);
});
test('legacy index without proof stays durably quarantined after exact proof until explicit enable',async()=>{
 const f=wiring([LEG]);f.data[KEY]=snapshot(LEG);f.data[INDEX]={version:1,projects:[{...LEG,legacy:true,key:KEY}]};
 const original=structuredClone(f.data[KEY]),a=f.start();assert((await a.send(LEG,'status')).ok);
 assert.equal((await f.record(INDEX)).projects[0].requiresRebind,true);
 f.publish(LEG,1);const b=f.start(LEG);b.tick();await settle();f.advance();b.tick();await settle();
 assert.equal(f.pages.get(1).clicks,0);assert.deepEqual(f.data[KEY],original);
 assert.equal((await f.record(INDEX)).projects[0].root,LEG.root);
 // A failed explicit enable cannot authorize automatic sending.
 f.selected=1;f.pages.get(1).location.href='https://foreign.invalid/';assert.equal((await b.send(LEG,'enable',{delayMs:0})).ok,false);
 assert.equal((await f.record(INDEX)).projects[0].requiresRebind,true);
 f.pages.get(1).location.href=CHAT;await f.enable(b,LEG);assert.equal((await f.record(INDEX)).projects[0].requiresRebind,undefined);
 b.tick();await settle();assert.equal(f.pages.get(1).clicks,1);
});
test('PASS ordinary total DB loss with already observed witness fails closed',async()=>{
 const f=wiring(),a=f.start();await f.enable(a,A);assert((await a.send(A,'disable')).ok);assert.equal(f.data[WITNESS],true);await f.loseDB();const b=f.start();const r=await b.send(A,'status');assert.equal(r.ok,false);assert.equal(r.code,'TRANSACTIONAL_STATE_LOST_NO_LEGACY_REPLAY');
});
test('full wiring initializer owns delayed witness through acknowledgment; no stale opener can cross confirmed disable and DB loss',async()=>{
 const f=wiring();f.data[key(A)]=snapshot(A);f.data[INDEX]={version:1,projects:[{...A,legacy:false,key:key(A)}]};
 const enter=defer(),release=defer();let first=true;
 f.hooks.localRead=async(k,captured)=>{if(k===WITNESS&&first){first=false;assert.equal(captured,undefined);enter.resolve();await release.promise;}};
 const delayed=f.start();await enter.promise;const active=f.start();let acknowledged=false;
 const disabling=active.send(A,'disable').then(r=>{assert(r.ok);acknowledged=true;});
 await settle();assert.equal(acknowledged,false);assert.equal(f.data[WITNESS],undefined);
 assert.equal(f.log.filter(([op,name])=>op==='acquire'&&name==='bridge-notice:storage-initialize').length,1);
 release.resolve();await disabling;assert.equal((await f.record(key(A))).automation.enabled,false);
 assert.equal(f.data[WITNESS],true);await f.loseDB();
 assert.equal((await delayed.send(A,'status')).ok,false);
 const fresh=f.start();assert.equal((await fresh.send(A,'status')).code,'TRANSACTIONAL_STATE_LOST_NO_LEGACY_REPLAY');
 assert.equal(f.data[key(A)].automation.enabled,true);
});
for(const mode of ['throw','hang'])test('PASS full wiring A legacy storage read '+mode+' does not stop independent B',async()=>{
 const f=wiring();f.data[key(A)]=snapshot(A);f.data[INDEX]={version:1,projects:[{...A,legacy:false,key:key(A)}]};const w=f.start();await f.enable(w,B);const entered=defer(),release=defer();f.hooks.localRead=async k=>{if(k===key(A)){entered.resolve();if(mode==='throw')throw Error('A_STATE_READ');await release.promise;}};f.publish(B,2);w.tick();await entered.promise;await settle();assert.equal(f.pages.get(2).clicks,1);release.resolve();await settle();
});
test('PASS complete wiring shared route lock serializes separate projects across two workers',async()=>{
 const f=wiring(),a=f.start(),b=f.start();await f.enable(a,A,1);await f.enable(b,B,1);f.publish(A,1);f.publish(B,2);const enter=defer(),release=defer();let once=true,bCalls=0;f.hooks.feed=async(p,q)=>{if(p.project_ref==='alpha'&&q.after!==undefined&&once){once=false;enter.resolve();await release.promise;}if(p.project_ref==='beta'&&q.after!==undefined)bCalls++;};a.tick();await enter.promise;b.tick();await settle();assert.equal(bCalls,0);release.resolve();await settle();assert.equal(f.pages.get(1).clicks,1);assert(bCalls>0);assert.equal((await f.record(key(B))).automation.deliveries[0].status,'waiting');
});
test('legacy v1-v3 intent groups compact once to IDs while the original import source remains unchanged',async()=>{
 const f=wiring([LEG]),s=snapshot(LEG);s.automation.deliveries=[1,2,3,3].map((v,i)=>({...event(LEG,i+1),noticeVersion:v,epoch,route:CHAT,status:'attempted_unknown',intentAt:10}));
 const [a,b,c,d]=s.automation.deliveries;c.merge=[c,d].map(e=>({id:e.work_ref,workRefs:[e.work_ref]}));d.mergedInto=c.work_ref;
 f.data[KEY]=structuredClone(s);const w=f.start(LEG);w.tick();await settle();f.refresh();w.tick();await settle();f.advance();w.tick();await settle();
 const actual=await f.record(KEY);assert.deepEqual(actual.automation.deliveries,[]);
 assert.deepEqual(actual.automation.consumed,s.automation.deliveries.map(e=>e.work_ref));assert.equal(actual.automation.cursor,s.automation.cursor);
 assert.deepEqual(f.data[KEY],s);assert.equal(f.pages.get(1).clicks,0);assert.equal((await w.send(LEG,'verify')).code,'INVALID_MESSAGE');
});
test('PASS witness ACK lost after local write prevents DB-loss replay, without mutating original legacy rows',async()=>{
 const f=wiring();f.data[key(A)]=snapshot(A);const before=structuredClone(f.data[key(A)]);let fail=true;f.hooks.localWrite=async v=>{if(v[WITNESS]&&fail){fail=false;throw Error('WITNESS_ACK_LOST');}};const a=f.start();const r=await a.send(A,'status');assert.equal(r.ok,false);assert.equal(f.data[WITNESS],true);await f.loseDB();const b=f.start();const second=await b.send(A,'status');assert.equal(second.code,'TRANSACTIONAL_STATE_LOST_NO_LEGACY_REPLAY');assert.deepEqual(f.data[key(A)],before);
});
test('PASS missing locks or IDB fails closed before any page mutation',async()=>{
 for(const kind of ['locks','db']){const f=wiring(),native={...f.native,...(kind==='locks'?{navigator:{}}:{indexedDB:undefined})},w=f.start(null,native);const r=await w.send(A,'enable',{delayMs:0});assert.equal(r.ok,false);assert.equal(r.code,kind==='locks'?'NATIVE_LOCKS_REQUIRED':'TRANSACTIONAL_STORAGE_REQUIRED');assert.equal(f.scripts.length,0);}
});
test('route changed while tick waits requeues under actual target before DOM; another worker cannot overlap',async()=>{
 const f=wiring(),a=f.start();await f.enable(a,B,2);await f.enable(a,A,1);const holding=defer(),unlock=defer();const lock=f.native.navigator.locks.request('bridge-notice:route:'+CHAT,{mode:'exclusive'},async()=>{holding.resolve();await unlock.promise;});await holding.promise;a.tick();await settle();
 // Recipient switching also owns the old route: it must wait for this lock.
 let switched=false;const switching=f.enable(a,A,2).then(()=>{switched=true;});
 await settle();assert.equal(switched,false);
 unlock.resolve();await lock;await switching;
 // Give alpha the first commit gate; publish beta only after alpha holds
 // the shared destination lock, so this test measures exclusion rather than
 // which project wins the shared page's first-edit race.
 f.publish(A,1);const atCommit=defer(),continueCommit=defer();let held=false,wrongLock=false,correctLock=false;f.hooks.scriptBefore=async s=>{if(s.args[0].op==='commit'&&s.args[0].project==='alpha'&&!held){held=true;const active=new Set();for(const [op,name] of f.log){if(op==='acquire')active.add(name);if(op==='release')active.delete(name);}wrongLock=active.has('bridge-notice:route:'+CHAT)&&!active.has('bridge-notice:route:'+OTHER);correctLock=active.has('bridge-notice:route:'+OTHER)&&!active.has('bridge-notice:route:'+CHAT);assert.equal(s.args[0].route,OTHER);atCommit.resolve();await continueCommit.promise;}};
 a.tick();await atCommit.promise;assert.equal(wrongLock,false);assert.equal(correctLock,true);f.publish(B,2);const b=f.start();b.tick();await settle();assert.equal(f.pages.get(2).clicks,0);assert.equal(f.pages.get(2).editor.textContent,'');continueCommit.resolve();await settle();assert.equal(f.pages.get(2).clicks,1);
});
test('PASS full wiring catalog rotation does not persist unbound discoveries or block saved disable',async()=>{
 const f=wiring(),w=f.start();await f.enable(w,A);for(let round=0;round<3;round++){f.remote=Array.from({length:32},(_,i)=>({project_ref:'p'+round+'_'+i,root:'/synthetic/'+round+'/'+i,scope_id:(round*32+i+20).toString(16).padStart(64,'0')}));assert((await w.send(null,'status')).ok);}assert.equal((await f.record(INDEX)).projects.length,1);assert((await w.send(A,'disable')).ok);assert.equal((await f.record(key(A))).automation.enabled,false);
});
test('PASS full wiring root mismatch refuses legacy sends and still permits disable',async()=>{
 const f=wiring([LEG]);f.data[KEY]=snapshot(LEG);const w=f.start({...LEG,root:'/old-other-root',scope_id:'d'.repeat(64)});f.publish(LEG,1);w.tick();await settle();assert.equal(f.pages.get(1).clicks,0);assert.equal((await w.send(LEG,'enable',{delayMs:0})).code,'PROJECT_UNAVAILABLE_HISTORY_RETAINED');assert((await w.send(LEG,'disable')).ok);assert.equal((await f.record(KEY)).automation.enabled,false);
});
test('PASS full wiring nonlegacy diagnostic is rejected before intent while scoped legacy alarm runs once',async t=>{
 const f=wiring([A,LEG]),w=f.start();assert((await w.send(A,'bind')).ok);assert.equal((await w.send(A,'arm',{delayMs:0})).code,'SYNTHETIC_DIAGNOSTIC_UNSUPPORTED_PROJECT');assert.equal((await f.record(key(A))).events.length,0);
 const now=Date.now;Date.now=()=>f.pages.get(1).clock.now;t.after(()=>Date.now=now);assert((await w.send(LEG,'bind')).ok);f.advance();assert((await w.send(LEG,'arm',{delayMs:60000})).ok);const alarm=f.alarms.find(x=>x.name.startsWith('bridge-synthetic-once:'));assert(alarm);f.advance(61000);w.listeners.alarm({name:alarm.name});await settle();assert.equal(f.pages.get(1).clicks,1);w.listeners.alarm({name:alarm.name});await settle();assert.equal(f.pages.get(1).clicks,1);
});
test('PASS timed-out DOM remains outstanding after lock release and confirmed disable; no new attempt or enabled restoration',async t=>{
 const f=wiring(),a=f.start();await f.enable(a,A);f.publish(A,1);const enter=defer(),release=defer();let attempts=0,lateResult;f.hooks.scriptAfter=async(s,result)=>{if(s.args[0].op==='commit')lateResult=result;};f.hooks.scriptBefore=async s=>{if(s.args[0].op==='commit'){attempts++;enter.resolve();await release.promise;}};
 const original=setTimeout;globalThis.setTimeout=(fn,ms,...args)=>original(fn,ms===8000?10:ms,...args);t.after(()=>globalThis.setTimeout=original);
 a.tick();await enter.promise;await new Promise(r=>original(r,35));await settle();assert.deepEqual((await f.record(key(A))).automation.deliveries,[]);assert.deepEqual((await f.record(key(A))).automation.consumed,[event(A,1).work_ref]);assert.equal(f.pages.get(1).clicks,0);
 const b=f.start();b.tick();await settle();assert.equal(attempts,1);assert((await b.send(A,'disable')).ok);release.resolve();await settle();assert.equal(f.pages.get(1).clicks,0);assert.equal(lateResult.stage,'blocked_before_mutation');assert.equal(lateResult.code,'STALE_PAGE_OBSERVATION');assert.equal(attempts,1);assert.equal((await f.record(key(A))).automation.enabled,false);assert.deepEqual((await f.record(key(A))).automation.deliveries,[]);assert.deepEqual((await f.record(key(A))).automation.consumed,[event(A,1).work_ref]);console.log('late outstanding DOM was blocked by replaced lease; no new attempt, enabled=false and unknown retained; not proof of cancellation for already-running DOM');
});

for(const action of ['arm','alarm','retry'])test('routed '+action+' rechecks binding after waiting and never operates under old route',async()=>{
 const {ProjectControllers}=await import('../extension/projects.js');
 const {setup}=await import('./project-repair-fixture.js');
 const f=setup([LEG]),p={...LEG,key:key(LEG)},manager=f.manager;
 await manager.run(LEG.project_ref,'bind');
 const entered=defer(),release=defer();let first=true,called=0,heldRoute;
 const exclusive=f.io.exclusive;
 f.io.exclusive=async(name,fn)=>{
   if(name==='route:'+CHAT&&first){first=false;entered.resolve();await release.promise;}
   if(name.startsWith('route:')){heldRoute=name;try{return await fn();}finally{heldRoute=null;}}
   return exclusive?exclusive(name,fn):fn();
 };
 // Replace only the final action to observe its actual owned lock; production
 // route selection, reads, and project ownership still execute.
 const controller=manager.controller(p);controller.run=async(a)=>{called++;assert.equal(a,action);assert.equal(heldRoute,'route:'+OTHER);return f.data[p.key];};
 const operation=manager.run(LEG.project_ref,action,{delayMs:0});await entered.promise;
 f.data[p.key].binding.route=OTHER;release.resolve();await operation;assert.equal(called,1);
});
