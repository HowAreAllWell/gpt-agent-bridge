import test from 'node:test';
import assert from 'node:assert/strict';
import {setup,wired,A,B,project,deferred} from './project-repair-fixture.js';
import {settle,nativeFixture} from './native-fixture.js';
import {ProjectControllers,PROJECTS_KEY} from '../extension/projects.js';
import {KEY} from '../extension/policy.js';
import {POLL} from '../extension/completion-policy.js';
import {stateStore,nativeExclusive} from '../extension/state-store.js';
const key=p=>'bridgeProjectV1:'+p.scope_id;
for(const kind of ['throws','pending'])test('independent state read '+kind+' lets B progress',async()=>{
 const f=setup();await f.enable(A);await f.enable(B);f.publish(B,2);const gate=deferred();
 f.hooks.read=async k=>{if(k===key(A)){if(kind==='throws')throw Error('A_READ');await gate.promise;}};
 const tick=f.manager.tick();await settle();assert.equal(f.pages.get(2).clicks,1);gate.resolve();await tick;
});
test('ephemeral catalog rotation does not fill permanent history or prevent old disable',async()=>{
 const f=setup();await f.enable(A);const old=structuredClone(f.state(A));
 for(let round=0;round<3;round++){f.remote=Array.from({length:32},(_,i)=>project('p'+round+'x'+i,round*32+i+20));await f.manager.catalog();}
 assert.deepEqual(f.data[PROJECTS_KEY].projects.map(p=>p.project_ref),['alpha']);
 await f.manager.run('alpha','disable');assert.equal(f.state(A).automation.enabled,false);assert.deepEqual(f.state(A).automation.deliveries,old.automation.deliveries);
});
for(const pin of ['missing','different','exact'])test('first legacy root '+pin+' preserves history and only exact proof can send',async()=>{
 const old=project('gpt-agent-bridge',3,'/original');const f=setup([old]);await f.enable(old);
 f.data[KEY]=structuredClone(f.state(old));delete f.data[PROJECTS_KEY];delete f.data[key(old)];
 f.publish(old,1);const before=structuredClone(f.data[KEY]);
 if(pin==='different')f.remote=[{...old,root:'/replacement',scope_id:'e'.repeat(64)}];
 const m=new ProjectControllers(f.io,pin==='missing'?old.project_ref:old);await m.tick();
 if(pin!=='exact'){assert.equal(f.pages.get(1).clicks,0);assert.deepEqual(f.data[KEY],before);await m.run(old.project_ref,'disable');assert.equal(f.data[KEY].automation.enabled,false);}
 else assert.equal(f.pages.get(1).clicks,1);
});
test('cross-manager native scope exclusion: disable acknowledges only after prior operation; later ticks cannot restore enabled',async()=>{
 const f=setup();await f.enable(A);f.publish(A,1);const entered=deferred(),release=deferred();let held=false;
 f.hooks.feed=async(p,q)=>{if(p.project_ref==='alpha'&&q.after!==undefined&&!held){held=true;entered.resolve();await release.promise;}};
 const tick=f.manager.tick();await entered.promise;const second=new ProjectControllers(f.io);let done=false;
 const disable=second.run('alpha','disable').then(()=>{done=true;});await settle();assert.equal(done,false);
 release.resolve();await tick;await disable;const clicks=f.pages.get(1).clicks;assert.equal(f.state(A).automation.enabled,false);
 await f.manager.tick();assert.equal(f.state(A).automation.enabled,false);assert.equal(f.pages.get(1).clicks,clicks);
});
test('native transactions reject stale writes after another writer confirmed disable; migration source stays untouched',async()=>{
 const native=nativeFixture(),original={schema:1,revision:1,automation:{enabled:true}};
 const a=stateStore(native.indexedDB,async()=>structuredClone(original),undefined,nativeExclusive(native.navigator.locks)),b=stateStore(native.indexedDB,async()=>original,undefined,nativeExclusive(native.navigator.locks));
 const stale=await a.read(KEY),fresh=await b.read(KEY);fresh.revision++;fresh.automation.enabled=false;await b.write(KEY,fresh);
 stale.revision++;await assert.rejects(a.write(KEY,stale),/STATE_CHANGED/);assert.equal((await a.read(KEY)).automation.enabled,false);assert.equal(original.automation.enabled,true);
});
test('native catalog transaction refuses a lost-index overwrite',async()=>{
 const n=nativeFixture(),a=stateStore(n.indexedDB,async()=>undefined,undefined,nativeExclusive(n.navigator.locks)),b=stateStore(n.indexedDB,async()=>undefined,undefined,nativeExclusive(n.navigator.locks));
 await a.read(PROJECTS_KEY);await b.read(PROJECTS_KEY);await b.write(PROJECTS_KEY,{version:1,projects:[B]});
 await assert.rejects(a.write(PROJECTS_KEY,{version:1,projects:[A]}),/STATE_CHANGED/);assert.deepEqual((await a.read(PROJECTS_KEY)).projects,[B]);
});
test('nonlegacy diagnostic refuses before intent and does not poison automatic notifications',async()=>{
 const f=wired();assert.equal((await f.send(A,'bind')).ok,true);f.pages.get(1).clock.now+=2100;
 const r=await f.send(A,'arm',{delayMs:0});assert.equal(r.ok,false);assert.equal(r.code,'SYNTHETIC_DIAGNOSTIC_UNSUPPORTED_PROJECT');assert.equal((await f.readState(A)).events.length,0);
 assert.equal((await f.send(A,'enable',{delayMs:0})).ok,true);f.pages.get(1).clock.now+=2100;f.publish(A,1);f.listeners.alarm({name:POLL});await settle();assert.equal(f.pages.get(1).clicks,1);
});
test('scoped explicit delayed alarm reaches original project and never replays',async t=>{
 const p=project('gpt-agent-bridge',3),f=wired([p]);const now=Date.now;Date.now=()=>f.pages.get(1).clock.now;t.after(()=>{Date.now=now;});assert.equal((await f.send(p,'bind')).ok,true);f.pages.get(1).clock.now+=2100;
 await f.send(p,'arm',{delayMs:60000});const alarm=f.alarms.find(a=>a.name.startsWith('bridge-synthetic-once:'));assert(alarm);
 f.pages.get(1).clock.now+=61000;f.listeners.alarm({name:alarm.name});await settle();assert.equal(f.pages.get(1).clicks,1);assert.equal((await f.readState(p)).events[0].status,'attempted_unknown');
 f.listeners.alarm({name:alarm.name});await settle();assert.equal(f.pages.get(1).clicks,1);
});
test('an already-created legacy index does not substitute for protected old root evidence',async()=>{
 const p=project('gpt-agent-bridge',3,'/replacement'),f=setup([p]);await f.enable(p);f.data[KEY]=structuredClone(f.state(p));delete f.data[key(p)];
 f.data[PROJECTS_KEY]={version:1,projects:[{...p,legacy:true,key:KEY}]};f.publish(p,1);
 const manager=new ProjectControllers(f.io,{...p,root:'/original',scope_id:'f'.repeat(64)});await manager.tick();
 assert.equal(f.pages.get(1).clicks,0);await manager.run(p.project_ref,'disable');assert.equal(f.data[KEY].automation.enabled,false);
});
test('two complete wireWorker instances share native locks and transactional state; acknowledged disable survives old worker',async()=>{
 const f=wired();assert.equal((await f.send(A,'enable',{delayMs:0})).ok,true);f.pages.get(1).clock.now+=2100;f.publish(A,1);
 const entered=deferred(),release=deferred();let held=false;
 f.hooks.feed=async(p,q)=>{if(p.project_ref==='alpha'&&q.after!==undefined&&!held){held=true;entered.resolve();await release.promise;}};
 const oldAlarm=f.listeners.alarm;oldAlarm({name:POLL});await entered.promise;f.rewire();let done=false;
 const disabling=f.send(A,'disable').then(r=>{assert.equal(r.ok,true);done=true;});await settle();assert.equal(done,false);
 release.resolve();await disabling;await settle();assert.equal((await f.readState(A)).automation.enabled,false);
 const clicks=f.pages.get(1).clicks;oldAlarm({name:POLL});f.listeners.alarm({name:POLL});await settle();
 assert.equal((await f.readState(A)).automation.enabled,false);assert.equal(f.pages.get(1).clicks,clicks);
});
test('native store loss after migration never resurrects the old chrome enabled snapshot',async()=>{
 const native=nativeFixture(),legacy={schema:1,revision:7,automation:{enabled:true}};
 const store=stateStore(native.indexedDB,async()=>legacy,{read:async()=>true,write:async()=>{throw Error('must not reset witness');}},nativeExclusive(native.navigator.locks));
 await assert.rejects(store.read(KEY),/TRANSACTIONAL_STATE_LOST/);
});
test('supplying missing legacy evidence still requires explicit destination authorization before resuming',async()=>{
 const old=project('gpt-agent-bridge',3,'/original'),f=setup([old]);await f.enable(old);
 f.data[KEY]=structuredClone(f.state(old));delete f.data[PROJECTS_KEY];delete f.data[key(old)];
 const quarantined=new ProjectControllers(f.io,old.project_ref);await quarantined.catalog();f.publish(old,1);
 const verified=new ProjectControllers(f.io,old);await verified.tick();assert.equal(f.pages.get(1).clicks,0);
 assert.equal(f.data[PROJECTS_KEY].projects[0].requiresRebind,true);
 await verified.run(old.project_ref,'enable',{delayMs:0});f.pages.get(1).clock.now+=2100;
 await verified.tick();assert.equal(f.pages.get(1).clicks,1);
});
test('a migrated legacy project read failure stays out of catalog and cannot stop B',async()=>{
 const old=project('gpt-agent-bridge',3,'/original'),f=setup([old,B]);await f.enable(old);await f.enable(B);
 f.data[KEY]=structuredClone(f.state(old));delete f.data[key(old)];
 f.data[PROJECTS_KEY].projects[0]={...old,key:KEY,legacy:true};f.publish(B,2);
 const m=new ProjectControllers(f.io,old);f.hooks.read=async k=>{if(k===KEY)throw Error('LEGACY_STATE_READ_FAILED');};
 await m.tick();assert.equal(f.pages.get(2).clicks,1);
});
test('two wired workers serialize a recipient switch with an old-route tick and preserve unpolled Work',async()=>{
 const f=wired();assert.equal((await f.send(A,'enable',{delayMs:0})).ok,true);
 f.pages.get(1).clock.now+=2100;f.pages.get(1).add(f.pages.get(1).doc,'button',{'data-testid':'stop-button'});
 f.publish(A,1);const entered=deferred(),release=deferred();let held=false;
 f.hooks.feed=async(p,q)=>{if(p.project_ref==='alpha'&&q.after!==undefined&&!held){held=true;entered.resolve();await release.promise;}};
 const oldAlarm=f.listeners.alarm;oldAlarm({name:POLL});await entered.promise;
 f.select(2);f.rewire();let done=false;
 const switching=f.send(A,'enable',{delayMs:0}).then(r=>{assert.equal(r.ok,true);done=true;});
 await settle();assert.equal(done,false);release.resolve();await switching;
 const state=await f.readState(A);assert.equal(state.automation.route,f.pages.get(2).location.href);
 assert.equal(state.automation.cursor,1);assert.equal(state.automation.deliveries[0].route,state.automation.route);
 assert.equal(f.pages.get(1).clicks+f.pages.get(2).clicks,0);
 f.publish(A,2);f.pages.get(2).clock.now+=2100;oldAlarm({name:POLL});f.listeners.alarm({name:POLL});await settle();
 assert.equal(f.pages.get(1).clicks,0);assert.equal(f.pages.get(2).clicks,1);
 assert.equal((await f.readState(A)).automation.cursor,2);
});
