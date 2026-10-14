import assert from 'node:assert/strict';
import {nativeFixture,settle} from './native-fixture.js';
import {stateStore,nativeExclusive} from '../extension/state-store.js';
import {ProjectControllers,PROJECTS_KEY} from '../extension/projects.js';
import {wireWorker} from '../extension/wiring.js';
import {Automation} from '../extension/automation.js';
import {KEY} from '../extension/policy.js';
import {completionId,completionMessage,POLL} from '../extension/completion-policy.js';
import {fixture,CHAT,OTHER} from './harness.js';
import {messageFixture} from './receipt-fixture.js';
const epoch='a'.repeat(32),sha='b'.repeat(64);
export const project=(ref,n,root='/synthetic/'+ref)=>({project_ref:ref,scope_id:n.toString(16).padStart(64,'0'),root});
export const A=project('alpha',1),B=project('beta',2),key=p=>'bridgeProjectV1:'+p.scope_id;
const work=(p,n)=>({work_ref:'work-'+n.toString(16).padStart(16,'0'),project_ref:p.project_ref,sequence:n,ready_at:1,report_sha256:sha,result_class:'result_ready',report_status:'readable'});
const flush=async()=>{for(let i=0;i<12;i++)await new Promise(r=>setImmediate(r));};
export function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
export function setup(ps=[A,B],sameChat=false) {
 const data={},pages=new Map([[1,fixture()],[2,fixture()]]);pages.get(2).location.href=OTHER;
 const receipts=new Map([...pages].map(([id,page])=>[id,messageFixture(page)]));
 let selected=1,remote=ps,id=0;const events=new Map(ps.map(p=>[p.project_ref,[]]));const calls=[];
 const hooks={read:async()=>{},write:async()=>{},feed:async()=>{},page:async()=>{}};
 const read=async k=>{await hooks.read(k);return structuredClone(data[k]);};
 const write=async(k,v)=>{await hooks.write(k,v);data[k]=structuredClone(v);};
 const io={read,write,catalog:async()=>({projects:remote}),forProject:p=>({
  boot:async()=> 'boot-1',uuid:()=>`aaaaaaaa-aaaa-aaaa-aaaa-${(++id).toString().padStart(12,'0')}`,now:()=>pages.get(1).clock.now,
  selectedTab:async()=>({id:selected,url:pages.get(selected).location.href,incognito:false}),
  tab:async t=>({id:t,url:pages.get(t).location.href,incognito:false}),
  exactTabs:async route=>[...pages].filter(([_,pg])=>pg.location.href===route).map(([id])=>({id,incognito:false})),
  alarm:async()=>{},clearAlarm:async()=>{},pollAlarm:async()=>{},reportStatus:async()=>{},
  feed:async q=>{await hooks.feed(p,q);const all=events.get(p.project_ref)||[],rows=all.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0));return {epoch,events:structuredClone(rows),cursor:Math.max(q?.after||0,...rows.map(e=>e.sequence)),latest:Math.max(0,...all.map(e=>e.sequence))};},
  page:async(b,r)=>{await hooks.page(b,r);calls.push({project:p.project_ref,binding:structuredClone(b),request:structuredClone(r)});return {...await pages.get(b.tabId).op({...r,project:b.project,route:b.route,generation:b.generation,documentToken:b.documentToken}),documentId:'doc-'+b.tabId};},
  receipt:async(b,r)=>receipts.get(b.tabId).observe({...r,route:b.route})
 })};
 io.exclusive=nativeExclusive(nativeFixture().navigator.locks);
 const manager=new ProjectControllers(io);
 return {data,pages,receipts,events,calls,hooks,io,manager,set selected(x){selected=x;},set remote(x){remote=x;},
  publish(p,n){events.get(p.project_ref).push(work(p,n));},
  async enable(p,tab=p===B&&!sameChat?2:1){selected=tab;await manager.run(p.project_ref,'enable',{delayMs:0});for(const pg of pages.values())pg.clock.now+=2100;},
  state:p=>data[key(p)]};
}

export function wired(ps=[A,B],url='http://127.0.0.1:8765'){
 const f=setup(ps),listeners={},net=[],alarms=[],session={};let selected=1;
 const event=n=>({addListener:fn=>listeners[n]=fn});const chrome={
  runtime:{id:'a'.repeat(32),getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onMessage:event('message'),onStartup:event('startup'),onInstalled:event('installed')},
  storage:{local:{setAccessLevel:async()=>{},get:async k=>({[k]:await f.io.read(k)}),set:async v=>{for(const [k,s] of Object.entries(v))await f.io.write(k,s);}},session:{setAccessLevel:async()=>{},get:async k=>({[k]:session[k]}),set:async v=>Object.assign(session,v)}},
  tabs:{query:async q=>q.active?[{id:selected,url:f.pages.get(selected).location.href,incognito:false}]:[...f.pages].map(([id,p])=>({id,url:p.location.href,incognito:false})),get:async id=>({id,url:f.pages.get(id).location.href,incognito:false})},
  scripting:{executeScript:async s=>{const id=s.target.tabId;const req=s.args[0];const result=s.func.name==='observeReceipt'?f.receipts.get(id).observe(req):await f.pages.get(id).op(req);return [{frameId:0,documentId:'doc-'+id,result}];}},
  alarms:{create:async(n,o)=>alarms.push({name:n,...o}),clear:async()=>true,onAlarm:event('alarm')}
 };
 const native=nativeFixture();const store=stateStore(native.indexedDB,async k=>(await chrome.storage.local.get(k))[k],undefined,nativeExclusive(native.navigator.locks));
 const network=async(href,o)=>{net.push({href,method:o.method});const u=new URL(href);if(u.pathname.endsWith('/projects'))return {ok:true,json:async()=>({projects:ps})};if(o.method==='POST')return {ok:true,json:async()=>({ok:true})};const p=ps.find(p=>p.project_ref===u.searchParams.get('project_ref'));assert.equal(u.searchParams.get('scope_id'),p.scope_id);await f.hooks.feed(p,Object.fromEntries(u.searchParams));const all=f.events.get(p.project_ref)||[],check=u.searchParams.get('check'),after=Number(u.searchParams.get('after')||0),rows=all.filter(e=>check?completionId(e)===check:e.sequence>after);return {ok:true,json:async()=>({epoch,events:structuredClone(rows),cursor:Math.max(after,...rows.map(e=>e.sequence)),latest:Math.max(0,...all.map(e=>e.sequence))})};};
 const rewire=()=>wireWorker(chrome,{extension_id:chrome.runtime.id,url,token:'t'.repeat(48)},network,native);rewire();
 return {...f,rewire,store,readState:p=>store.read(key(p)),listeners,net,alarms,select:id=>selected=id,send:(p,action,args={})=>new Promise(resolve=>listeners.message({action,project_ref:p.project_ref,...args},{id:chrome.runtime.id,url:chrome.runtime.getURL('popup.html')},resolve))};
}
