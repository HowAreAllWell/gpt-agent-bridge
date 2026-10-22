import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation,draftChoiceReply} from '../extension/automation.js';
import {harness,CHAT,OTHER,DOMEvent} from './harness.js';
import {completionId} from '../extension/completion-policy.js';
const epoch='a'.repeat(32),id=(kind,n)=>kind+'-'+n.toString(16).padStart(16,'0');
const batch=n=>({batch_ref:id('batch',n),project_ref:'gpt-agent-bridge',sequence:n,ready_at:1,requested:1,not_submitted:0,
 members:[{work_ref:id('work',n),state:'agent_turn_settled',result_class:'result_ready',classification_report_status:'readable',report_status:'readable',report_sha256:'b'.repeat(64)}]});
const settle=async()=>{for(let i=0;i<25;i++)await new Promise(r=>setImmediate(r));};
async function setup(draft='draft',beforeTick=()=>{}) {
 const h=harness();h.events=[];h.messages=[];
 h.io.exactTabs=async route=>[{id:1,incognito:false}].filter(()=>route===h.page.location.href);
 h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.io.feed=async q=>{const events=h.events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)).slice(0,16);
  return {epoch,events:structuredClone(events),cursor:Math.max(q?.after||0,...events.map(e=>e.sequence),0),latest:Math.max(...h.events.map(e=>e.sequence),0)};};
 h.worker=new Automation(h.io);await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;
 h.page.editor.textContent=draft;if(draft)h.page.renderSend();
 h.tick=()=>h.worker.run('tick');h.wake=()=>{h.worker=new Automation(h.io);return h.tick();};
 h.page.onPageMessage=async m=>{h.messages.push(m);const s=await h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});return draftChoiceReply(s.automation,m.offerId);};
 h.choose=async choice=>{h.page.userClick(h.page.choiceButtons()[choice==='append'?0:1]);await settle();};
 h.events=[batch(1)];beforeTick(h);await h.tick();return h;
}
for(const choice of ['append','ignore'])test('persistent prompt: typing, rich text, IME, upload and clearing never replace the host: '+choice,async()=>{
 const h=await setup(),p=h.page,offer=p.window.__bridgeDraftChoiceV1,buttons=p.choiceButtons();
 p.editor.focus=()=>{throw Error('FOCUS_FORBIDDEN');};
 for(const mutate of [()=>p.edit('latest text'),()=>p.doc.emit(new DOMEvent('compositionstart',{target:p.editor})),
  ()=>p.edit('组合中的文字'),()=>{const strong=p.add(p.editor,'strong');strong.textContent='rich';},
  ()=>{p.body.appendChild(p.file);p.file.files=[{}];p.body.attrs['aria-busy']='true';},
  ()=>{p.file.files=[];delete p.body.attrs['aria-busy'];p.doc.emit(new DOMEvent('compositionend',{target:p.editor}));},()=>p.edit('')]) {
  mutate();await h.tick();assert.equal(p.window.__bridgeDraftChoiceV1,offer);assert.equal(offer.host.isConnected,true);
  assert.deepEqual(p.choiceButtons(),buttons);assert.equal(h.messages.length,0);assert.equal(p.clicks,0);
 }
 await h.choose(choice);assert.equal(p.choiceButtons().length,0);assert.equal(h.state.automation.offer,null);
 assert.equal(p.clicks,0);assert.equal(h.state.automation.deliveries.length,0);
 assert.equal(p.editor.childNodes.length,choice==='append'?1:0);
 await h.wake();assert.equal(p.choiceButtons().length,0);
});
for(const choice of ['append','ignore'])test('click samples three completed batches once; later batch gets a new prompt: '+choice,async()=>{
 const h=await setup(),p=h.page,offer=p.window.__bridgeDraftChoiceV1,old=p.choiceButtons()[0];
 h.events.push(batch(2));await h.tick();h.events.push(batch(3)); // Third batch has never been polled.
 assert.equal(p.window.__bridgeDraftChoiceV1,offer);p.edit('current draft');await h.choose(choice);
 assert.equal(p.choiceButtons().length,0);for(let n=1;n<=3;n++)assert(h.state.automation.consumed.includes(id('batch',n)));
 const text=p.editor.textContent;
 for(let n=1;n<=3;n++)assert.equal(text.includes(id('batch',n)),choice==='append');
 p.userClick(old);await settle();assert.equal(p.editor.textContent,text);
 await h.wake();assert.equal(p.choiceButtons().length,0);assert.equal(p.editor.textContent,text);
 h.events.push(batch(4));await h.tick();assert.equal(p.choiceButtons().length,2);assert.notEqual(p.window.__bridgeDraftChoiceV1,offer);
});
test('click watermark excludes batches published during a paginated feed read',async()=>{
 const h=await setup();h.events=Array.from({length:18},(_,i)=>batch(i+1));
 const feed=h.io.feed;let reads=0;
 h.io.feed=async q=>{const r=await feed(q);if(!q?.check&&++reads===1)h.events.push(batch(19));return r;};
 await h.choose('append');assert(h.page.editor.textContent.includes(id('batch',18)));
 assert(!h.page.editor.textContent.includes(id('batch',19)));assert.equal(h.state.automation.cursor,18);
 await h.tick();assert.equal(h.page.choiceButtons().length,2);
});
for(const choice of ['append','ignore'])test('draft wins over English/Chinese Stop and tool busy: '+choice,async()=>{
 for(const label of ['Stop','停止']){
  const h=await setup(),p=h.page;const old=p.window.__bridgeDraftChoiceV1;
  p.add(p.footer,'button',{type:'button','aria-label':label});p.body.attrs['aria-busy']='true';
  await h.tick();assert.equal(p.window.__bridgeDraftChoiceV1,old);
  if(choice==='append'){delete p.body.attrs['aria-busy'];}
  await h.choose(choice);assert.equal(p.choiceButtons().length,0);assert.equal(p.clicks,0);
 }
});
test('IME and unfinished upload refuse Append without retiring; same buttons work after completion',async()=>{
 const h=await setup(),p=h.page,offer=p.window.__bridgeDraftChoiceV1;
 p.doc.emit(new DOMEvent('compositionstart',{target:p.editor}));await h.choose('append');
 assert.equal(h.messages.length,0);assert.equal(p.window.__bridgeDraftChoiceV1,offer);
 p.doc.emit(new DOMEvent('compositionend',{target:p.editor}));p.body.appendChild(p.file);p.file.files=[{}];
 const progress=p.add(p.body,'div',{'data-testid':'upload-progress'});await h.choose('append');
 assert.equal(h.state.automation.consumed.length,0);assert.equal(p.window.__bridgeDraftChoiceV1,offer);
 progress.remove();await h.choose('append');assert.equal(p.choiceButtons().length,0);assert.equal(p.file.files.length,1);
 assert.equal(p.editor.childNodes.length,2);assert.equal(p.clicks,0);
});
test('Ignore during upload preserves every editor and attachment node',async()=>{
 const h=await setup(),p=h.page,original=p.editor.childNodes[0];p.body.appendChild(p.file);p.file.files=[{}];p.body.attrs['aria-busy']='true';
 await h.choose('ignore');assert.equal(p.editor.childNodes[0],original);assert.equal(p.editor.textContent,'draft');
 assert.equal(p.file.files.length,1);assert.equal(p.body.attrs['aria-busy'],'true');assert.equal(p.choiceButtons().length,0);
});
for(const fault of ['reply lost','commit ACK lost','DOM rejected'])test('Append retires exactly once despite '+fault,async()=>{
 const h=await setup(),p=h.page,page=h.io.page;let commits=0;
 h.io.page=async(b,r)=>{if(r.op==='draft_commit'){commits++;const out=await page(b,r);if(fault==='commit ACK lost')throw Error('ACK_LOST');return out;}return page(b,r);};
 if(fault==='DOM rejected')p.onYield=()=>p.editor.lastChild?.remove();
 if(fault==='reply lost')p.onPageMessage=async m=>{await h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});return new Promise(()=>{});};
 await h.choose('append');assert.equal(p.choiceButtons().length,0);const text=p.editor.textContent;
 await h.wake();await h.wake();assert.equal(commits,1);assert.equal(p.editor.textContent,text);assert.equal(p.choiceButtons().length,0);
 assert(h.state.automation.consumed.includes(id('batch',1)));
});
for(const fault of ['offline','IME at prepare','upload at commit','navigation at commit','editor missing'])test('no safe click: retain current pending group for '+fault,async()=>{
 const h=await setup(),p=h.page,offer=p.window.__bridgeDraftChoiceV1,feed=h.io.feed,page=h.io.page;
 if(fault==='offline')h.io.feed=async()=>{throw Error('OFFLINE');};
 h.io.page=async(b,r)=>{
  if(r.op==='draft_prepare'&&fault==='IME at prepare')p.doc.emit(new DOMEvent('compositionstart',{target:p.editor}));
  if(r.op==='draft_prepare'&&fault==='editor missing')p.editor.remove();
  if(r.op==='draft_commit'&&fault==='upload at commit')p.body.attrs['aria-busy']='true';
  if(r.op==='draft_commit'&&fault==='navigation at commit')p.navigate(OTHER);
  return page(b,r);
 };
 await h.choose('append');assert.equal(p.editor.textContent,'draft');assert.equal(p.clicks,0);
 assert(!h.state.automation.consumed.includes(id('batch',1)));assert(h.state.automation.offer);
 if(fault!=='navigation at commit')assert.equal(p.window.__bridgeDraftChoiceV1,offer);
 if(fault==='offline')assert.equal(p.choiceButtons()[0].disabled,false);
 h.io.feed=feed;
});
test('same Work republished under a new batch never produces a new prompt',async()=>{
 const h=await setup();await h.choose('append');const repeated=batch(2);repeated.members=batch(1).members;h.events.push(repeated);
 const text=h.page.editor.textContent;await h.wake();assert.equal(h.page.choiceButtons().length,0);assert.equal(h.page.editor.textContent,text);
 assert(h.state.automation.consumed.includes(id('batch',2)));
});
for(const label of ['Stop','停止','Unknown'])test('empty composer safely waits for '+label,async()=>{
 const h=await setup(''); // Initial event may already have sent in the idle fixture.
 h.page.edit('');h.events.push(batch(2));h.page.button.attrs={type:'button','aria-label':label};
 const before=h.page.clicks;await h.tick();assert.equal(h.page.clicks,before);assert.equal(h.page.editor.textContent,'');
});
for(const kind of ['Stop','停止','IME','selected file','rich text'])test('initial draft is detected before busy state: '+kind,async()=>{
 const h=await setup(kind==='selected file'?'':'draft',h=>{
  const p=h.page;
  if(['Stop','停止'].includes(kind))p.add(p.footer,'button',{type:'button','aria-label':kind});
  if(kind==='IME')p.doc.emit(new DOMEvent('compositionstart',{target:p.editor}));
  if(kind==='selected file'){p.body.appendChild(p.file);p.file.files=[{}];p.body.attrs['aria-busy']='true';}
  if(kind==='rich text'){p.editor.textContent='';p.add(p.editor,'strong');}
 });
 assert.equal(h.page.choiceButtons().length,2);assert.equal(h.page.clicks,0);assert(h.state.automation.offer);
});
for(const fault of ['wrong document','extra field','bad lease','bad focused'])test('spoofed prepare response never retires or appends: '+fault,async()=>{
 const h=await setup(),page=h.io.page,offer=h.page.window.__bridgeDraftChoiceV1;
 h.io.page=async(b,r)=>{const out=await page(b,r);if(r.op==='draft_prepare'){
  if(fault==='wrong document')out.documentId='different';if(fault==='extra field')out.extra=true;
  if(fault==='bad lease')out.lease='not-a-lease';if(fault==='bad focused')out.focused='yes';
 }return out;};
 await h.choose('append');assert.equal(h.page.editor.textContent,'draft');assert.equal(h.state.automation.consumed.length,0);
 assert.equal(h.page.window.__bridgeDraftChoiceV1,offer);assert.equal(h.page.clicks,0);
});
test('lost durable intent ACK never retries an editor mutation or reoffers the same Work',async()=>{
 const h=await setup(),write=h.io.write,page=h.io.page;let unknown=true,commits=0;
 h.io.write=async(k,s)=>{await write(k,s);if(unknown&&s.automation.lastChoice){unknown=false;throw Error('SAVE_ACK_LOST');}};
 h.io.page=async(b,r)=>{if(r.op==='draft_commit')commits++;return page(b,r);};
 await h.choose('append');assert.equal(commits,0);assert(h.state.automation.consumed.includes(id('batch',1)));
 h.io.write=write;await h.wake();assert.equal(h.page.choiceButtons().length,0);assert.equal(commits,0);assert.equal(h.page.editor.textContent,'draft');
});
test('ordinary typing during intent wait appends to the current editor; a real user submit never does',async()=>{
 for(const submit of [false,true]){
  const h=await setup(),page=h.io.page;
  h.io.page=async(b,r)=>{if(r.op==='draft_commit'){
   h.page.edit('new current draft');if(submit)h.page.doc.emit(new DOMEvent('keydown',{target:h.page.editor,key:'Enter'}));
  }return page(b,r);};
  await h.choose('append');assert.equal(h.page.clicks,0);assert(h.page.editor.textContent.startsWith('new current draft'));
  assert.equal(h.page.editor.textContent.includes(id('batch',1)),!submit);
  assert.equal(h.state.automation.consumed.includes(id('batch',1)),!submit);
 }
});
test('rapid Append/Ignore double click authorizes only one action',async()=>{
 const h=await setup(),buttons=h.page.choiceButtons();h.page.userClick(buttons[0]);h.page.userClick(buttons[1]);h.page.userClick(buttons[0]);
 await settle();assert.equal(h.messages.length,1);assert.equal(h.page.choiceButtons().length,0);
 assert(h.page.editor.textContent.includes(id('batch',1)));assert.equal(h.page.editor.childNodes.length,2);
});
for(const choice of ['append','ignore'])test('stale sender context URL accepts the current bound document once: '+choice,async()=>{
 const h=await setup();let request;
 const source={tabId:1,documentId:'doc-1',url:OTHER};
 h.page.onPageMessage=async m=>{
  h.messages.push(m);request={...m,source};
  const s=await h.worker.run('draft_choice',request);return draftChoiceReply(s.automation,m.offerId);
 };
 await h.choose(choice);
 assert.equal(h.messages.length,1);assert.equal(h.state.automation.offer,null);
 assert.equal(h.page.choiceButtons().length,0);assert.equal(h.page.clicks,0);
 assert(h.state.automation.consumed.includes(id('batch',1)));
 assert(h.page.editor.textContent.startsWith('draft'));
 assert.equal(h.page.editor.textContent.includes(id('batch',1)),choice==='append');
 const text=h.page.editor.textContent,commits=h.calls.filter(c=>c.op==='draft_commit').length;
 await h.worker.run('draft_choice',request);await h.wake();
 assert.equal(h.page.editor.textContent,text);assert.equal(h.page.choiceButtons().length,0);
 assert.equal(h.calls.filter(c=>c.op==='draft_commit').length,commits);
});
for(const fault of ['tab','document','token','offer'])test('stale sender URL never authorizes a different '+fault,async()=>{
 const h=await setup(),offer=h.page.window.__bridgeDraftChoiceV1;
 const arg={choice:'ignore',offerId:offer.id,token:offer.token,source:{tabId:1,documentId:'doc-1',url:OTHER}};
 if(fault==='tab')arg.source.tabId=2;
 if(fault==='document')arg.source.documentId='doc-2';
 if(fault==='token')arg.token='ffffffff-ffff-ffff-ffff-ffffffffffff';
 if(fault==='offer')arg.offerId='ffffffff-ffff-ffff-ffff-ffffffffffff';
 await assert.rejects(h.worker.run('draft_choice',arg),/DRAFT_CHOICE_SOURCE_CHANGED/);
 assert.equal(h.state.automation.consumed.length,0);assert.equal(h.page.editor.textContent,'draft');
 assert.equal(h.page.window.__bridgeDraftChoiceV1,offer);assert.equal(h.page.clicks,0);
 assert.equal(h.calls.filter(c=>c.op==='draft_prepare'||c.op==='draft_commit').length,0);
});
for(const stage of ['before prepare','after prepare'])test('current tab route must still match '+stage,async()=>{
 const h=await setup(),page=h.io.page;let result;
 const moved=()=>{h.io.tab=async()=>({id:1,url:OTHER,incognito:false});};
 if(stage==='before prepare')moved();
 else h.io.page=async(b,r)=>{const out=await page(b,r);if(r.op==='draft_prepare')moved();return out;};
 h.page.onPageMessage=m=>{
  result=h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:OTHER}});
  return result.then(s=>draftChoiceReply(s.automation,m.offerId));
 };
 await h.choose('ignore');await assert.rejects(result,/TARGET_CHANGED_REBIND/);
 assert.equal(h.state.automation.consumed.length,0);assert(h.state.automation.offer);
 assert.equal(h.page.editor.textContent,'draft');assert.equal(h.page.clicks,0);
 assert.equal(h.calls.filter(c=>c.op==='draft_commit').length,0);
});
test('page route guard refuses a changed document route even when Chrome tab metadata lags',async()=>{
 const h=await setup(),page=h.io.page;
 h.io.tab=async()=>({id:1,url:CHAT,incognito:false});
 h.io.page=async(b,r)=>{if(r.op==='draft_prepare')h.page.location.href=OTHER;return page(b,r);};
 h.page.onPageMessage=async m=>{
  const s=await h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:OTHER}});
  return draftChoiceReply(s.automation,m.offerId);
 };
 await h.choose('append');
 assert.equal(h.state.automation.consumed.length,0);assert(h.state.automation.offer);
 assert.equal(h.page.editor.textContent,'draft');assert.equal(h.page.clicks,0);
 assert.equal(h.calls.filter(c=>c.op==='draft_commit').length,0);
});

for(const choice of ['append','ignore'])test('foreign project sequence gaps do not block a complete local click: '+choice,async()=>{
 const h=await setup(),feed=h.io.feed;
 h.io.feed=async q=>({...await feed(q),latest:1000});
 await h.choose(choice);
 assert.equal(h.page.choiceButtons().length,0);assert(h.state.automation.consumed.includes(id('batch',1)));
 assert.equal(h.page.clicks,0);
});
test('Ignore needs no editor readiness, IME completion or draft mutation',async()=>{
 const h=await setup(),p=h.page,original=p.editor.childNodes[0];
 p.doc.emit(new DOMEvent('compositionstart',{target:p.editor}));
 await h.choose('ignore');assert.equal(p.choiceButtons().length,0);
 assert.equal(p.editor.childNodes[0],original);assert.equal(p.editor.textContent,'draft');assert.equal(p.clicks,0);
});
test('lost old identity does not turn a refreshed surviving batch into a self-conflict',async()=>{
 const h=await setup(),feed=h.io.feed;h.events.push(batch(2));
 h.io.feed=async q=>q?.check===id('batch',1)?{epoch,events:[],cursor:2,latest:2,
  check:{work_ref:q.check,state:'unavailable',code:'WORK_IDENTITY_LOST'}}:feed(q);
 await h.choose('append');assert.equal(h.page.choiceButtons().length,0);
 assert(h.page.editor.textContent.includes(id('batch',2)));assert(!h.page.editor.textContent.includes(id('batch',1)));
 assert.equal(h.page.clicks,0);
});
for(const choice of ['append','ignore'])test('128 completions with foreign sequence gaps finish on a final empty page: '+choice,async()=>{
 const h=await setup();h.events=Array.from({length:128},(_,i)=>batch(i+1));const feed=h.io.feed;
 h.io.feed=async q=>({...await feed(q),latest:1000});await h.choose(choice);
 assert.equal(h.page.choiceButtons().length,0);assert.equal(h.state.automation.consumed.filter(x=>x.startsWith('batch-')).length,128);
 assert.equal(h.page.clicks,0);
});
