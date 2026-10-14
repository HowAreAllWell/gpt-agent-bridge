import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {ProjectControllers} from '../extension/projects.js';
import {harness,CHAT,OTHER} from './harness.js';

test('actual registry/feed responses: later registrations appear without restart, remain off until explicit Chat enable',
 {skip:!process.env.BRIDGE_REGISTRY_FIXTURE_OUTPUT && 'Run isolated tests.test_registry_notifications with BRIDGE_REGISTRY_FIXTURE_OUTPUT first'},async()=>{
 const proof=JSON.parse(readFileSync(process.env.BRIDGE_REGISTRY_FIXTURE_OUTPUT,'utf8'));
 const store={},homes=new Map();let catalog=proof.empty,phase='before';
 for(const [i,p] of proof.catalog.projects.entries()) {
  const h=harness();h.page.location.href=i?OTHER:CHAT;
  h.io.exactTabs=async r=>r===h.page.location.href?[{id:1,incognito:false}]:[];
  h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
  h.io.receipt=async()=>({ok:true,scope:'chat-user-message-v1',notices:0,replies:0,draft:false,tooMany:false});
  const page=h.io.page;h.io.page=(b,r)=>page(b,{...r,project:b.project});
  h.io.feed=async q=>{const payload=structuredClone(proof[phase][p.project_ref]);payload.events=payload.events.filter(e=>q?.check?e.work_ref===q.check:e.sequence>(q?.after||0));return payload;};homes.set(p.project_ref,h);
 }
 const manager=new ProjectControllers({read:async k=>structuredClone(store[k]),write:async(k,v)=>{store[k]=structuredClone(v);},catalog:async()=>catalog,forProject:p=>homes.get(p.project_ref).io});
 assert.deepEqual(await manager.catalog(),[]);await manager.tick();
 catalog=proof.catalog;phase='after';assert.equal((await manager.catalog()).length,2);await manager.tick();
 for(const h of homes.values())assert.equal(h.page.clicks,0);
 assert.deepEqual(store,{}); // registration has not authorized or created a send intent
 for(const p of catalog.projects)await manager.run(p.project_ref,'enable',{delayMs:0});
 for(const h of homes.values())h.page.clock.now+=2100;
 phase='later';await manager.tick();
 for(const p of catalog.projects){const h=homes.get(p.project_ref);assert.equal(h.page.clicks,1);assert(h.page.editor.textContent.includes('project_ref='+p.project_ref));assert(h.page.editor.textContent.includes(proof.later[p.project_ref].events.at(-1).work_ref));assert(!h.page.editor.textContent.includes(proof.after[p.project_ref].events[0].work_ref));const foreign=catalog.projects.find(x=>x!==p);assert(!h.page.editor.textContent.includes(proof.later[foreign.project_ref].events.at(-1).work_ref));}
 await manager.tick();for(const h of homes.values())assert.equal(h.page.clicks,1);
});
