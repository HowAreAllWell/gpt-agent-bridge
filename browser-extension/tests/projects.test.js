import test from 'node:test';
import assert from 'node:assert/strict';
import {ProjectControllers,PROJECTS_KEY} from '../extension/projects.js';
import {KEY} from '../extension/policy.js';
import {completionId} from '../extension/completion-policy.js';
import {harness,CHAT,OTHER} from './harness.js';
import {nativeExclusive} from '../extension/state-store.js';
const epoch='a'.repeat(32);
const row=(ref,scope,root)=>({project_ref:ref,scope_id:scope.repeat(64),root});
const A=row('alpha','a','/synthetic/a'),B=row('beta','b','/synthetic/b');
function fixture(projects=[A,B]) {
 const data={},homes=new Map(),events=new Map();let remote=projects;
 for(const [i,p] of projects.entries()) {
  const h=harness();h.page.location.href=i?OTHER:CHAT;events.set(p.project_ref,[]);
  h.io.exactTabs=async r=>r===h.page.location.href?[{id:1,incognito:false}]:[];
  h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
  const page=h.io.page;h.io.page=(b,r)=>page(b,{...r,project:b.project});
  h.io.feed=async q=>{const all=events.get(p.project_ref),found=all.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0));return {epoch,events:found,cursor:Math.max(q?.after||0,...found.map(e=>e.sequence)),latest:Math.max(0,...all.map(e=>e.sequence))};};
  homes.set(p.project_ref,h);
 }
 const io={read:async k=>structuredClone(data[k]),write:async(k,v)=>{data[k]=structuredClone(v);},catalog:async()=>({projects:remote}),forProject:p=>homes.get(p.project_ref).io};
 const manager=new ProjectControllers(io,'gpt-agent-bridge');
 return {data,homes,io,manager,remote:v=>remote=v,
  publishEvent(p,e){events.get(p.project_ref).push(e);},
  publish(p,n){events.get(p.project_ref).push({work_ref:'work-'+String(n).padStart(16,'0'),project_ref:p.project_ref,sequence:n,ready_at:1,report_sha256:'b'.repeat(64),result_class:'result_ready',report_status:'readable'});},
  async enable(p){await manager.run(p.project_ref,'enable',{delayMs:0});homes.get(p.project_ref).page.clock.now+=2100;},
  state(p){return data['bridgeProjectV1:'+p.scope_id];}};
}
test('two registered projects keep chats, full Work refs, intents and cursors isolated',async()=>{
 const f=fixture();await f.enable(A);await f.enable(B);f.publish(A,1);f.publish(A,2);f.publish(B,3);
 await f.manager.tick();
 for(const p of [A,B]) {
  const h=f.homes.get(p.project_ref),s=f.state(p);assert.equal(h.page.clicks,1);
  assert(h.page.editor.textContent.startsWith('project_ref='+p.project_ref+'；'));
  assert.deepEqual(s.automation.deliveries,[]);
  assert.deepEqual(s.automation.consumed,p===A?['work-0000000000000001','work-0000000000000002']:['work-0000000000000003']);
 }
 assert.equal(f.state(A).automation.cursor,2);assert.equal(f.state(B).automation.cursor,3);
 assert(!f.homes.get(A.project_ref).page.editor.textContent.includes('work-0000000000000003'));
 await new ProjectControllers(f.io).tick();assert.equal(f.homes.get(A.project_ref).page.clicks,1);
});
for(const cause of ['busy','read throw','unknown'])test('A '+cause+' never prevents B dispatch',async()=>{
 const f=fixture();await f.enable(A);await f.enable(B);const a=f.homes.get('alpha');
 if(cause==='busy')a.page.add(a.page.doc,'button',{'data-testid':'stop-button'});
 if(cause==='read throw')f.manager.controller(A).io.feed=async()=>{throw Error('TEMPORARY_READ');};
 f.publish(A,1);f.publish(B,2);await f.manager.tick();
 assert.equal(f.homes.get('beta').page.clicks,1);
 if(cause!=='unknown')assert.equal(a.page.clicks,0);
});
test('adding/removing/changing a root does not enable, clear or reinterpret history',async()=>{
 const f=fixture();await f.enable(A);f.publish(A,1);await f.manager.tick();const before=structuredClone(f.state(A));
 f.remote([B,{...A,root:'/replacement',scope_id:'c'.repeat(64)}]);await f.manager.tick();
 assert.deepEqual(f.state(A),before);assert.equal((await f.manager.catalog()).find(p=>p.project_ref==='alpha').available,false);
 assert.equal(f.state(B),undefined);await assert.rejects(f.manager.run('alpha','enable',{delayMs:0}),/UNAVAILABLE/);
 assert.deepEqual((await f.manager.run('alpha','status')).state.automation.deliveries,[]);assert.deepEqual(f.state(A).automation.consumed,['work-0000000000000001']);
});
test('legacy namespace compacts v1/v2/v3 frozen messages to identity-only suppression without replay',async()=>{
 const old=row('gpt-agent-bridge','d','/old');const f=fixture([old,B]);
 const h=f.homes.get(old.project_ref);await h.bind();const state=h.state;
 state.automation={enabled:false,route:CHAT,epoch,cursor:8,delayMs:0,deliveries:[]};
 for(const [i,version] of [1,2,3].entries()) {
  if(version===3)continue;
  state.automation.deliveries.push({work_ref:'work-'+String(i+1).padStart(16,'0'),project_ref:old.project_ref,sequence:i+1,ready_at:1,report_sha256:'b'.repeat(64),result_class:'result_ready',report_status:'readable',epoch,route:CHAT,status:'attempted_unknown',intentAt:12,noticeVersion:version});
 }
 const base=state.automation.deliveries[0];
 const owner={...base,work_ref:'work-0000000000000003',sequence:3,noticeVersion:3};
 const member={...base,work_ref:'work-0000000000000004',sequence:4,noticeVersion:3,mergedInto:owner.work_ref};
 owner.merge=[owner,member].map(e=>({id:e.work_ref,workRefs:[e.work_ref]}));state.automation.deliveries.push(owner,member);
 f.data[KEY]=state;
 f.manager.legacyProject=old;
 const catalog=await f.manager.catalog();assert.equal(catalog[0].key,KEY);
 await f.manager.run(old.project_ref,'status');assert.deepEqual(f.data[KEY].automation.deliveries,[]);
 assert.deepEqual(f.data[KEY].automation.consumed,state.automation.deliveries.map(e=>e.work_ref));assert.equal(f.data[KEY].automation.cursor,8);
 await f.enable(B);f.publish(B,9);await f.manager.tick();assert.equal(f.homes.get(B.project_ref).page.clicks,1);assert.equal(h.page.clicks,0);
});
test('same Chat operations are serialized even across concurrent alarms; different Chat is independent',async()=>{
 const f=fixture();await f.enable(A);await f.enable(B);
 f.data['bridgeProjectV1:'+B.scope_id].automation.route=CHAT;
 let active=0,max=0,count=0;
 f.manager.controller=()=>({run:async()=>{active++;max=Math.max(max,active);await new Promise(r=>setImmediate(r));active--;count++;}});
 await Promise.all([f.manager.tick(),f.manager.tick()]);assert.equal(max,1);assert.equal(count,4);
});
test('catalog corruption and uncertain publication stop dispatch without reset',async()=>{
 const f=fixture();f.data[PROJECTS_KEY]={version:1,projects:[{...A,key:'some-other-project'}]};
 await assert.rejects(f.manager.tick(),/INDEX_INVALID/);assert.equal(f.homes.get('alpha').page.clicks,0);
});

test('offline status and disable retain unknown history without requiring a live catalog',async()=>{
 const f=fixture();await f.enable(A);f.publish(A,1);await f.manager.tick();const before=structuredClone(f.state(A).automation.deliveries);
 f.io.catalog=async()=>{throw Error('OFFLINE');};
 assert.equal((await f.manager.run('alpha','status')).projects[0].available,false);
 await f.manager.run('alpha','disable');assert.equal(f.state(A).automation.enabled,false);
 assert.deepEqual(f.state(A).automation.deliveries,before);await assert.rejects(f.manager.tick(),/OFFLINE/);
});
test('foreign persisted binding fails closed without sending under another project',async()=>{
 const f=fixture();await f.enable(A);f.state(A).binding.project='beta';f.publish(A,1);
 await f.manager.tick();assert.equal(f.homes.get('alpha').page.clicks,0);
 await assert.rejects(f.manager.run('alpha','status'),/STATE_INVALID/);
});

test('v4 fixed delegate batches merge only within their source project and keep every original Work',async()=>{
 const f=fixture();await f.enable(A);await f.enable(B);
 const batch=(p,n)=>({batch_ref:'batch-'+String(n).padStart(16,'0'),project_ref:p.project_ref,sequence:n,ready_at:5,requested:2,not_submitted:0,members:[1,2].map(i=>({work_ref:'work-'+String(n*10+i).padStart(16,'0'),state:'agent_turn_settled',result_class:'result_ready',classification_report_status:'readable',report_status:'readable',report_sha256:'b'.repeat(64)}))});
 const a=batch(A,1),a2=batch(A,2),b=batch(B,3);f.publishEvent(A,a);f.publishEvent(A,a2);f.publishEvent(B,b);
 await f.manager.tick();
 assert.deepEqual(f.state(A).automation.deliveries,[]);assert.deepEqual(f.state(A).automation.consumed,[a.batch_ref,...a.members.map(m=>m.work_ref),a2.batch_ref,...a2.members.map(m=>m.work_ref)]);
 const text=f.homes.get('alpha').page.editor.textContent;
 for(const member of [...a.members,...a2.members])assert(text.includes(member.work_ref));
 for(const member of b.members)assert(!text.includes(member.work_ref));
 assert.equal(f.homes.get('alpha').page.clicks,1);assert.equal(f.homes.get('beta').page.clicks,1);
});

test('two explicitly enabled projects share one exact Chat, send separately and disable independently',async()=>{
 const f=fixture(),a=f.homes.get(A.project_ref),b=f.homes.get(B.project_ref),p=a.page;
 // One physical document, including separate project slots; no two-page shortcut.
 b.page=p;b.io.page=a.io.page;b.io.selectedTab=a.io.selectedTab;b.io.tab=a.io.tab;b.io.exactTabs=a.io.exactTabs;
 await f.enable(A);await f.enable(B);
 assert.equal(f.state(A).automation.route,CHAT);assert.equal(f.state(B).automation.route,CHAT);
 assert(f.state(A).automation.enabled && f.state(B).automation.enabled);
 const sent=[];p.doc.addEventListener('click',e=>{
   if(e.target.getAttribute('aria-label')==='Send') {
     sent.push(p.editor.textContent);
     queueMicrotask(()=>{p.editor.textContent='';p.renderVoice();}); // synthetic host receipt/clear
   }
 });
 f.publish(A,1);f.publish(B,2);await f.manager.tick();
 // The host clears A's submitted composer before B's serialized preparation.
 // A current empty editor needs no quiet delay; each project still sends once.
 assert.equal(p.clicks,2);assert.equal(sent.length,2);
 await f.manager.tick();assert.equal(p.clicks,2);assert.equal(sent.length,2);
 for(const [i,project] of [A,B].entries()) {
   assert.deepEqual(f.state(project).automation.deliveries,[]);
   assert.deepEqual(f.state(project).automation.consumed,['work-'+String(i+1).padStart(16,'0')]);
   assert(sent.some(t=>t.includes('project_ref='+project.project_ref)&&t.includes('work-'+String(i+1).padStart(16,'0'))));
 }
 assert(sent.every(t=>!(t.includes('work-0000000000000001')&&t.includes('work-0000000000000002'))));
 const ah=structuredClone(f.state(A).automation.deliveries);
 await f.manager.run(A.project_ref,'disable');assert(!f.state(A).automation.enabled);assert(f.state(B).automation.enabled);
 await f.manager.run(A.project_ref,'enable',{delayMs:0});await f.manager.tick();
 assert.equal(p.clicks,2);assert.deepEqual(f.state(A).automation.deliveries,ah);
});

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
// Exercise the production lock adapter with a shared deterministic Locks API
// substitute, independent of the optional IndexedDB test dependency.
function lockFixture(f) {
 const tails=new Map(),held=new Set();
 f.io.exclusive=nativeExclusive({request(name,options,fn){
  const task=(tails.get(name)||Promise.resolve()).then(async()=>{
   assert(!held.has(name));held.add(name);try{return await fn();}finally{held.delete(name);}
  });tails.set(name,task.catch(()=>{}));return task;
 }});
 return held;
}
test('recipient switch waits for old-worker tick, owns both routes before project, and keeps its queued Work',async()=>{
 const f=fixture(),held=lockFixture(f);await f.enable(A);f.publish(A,1);
 const h=f.homes.get('alpha'),entered=deferred(),release=deferred(),feed=h.io.feed;
 let blocked=false;f.manager.controller(A).io.feed=async q=>{
  if(q?.after!==undefined&&!blocked){blocked=true;entered.resolve();await release.promise;}return feed(q);
 };
 const oldTick=f.manager.tick();await entered.promise;h.page.navigate(OTHER);f.publish(A,2);
 const second=new ProjectControllers(f.io);let done=false;
 h.pageHook=(_,r)=>{if(r.op==='bind')for(const lock of ['route:'+CHAT,'route:'+OTHER,'project:'+A.scope_id])
   assert(held.has('bridge-notice:'+lock),lock);};
 const switching=second.run('alpha','enable',{delayMs:0}).then(()=>{done=true;});
 await flush();assert.equal(done,false);release.resolve();await oldTick;await switching;
 assert.equal(f.state(A).automation.route,OTHER);assert.equal(h.page.clicks,0);
 assert.deepEqual(f.state(A).automation.deliveries.map(e=>e.route),[OTHER,OTHER]);
 h.page.clock.now+=2100;await Promise.all([second.tick(),f.manager.tick()]);
 assert.equal(h.page.clicks,1);assert.equal(f.state(A).automation.cursor,2);
});
test('recipient selection pinned before waiting for destination lock cannot drift to another Chat',async()=>{
 const f=fixture();lockFixture(f);await f.enable(A);const before=structuredClone(f.state(A)),h=f.homes.get('alpha');
 const entered=deferred(),release=deferred();
 const occupied=f.io.exclusive('route:'+OTHER,async()=>{entered.resolve();await release.promise;});await entered.promise;
 h.page.navigate(OTHER);const switchResult=f.manager.run('alpha','enable',{delayMs:0});
 const rejected=assert.rejects(switchResult,/RECIPIENT_SELECTION_CHANGED/);
 await flush();h.page.navigate(CHAT);release.resolve();await occupied;await rejected;
 assert.deepEqual(f.state(A),before);assert.equal(h.page.clicks,0);
});
test('old in-flight click completes before switch, stays old, and does not block new-route Work',async()=>{
 const f=fixture();lockFixture(f);await f.enable(A);f.publish(A,1);
 const h=f.homes.get('alpha'),entered=deferred(),release=deferred(),feed=h.io.feed;
 let held=false;f.manager.controller(A).io.feed=async q=>{
  if(q?.after!==undefined&&!held){held=true;entered.resolve();await release.promise;}return feed(q);
 };
 const tick=f.manager.tick();await entered.promise;h.pages.get(2).location.href=OTHER;h.selected=2;
 h.io.exactTabs=async r=>[...h.pages].filter(([,p])=>p.location.href===r).map(([id])=>({id,incognito:false}));
 const second=new ProjectControllers(f.io);let done=false;
 const switching=second.run('alpha','enable',{delayMs:0}).then(()=>{done=true;});
 await flush();assert.equal(done,false);release.resolve();await tick;await switching;
 const old='work-0000000000000001';
 assert.equal(h.page.clicks,1);assert.equal(h.pages.get(2).clicks,0);assert.deepEqual(f.state(A).automation.deliveries,[]);
 assert.equal(f.state(A).automation.route,OTHER);assert.equal(f.state(A).binding.route,OTHER);
 assert.deepEqual(f.state(A).automation.consumed,[old]);f.publish(A,2);h.pages.get(2).clock.now+=2100;
 await Promise.all([second.tick(),f.manager.tick()]);assert.equal(h.page.clicks,1);assert.equal(h.pages.get(2).clicks,1);
 assert.deepEqual(f.state(A).automation.deliveries,[]);assert.deepEqual(f.state(A).automation.consumed,[old,'work-0000000000000002']);
});
test('opposite concurrent recipient switches use sorted routes without deadlock or sends',{timeout:2000},async()=>{
 const f=fixture();lockFixture(f);await f.enable(A);await f.enable(B);
 f.homes.get('alpha').page.navigate(OTHER);f.homes.get('beta').page.navigate(CHAT);
 const second=new ProjectControllers(f.io);
 await Promise.all([f.manager.run('alpha','enable',{delayMs:0}),second.run('beta','enable',{delayMs:0})]);
 assert.equal(f.state(A).automation.route,OTHER);assert.equal(f.state(B).automation.route,CHAT);
 assert.equal(f.homes.get('alpha').page.clicks+f.homes.get('beta').page.clicks,0);
});
