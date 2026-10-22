import test from 'node:test';
import assert from 'node:assert/strict';
import {ProjectControllers} from '../extension/projects.js';
import {draftChoiceReply} from '../extension/automation.js';
import {harness,CHAT,OTHER} from './harness.js';
import {completionId} from '../extension/completion-policy.js';
const epoch='a'.repeat(32);
const projects=['alpha','beta','other','disabled'].map((project_ref,i)=>({project_ref,root:'/synthetic/'+project_ref,scope_id:String(i+1).repeat(64)}));
const key=p=>'bridgeProjectV1:'+p.scope_id;
const work=(p,n)=>({work_ref:'work-'+String(n).padStart(16,'0'),project_ref:p.project_ref,sequence:n,ready_at:1,
 report_sha256:'b'.repeat(64),result_class:'result_ready',report_status:'readable'});
async function setup() {
 const h=harness(),data={},events=new Map(projects.map(p=>[p.project_ref,[]]));
 h.io.exactTabs=async r=>[{id:r===CHAT?1:2,incognito:false}];h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.pages.get(2).location.href=OTHER;
 const hooks={feed:async()=>{},publish:async()=>{},commit:async()=>{}},page=h.io.page;
 const io={read:async k=>structuredClone(data[k]),write:async(k,v)=>{data[k]=structuredClone(v);},
  writeMany:async rows=>{await hooks.publish(rows);for(const row of rows)data[row.key]=structuredClone(row.value);},
  catalog:async()=>({projects}),forProject:p=>({...h.io,page:async(b,r)=>{if(r.op==='draft_commit')await hooks.commit();return page(b,{...r,project:b.project});},
   feed:async q=>{await hooks.feed(p,q);const rows=events.get(p.project_ref).filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)).slice(0,16);
    return {epoch,events:structuredClone(rows),cursor:Math.max(q?.after||0,...rows.map(e=>e.sequence),0),latest:Math.max(0,...[...events.values()].flat().map(e=>e.sequence))};}})};
 const manager=new ProjectControllers(io);
 for(const p of projects) {
  h.selected= p.project_ref==='other'?2:1;
  await manager.run(p.project_ref,'enable',{delayMs:0});
 }
 await manager.run('disabled','disable');h.page.clock.now+=2100;h.page.editor.textContent='draft';h.page.renderSend();
 events.get('alpha').push(work(projects[0],1));await manager.tick();
 h.page.onPageMessage=async m=>{const out=await manager.run(m.project_ref,'draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});return draftChoiceReply(out.state.automation,m.offerId);};
 const settle=async()=>{for(let i=0;i<80;i++)await new Promise(r=>setImmediate(r));};
 return {h,data,events,manager,hooks,io,choose:async choice=>{h.page.userClick(h.page.choiceButtons()[choice==='append'?0:1]);await settle();},
  state:p=>data[key(p)],publish:(p,n)=>events.get(p.project_ref).push(work(p,n)),settle};
}
for(const choice of ['append','ignore'])test('one click handles all enabled projects on this Chat only: '+choice,async()=>{
 const f=await setup();f.publish(projects[1],2);f.publish(projects[2],3);f.publish(projects[3],4);
 await f.choose(choice);
 for(const p of projects.slice(0,2))assert(f.state(p).automation.consumed.includes(work(p,p===projects[0]?1:2).work_ref));
 for(const p of projects.slice(2))assert.equal(f.state(p).automation.consumed.length,0);
 assert.equal(f.h.page.choiceButtons().length,0);assert.equal(f.h.page.clicks,0);
 const text=f.h.page.editor.textContent;
 assert.equal(text.includes('project_ref=alpha'),choice==='append');assert.equal(text.includes('project_ref=beta'),choice==='append');
 assert(!text.includes('project_ref=other'));assert(!text.includes('project_ref=disabled'));
 await f.manager.tick();assert.equal(f.h.page.editor.textContent,text);assert.equal(f.h.page.choiceButtons().length,0);
});
test('identical raw IDs in different projects retain project attribution and dedup separately',async()=>{
 const f=await setup();const e=work(projects[1],1);e.sequence=2;f.events.get('beta').push(e);
 await f.choose('append');const text=f.h.page.editor.textContent;
 assert(text.includes('project_ref=alpha'));assert(text.includes('project_ref=beta'));
 assert.equal((text.match(/work-0000000000000001/g)||[]).length,4); // event and member in each notice
});
test('new completion during collection is deferred by one common boundary',async()=>{
 const f=await setup();f.publish(projects[1],2);let once=true;
 f.hooks.feed=async(p,q)=>{if(p.project_ref==='beta'&&!q?.check&&once){once=false;f.publish(projects[1],3);}};
 await f.choose('append');assert(f.state(projects[1]).automation.consumed.includes(work(projects[1],2).work_ref));
 assert(!f.state(projects[1]).automation.consumed.includes(work(projects[1],3).work_ref));
 assert(!f.h.page.editor.textContent.includes(work(projects[1],3).work_ref));
 await f.manager.tick();assert.equal(f.h.page.choiceButtons().length,2);
});
test('unreadable bound project does not partially consume or append other projects',async()=>{
 const f=await setup();f.publish(projects[1],2);f.hooks.feed=async p=>{if(p.project_ref==='beta')throw Error('OFFLINE');};
 await f.choose('append');assert.equal(f.h.page.editor.textContent,'draft');assert.equal(f.state(projects[0]).automation.consumed.length,0);
 assert.equal(f.state(projects[1]).automation.consumed.length,0);assert.equal(f.h.page.clicks,0);
});
for(const failure of ['abort','ACK lost','page ACK lost'])test('multi-project intent '+failure+' cannot partially publish or replay an Append',async()=>{
 const f=await setup();f.publish(projects[1],2);let commits=0,failed=false;
 f.hooks.publish=async rows=>{if(!failed&&rows.some(r=>r.value.automation.lastChoice)){
  failed=true;if(failure==='abort')throw Error('ABORT');
  if(failure==='ACK lost'){for(const row of rows)f.data[row.key]=structuredClone(row.value);throw Error('ACK_LOST');}
 }};
 f.hooks.commit=async()=>{commits++;if(failure==='page ACK lost')throw Error('ACK_LOST');};
 await f.choose('append');assert.equal(commits,failure==='page ACK lost'?1:0);
 assert.equal(f.state(projects[0]).automation.consumed.length===0,failure==='abort');
 assert.equal(f.state(projects[1]).automation.consumed.length===0,failure==='abort');
 f.hooks.publish=async()=>{};await f.manager.tick();await f.manager.tick();assert.equal(commits,failure==='page ACK lost'?1:0);
 assert.equal(f.h.page.editor.textContent,'draft');assert.equal(f.h.page.clicks,0);
});

test('another project cannot auto-send while this Chat has an undecided offer, even after draft clearing',async()=>{
 const f=await setup();f.h.page.edit('');f.h.page.renderVoice();f.h.page.clock.now+=2100;
 f.publish(projects[1],2);await f.manager.tick();assert.equal(f.h.page.clicks,0);
 assert.equal(f.h.page.choiceButtons().length,2);await f.choose('ignore');assert.equal(f.h.page.clicks,0);
 assert(f.state(projects[1]).automation.consumed.includes(work(projects[1],2).work_ref));
});

for(const choice of ['append','ignore'])test('lost originating Work still allows another bound project to be handled: '+choice,async()=>{
 const f=await setup();f.publish(projects[1],2);const feed=f.manager.controller((await f.manager.catalog()).find(p=>p.project_ref==='alpha')).io.feed;
 f.manager.controller((await f.manager.catalog()).find(p=>p.project_ref==='alpha')).io.feed=async q=>q?.check?
  {epoch,events:[],cursor:1,latest:2,check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}}:feed(q);
 await f.choose(choice);assert.equal(f.h.page.choiceButtons().length,0);
 assert(f.state(projects[1]).automation.consumed.includes(work(projects[1],2).work_ref));
 assert.equal(f.h.page.editor.textContent.includes('project_ref=beta'),choice==='append');
 await f.manager.tick();assert.equal(f.h.page.choiceButtons().length,0);assert.equal(f.h.page.clicks,0);
});
test('durable other-project offer prevents auto-send when its page view cannot be restored',async()=>{
 const f=await setup(),pg=f.h.page,op=pg.op;
 pg.window.__bridgeDraftChoiceV1.host.remove();pg.edit('');pg.renderVoice();pg.clock.now+=2100;
 pg.op=async r=>r.op==='draft_offer'&&r.project==='alpha'?{ok:false,code:'COMPOSER_NOT_READY'}:op(r);
 f.publish(projects[1],2);await f.manager.tick();assert.equal(pg.clicks,0);assert.equal(pg.editor.textContent,'');
 assert.equal(f.state(projects[1]).automation.consumed.length,0);
});

for(const fault of ['mixed scope','invalid project','extra field'])test('malformed cross-project Append packet is refused before intent: '+fault,async()=>{
 const f=await setup();f.publish(projects[1],2);const pg=f.h.page,op=pg.op;
 pg.op=async r=>{if(r.op==='draft_prepare'&&r.merge){r=structuredClone(r);
  if(fault==='mixed scope')delete r.merge[1].project_ref;
  if(fault==='invalid project')r.merge[1].project_ref='not a project';
  if(fault==='extra field')r.merge[1].text='arbitrary prompt';
 }return op(r);};
 await f.choose('append');assert.equal(pg.editor.textContent,'draft');assert.equal(pg.clicks,0);
 for(const p of projects.slice(0,2))assert.equal(f.state(p).automation.consumed.length,0);
});
test('a bound project changing during page preparation prevents the whole Append',async()=>{
 const f=await setup();f.publish(projects[1],2);const pg=f.h.page,op=pg.op;
 pg.op=async r=>{const out=await op(r);if(r.op==='draft_prepare')f.data[key(projects[1])].revision++;return out;};
 await f.choose('append');assert.equal(pg.editor.textContent,'draft');assert.equal(pg.clicks,0);
 for(const p of projects.slice(0,2))assert.equal(f.state(p).automation.consumed.length,0);
});
