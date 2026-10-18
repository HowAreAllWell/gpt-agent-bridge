import test from 'node:test';
import assert from 'node:assert/strict';
import {Automation} from '../extension/automation.js';
import {completionId,completionMessage,mergedNotice,noticeItem} from '../extension/completion-policy.js';
import {harness,fixture,DOMEvent,CHAT,OTHER} from './harness.js';
import {wired,A,B} from './project-repair-fixture.js';
import {settle} from './native-fixture.js';
import {wiring as refreshWiring,A as refreshProject,key as refreshKey,settle as settleRefresh} from './review-wiring-fixture.js';
const epoch='a'.repeat(32),sha='b'.repeat(64);
const event=n=>({work_ref:'work-'+n.toString(16).padStart(16,'0'),project_ref:'gpt-agent-bridge',
 sequence:n,ready_at:5,result_class:'result_ready',report_status:'readable',report_sha256:sha});
const flush=async()=>{for(let i=0;i<20;i++)await new Promise(r=>setImmediate(r));};
function draft(page,text) {
 page.editor.textContent='';page.add(page.editor,'p').textContent=text;
 page.doc.emit({type:'input',target:page.editor});page.renderSend();page.clock.now+=2100;
}
function text(page) {
 const content=n=>n.nodeType===3?n.nodeValue:n.tagName==='BR'?
  n.getAttribute('class')==='ProseMirror-trailingBreak'?'':'\n':n.childNodes.map(content).join('');
 return page.editor.childNodes.map(content).join('\n');
}
async function setup(options={}) {
 const h=harness(options),events=[],messages=[];let result;
 h.io.exactTabs=async r=>[...h.pages].filter(([,p])=>p.location.href===r).map(([id])=>({id,incognito:false}));
 // The second fixture tab must not accidentally duplicate the original recipient.
 h.pages.get(2).location.href=OTHER;
 h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
 h.io.feed=async q=>{const found=events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0));
  return {epoch,events:found,cursor:Math.max(q?.after||0,...found.map(e=>e.sequence)),latest:Math.max(0,...events.map(e=>e.sequence))};};
 h.worker=new Automation(h.io);await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;
 for(const [id,page] of h.pages)page.onPageMessage=async m=>{
  messages.push(m);
  try {await h.worker.run('draft_choice',{token:m.token,source:{tabId:id,documentId:'doc-'+id,url:page.location.href}});result={ok:true};}
  catch(e){result={ok:false,code:e.message};}
  return result;
 };
 return Object.assign(h,{publish(n){events.push(typeof n==='object'?n:event(n));},tick(){return h.worker.run('tick');},
  getResult:()=>result,messages,wake(){h.worker=new Automation(h.io);return h.worker.run('tick');}});
}
test('external file inputs: same native form outside body requires an explicit choice, including form attribute association',async()=>{
 for(const remote of [false,true])for(const value of ['', '中文草稿保留附件'])for(const choice of ['append','ignore']) {
  const h=await setup({owner:true}),p=h.page;p.owner.setAttribute('id','composer-owner');if(value)draft(p,value);
  const parent=remote?p.add(p.doc,'form',{id:'unrelated-owner'}):p.owner;
  const input=p.add(parent,'input',{type:'file',hidden:'',...(remote?{form:'composer-owner'}:{})}),file={};input.files=[file];
  assert.equal(input.form,p.owner);assert(!p.body.contains(input));
  const original=[...p.editor.childNodes],copy=p.editor.cloneNode(true),slot=p.attachments.cloneNode(true),inputCopy=input.cloneNode(true);
  h.publish(1);await h.tick();assert.equal(p.clicks,0);assert.equal(p.choiceButtons().length,2);
  assert(!h.calls.some(c=>c.op==='commit'));assert.deepEqual(h.state.automation.consumed,[]);
  assert.equal(h.state.automation.deliveries[0].intentAt,undefined);assert(p.editor.isEqualNode(copy));
  p.userClick(p.choiceButtons()[choice==='append'?0:1]);await flush();assert.deepEqual(h.getResult(),{ok:true});
  assert.equal(p.clicks,0);assert.equal(input.files[0],file);assert.equal(input.form,p.owner);assert(input.isEqualNode(inputCopy));
  assert(p.attachments.isEqualNode(slot));assert(original.every((node,i)=>p.editor.childNodes[i]===node&&node.isEqualNode(copy.childNodes[i])));
  assert.equal(text(p),choice==='append'?value+'\n'+completionMessage({...event(1),noticeVersion:2}):value);
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);const after=p.editor.cloneNode(true);await h.wake();
  assert(p.editor.isEqualNode(after));assert.equal(p.choiceButtons().length,0);assert.equal(p.clicks,0);
 }
});
test('external file inputs: a same-owner selection appearing during automatic prefill blocks Send without replay',async()=>{
 for(const remote of [false,true])for(const change of ['select','insert','associate']) {
  const h=await setup({owner:true}),p=h.page;p.owner.setAttribute('id','composer-owner');
  let input;const create=()=>p.add(remote?p.doc:p.owner,'input',{type:'file',hidden:'',...(remote?{form:'composer-owner'}:{})});
  if(change!=='insert') {
   input=create();assert.equal(input.form,p.owner);assert(!p.body.contains(input));
   if(change==='associate') {
    const foreign=p.add(p.doc,'form',{id:'foreign-owner'});
    input.setAttribute('form','foreign-owner');input.files=[{}];assert.equal(input.form,foreign);
   }
  }
  h.publish(1);p.onYield=()=>{
   if(change==='insert')input=create();
   if(change==='associate')input.setAttribute('form','composer-owner');
   input.files=[{}];
  };await h.tick();assert.equal(p.clicks,0,change);assert.equal(input.form,p.owner);
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
  const after=p.editor.cloneNode(true);p.onYield=()=>{};input.files=[];await h.wake();assert(p.editor.isEqualNode(after));assert.equal(p.clicks,0);
 }
});
test('external file inputs: foreign selections allow Send; unowned selections do not acquire ownership or Send',async()=>{
 for(const owner of [false,true])for(const explicit of [false,true]) {
  const h=await setup({owner}),p=h.page,foreign=p.add(p.doc,'form',{id:'foreign-owner'});
  // Explicit form association overrides a physical ancestor form, not just containment.
  const input=p.add(explicit?(p.owner||p.doc):foreign,'input',{type:'file',hidden:'',...(explicit?{form:'foreign-owner'}:{})});
  input.files=[{}];assert.equal(input.form,foreign);assert(!p.body.contains(input));h.publish(1);await h.tick();
  assert.equal(p.clicks,1);assert.equal(p.choiceButtons().length,0);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
 }
 const h=await setup(),p=h.page,input=p.add(p.doc,'input',{type:'file',hidden:''});input.files=[{}];
 assert.equal(input.form,null);h.publish(1);await h.tick();assert.equal(p.clicks,0);
 assert.equal(p.choiceButtons().length,0);assert.equal(h.state.automation.deliveries[0].code,'ATTACHMENT');
 assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.editor.textContent,'');
});
for(const owner of [false,true])for(const phase of ['before prepare','after prefill'])
test('unowned selection: '+phase+', native owner='+owner+' blocks automatic Send without claiming ownership',async()=>{
  const h=await setup({owner}),p=h.page,input=p.add(p.doc,'input',{type:'file',hidden:''}),file={};
  assert.equal(input.form,null);assert(!p.body.contains(input));h.publish(1);
  if(phase==='before prepare')input.files=[file];else p.onYield=()=>{input.files=[file];};
  await h.tick();assert.equal(p.clicks,0,phase+': owner='+owner);assert.equal(input.files[0],file);assert.equal(p.choiceButtons().length,0);
  if(phase==='before prepare') {
   assert.equal(p.editor.textContent,'');assert.deepEqual(h.state.automation.consumed,[]);
   assert.equal(h.state.automation.deliveries[0].code,'ATTACHMENT');assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
   assert(!h.calls.some(c=>c.op==='commit'));await h.wake();assert.equal(p.clicks,0);assert.deepEqual(h.state.automation.consumed,[]);
  } else {
   assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
   assert.equal(p.editor.textContent,completionMessage({...event(1),noticeVersion:2}));
  }
  const after=p.editor.cloneNode(true);p.onYield=()=>{};input.files=[];await h.wake();
  if(phase==='before prepare')assert.equal(p.clicks,1);else {assert.equal(p.clicks,0);assert(p.editor.isEqualNode(after));}
  await h.wake();assert.equal(p.clicks,phase==='before prepare'?1:0);
});
test('unowned selection: existing plain or rich Chinese draft still allows explicit Append or Ignore without Send',async()=>{
 for(const owner of [false,true])for(const rich of [false,true])for(const choice of ['append','ignore']) {
  const h=await setup({owner}),p=h.page;draft(p,'中文草稿');if(rich)p.add(p.editor.lastChild,'strong',{class:'rich'}).textContent='保留格式🙂';
  const input=p.add(p.doc,'input',{type:'file',hidden:''}),file={};input.files=[file];assert.equal(input.form,null);
  const original=[...p.editor.childNodes],copy=p.editor.cloneNode(true);h.publish(1);await h.tick();
  assert.equal(p.choiceButtons().length,2);assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.clicks,0);
  p.userClick(p.choiceButtons()[choice==='append'?0:1]);await flush();assert.deepEqual(h.getResult(),{ok:true});
  assert.equal(p.clicks,0);assert.equal(input.files[0],file);assert(original.every((n,i)=>p.editor.childNodes[i]===n&&n.isEqualNode(copy.childNodes[i])));
  assert.equal(p.editor.childNodes.length,original.length+(choice==='append'?1:0));
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);const after=p.editor.cloneNode(true);await h.wake();assert(p.editor.isEqualNode(after));
 }
});
for(const phase of ['draft_prepare','draft_commit','after append'])test('manual choice: body input reassociation at '+phase+' preserves the current draft and files',async()=>{
 for(const owner of [true,false]) {
  const h=await setup({owner}),p=h.page;draft(p,'保留中文草稿');p.body.appendChild(p.file);const file={};p.file.files=[file];
  const foreign=p.add(p.doc,'form',{id:'foreign-owner'});assert.equal(p.file.form,p.owner);h.publish(1);await h.tick();
  const mutate=()=>p.file.setAttribute('form','foreign-owner');
  if(phase==='after append')p.onYield=mutate;else h.pageHook=async(b,r)=>{if(r.op===phase)mutate();};
  p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true},phase);
  assert.equal(p.file.form,foreign);assert.equal(p.file.files[0],file);assert.equal(p.clicks,0);
  assert.equal(p.editor.childNodes.length,2);
  const after=p.editor.cloneNode(true);p.onYield=()=>{};h.pageHook=async()=>{};await h.wake();assert(p.editor.isEqualNode(after));
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);assert.equal(p.choiceButtons().length,0);
 }
});
test('native owner progress: automatic path waits; explicit Append leaves later progress untouched',async()=>{
 for(const attrs of [{role:'progressbar'},{'data-testid':'upload-progress'},{'aria-busy':'true'}])for(const phase of ['draft_commit','after append']) {
  const h=await setup({owner:true}),p=h.page;draft(p,'保留中文草稿');p.body.appendChild(p.file);p.file.files=[{}];
  let progress=p.add(p.owner,'span',attrs);assert(!p.body.contains(progress));h.publish(1);await h.tick();
  assert.equal(p.choiceButtons().length,0);assert.equal(h.state.automation.deliveries[0].code,'COMPOSER_NOT_READY');
  assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.clicks,0);progress.remove();await h.wake();assert.equal(p.choiceButtons().length,2);
  const busy=()=>{progress=p.add(p.owner,'span',attrs);};
  if(phase==='after append')p.onYield=busy;else h.pageHook=async(b,r)=>{if(r.op===phase)busy();};
  p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true});assert.equal(p.editor.childNodes.length,2);assert.equal(p.clicks,0);assert(progress.isConnected);
  const after=p.editor.cloneNode(true);progress.remove();h.pageHook=async()=>{};p.onYield=()=>{};await h.wake();assert(p.editor.isEqualNode(after));
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);assert.equal(p.choiceButtons().length,0);
 }
});
test('native owner progress: unrelated foreign-form and page spinners do not block a safe composer',async()=>{
 for(const owner of [false,true]) {
  const h=await setup({owner}),p=h.page,foreign=p.add(p.doc,'form');
  p.add(foreign,'span',{role:'progressbar'});p.add(p.doc,'span',{'aria-busy':'true'});h.publish(1);await h.tick();
  assert.equal(p.clicks,1);assert.deepEqual(h.state.automation.deliveries,[]);
 }
});
test('external file inputs: rebuilding an unselected external picker does not invalidate an explicit draft choice',async()=>{
 const h=await setup({owner:true}),p=h.page;p.owner.setAttribute('id','composer-owner');draft(p,'保留中文草稿');
 const input=p.add(p.doc,'input',{type:'file',hidden:'',form:'composer-owner'});assert.equal(input.files.length,0);
 h.publish(1);await h.tick();h.pageHook=async(b,r)=>{if(r.op==='draft_commit')input.parentNode.replaceChild(input.cloneNode(true),input);};
 p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true});assert.equal(p.clicks,0);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
});
test('external file inputs: explicit Append permits current selection/association without sending files',async()=>{
 for(const phase of ['draft_prepare','draft_commit','after append'])for(const change of ['selection','owner']) {
  const h=await setup({owner:true}),p=h.page;p.owner.setAttribute('id','composer-owner');draft(p,'保留中文草稿');
  const input=p.add(p.doc,'input',{type:'file',hidden:'',form:'composer-owner'});input.files=[{}];h.publish(1);await h.tick();
  const mutate=()=>{if(change==='selection')input.files=[{}];else input.setAttribute('form','not-the-owner');};
  if(phase==='after append')p.onYield=mutate;else h.pageHook=async(b,r)=>{if(r.op===phase)mutate();};
  assert.equal(p.choiceButtons().length,2);p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true});
  assert.equal(p.clicks,0);assert.equal(p.editor.childNodes.length,2);
  const copy=p.editor.cloneNode(true);p.onYield=()=>{};h.pageHook=async()=>{};await h.wake();assert(p.editor.isEqualNode(copy));
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);assert.equal(p.choiceButtons().length,0);
 }
});
test('attachments: stable Chinese or attachment-only drafts offer both choices without sending or altering attachments',async()=>{
 const fixtures=[
  p=>{p.attachments.hidden=false;const chip=p.add(p.attachments,'div');p.add(chip,'span').textContent='synthetic-file.pdf';p.add(chip,'img');return chip;},
  p=>{const chip=p.add(p.body,'div',{'data-testid':'attachment'});chip.textContent='synthetic-file.pdf';return chip;},
  p=>p.add(p.body,'img',{src:'blob:synthetic-image'}),
  p=>{p.body.appendChild(p.file);p.file.files=[{name:'synthetic-file.pdf'}];return p.file;}
 ];
 for(const attach of fixtures)for(const value of ['普通中文草稿，保留图片和文件。',''])for(const choice of ['append','ignore']) {
  const h=await setup(),p=h.page;if(value)draft(p,value);
  const node=attach(p),copy=node.cloneNode(true),files=[...p.file.files],editor=p.editor.cloneNode(true),original=[...p.editor.childNodes];let inputs=0;
  p.editor.addEventListener('input',()=>inputs++);h.publish(1);await h.tick();
  assert.equal(p.choiceButtons().length,2);assert.equal(h.state.automation.deliveries[0].code,'DRAFT_CHOICE_PENDING');
  assert.equal(h.state.automation.deliveries[0].intentAt,undefined);assert.deepEqual(h.state.automation.consumed,[]);
  assert(p.editor.isEqualNode(editor));assert(node.isEqualNode(copy));assert.equal(inputs,0);assert.equal(p.clicks,0);
  await h.wake();const button=p.choiceButtons()[choice==='append'?0:1];p.userClick(button);p.userClick(button);await flush();
  assert.deepEqual(h.getResult(),{ok:true});assert.equal(h.messages.length,1);assert.equal(p.clicks,0);
  assert(node.isConnected&&node.isEqualNode(copy));assert.deepEqual(p.file.files,files);
  assert(original.every((n,i)=>p.editor.childNodes[i]===n&&n.isEqualNode(editor.childNodes[i])));
  assert.equal(p.editor.childNodes.length,original.length+(choice==='append'?1:0));assert.equal(inputs,choice==='append'?1:0);
  assert.equal(text(p),choice==='append'?value+'\n'+completionMessage({...event(1),noticeVersion:2}):value);
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
  assert(!JSON.stringify(h.state).includes('synthetic-file.pdf'));assert(!JSON.stringify(h.state).includes('普通中文草稿'));
  assert(!JSON.stringify(h.messages).includes('synthetic-file.pdf'));const after=p.editor.cloneNode(true);await h.wake();
  assert(p.editor.isEqualNode(after));assert(node.isEqualNode(copy));assert.equal(p.choiceButtons().length,0);
 }
});
test('attachments: visible upload progress or busy state waits, then reoffers the same unattempted completion',async()=>{
 for(const attrs of [{role:'progressbar'},{'data-testid':'upload-progress'},{'aria-busy':'true'}]) {
  const h=await setup(),p=h.page;draft(p,'中文草稿');p.attachments.hidden=false;
  const chip=p.add(p.attachments,'div'),progress=p.add(chip,'span',attrs);h.publish(1);await h.tick();
  assert.equal(p.choiceButtons().length,0);assert.equal(h.state.automation.deliveries[0].code,'COMPOSER_NOT_READY');
  assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.clicks,0);assert.equal(text(p),'中文草稿');
  progress.remove();await h.wake();assert.equal(p.choiceButtons().length,2);assert.equal(h.state.automation.deliveries[0].work_ref,event(1).work_ref);
 }
});
test('attachments: explicit Append permits concurrent attachment edits and never modifies or sends them',async()=>{
 for(const phase of ['draft_prepare','draft_commit','after append'])for(const kind of ['chip text','chip replacement','external marker','file selection']) {
  const h=await setup(),p=h.page;draft(p,'原有中文草稿');p.attachments.hidden=false;
  const chip=p.add(p.attachments,'div');chip.textContent='original attachment';p.body.appendChild(p.file);p.file.files=[{}];
  const marker=p.add(p.body,'div',{'data-testid':'attachment'});h.publish(1);await h.tick();assert.equal(p.choiceButtons().length,2);
  const mutate=()=>{
   if(kind==='chip text')chip.textContent='changed attachment';
   if(kind==='chip replacement')chip.parentNode.replaceChild(chip.cloneNode(true),chip);
   if(kind==='external marker')marker.parentNode.replaceChild(marker.cloneNode(true),marker);
   if(kind==='file selection')p.file.files=[{}];
  };
  if(phase==='after append')p.onYield=mutate;else h.pageHook=async(b,r)=>{if(r.op===phase)mutate();};
  p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true},phase+': '+kind);assert.equal(p.clicks,0);
  assert.equal(p.editor.childNodes.length,2);
  const after=p.editor.cloneNode(true),attachments=p.attachments.cloneNode(true);p.onYield=()=>{};h.pageHook=async()=>{};
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
  await h.wake();assert.equal(p.choiceButtons().length,0);
  assert(p.editor.isEqualNode(after));assert(p.attachments.isEqualNode(attachments));assert.equal(h.messages.length,1);
 }
});
test('attachments: appearing after automatic prefill prevents Send and never replays the consumed real Work',async()=>{
 for(const attach of [p=>p.add(p.attachments,'span'),p=>p.add(p.body,'div',{'data-testid':'attachment'}),
  p=>p.add(p.body,'img'),p=>{p.body.appendChild(p.file);p.file.files=[{}];}]) {
  const h=await setup(),p=h.page;h.publish(1);let once=false;
  p.onYield=()=>{if(!once){once=true;attach(p);}};await h.tick();
  assert.equal(p.clicks,0);assert.deepEqual(h.state.automation.deliveries,[]);
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);const after=p.editor.cloneNode(true);p.onYield=()=>{};
  await h.wake();assert(p.editor.isEqualNode(after));assert.equal(p.choiceButtons().length,0);assert.equal(p.clicks,0);
  h.publish(2);await h.wake();assert.equal(p.choiceButtons().length,2);assert.equal(p.clicks,0);
  assert.equal(h.state.automation.deliveries[0].work_ref,event(2).work_ref);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
 }
});
for(const choice of ['append','ignore'])test('minimum contract: opaque linked/media draft choices need no auxiliary or primary toolbar controls: '+choice,async()=>{
 const h=await setup(),p=h.page;draft(p,'current draft');
 const para=p.editor.lastChild;p.add(para,'a',{href:'https://example.invalid/'}).textContent='链接';
 p.add(para,'span',{'data-state':'open',class:'rich'}).textContent='富文本';p.add(para,'img');
 for(const control of [p.addContext,p.reasoning,p.dictate,p.button])control.remove();
 const copy=p.editor.cloneNode(true),original=[...p.editor.childNodes];h.publish(1);await h.tick();
 assert.equal(p.choiceButtons().length,2);assert(p.editor.isEqualNode(copy));
 p.userClick(p.choiceButtons()[choice==='append'?0:1]);await flush();assert.deepEqual(h.getResult(),{ok:true});
 assert.equal(p.clicks,0);assert(original.every((n,i)=>p.editor.childNodes[i]===n && n.isEqualNode(copy.childNodes[i])));
 assert.equal(p.editor.childNodes.length,original.length+(choice==='append'?1:0));
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.consumed.length,1);
});
test('minimum contract: clicked disconnected offer never claims a visible pending choice while its message is unresolved',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 h.page.onPageMessage=()=>new Promise(()=>{});h.page.userClick(h.page.choiceButtons()[0]);
 const offer=h.page.window.__bridgeDraftChoiceV1;assert.equal(offer.host.isConnected,false);
 h.page.clock.now+=180000;await h.wake();
 assert.equal(h.state.automation.deliveries[0].code,'DRAFT_CHOICE_UNCONFIRMED');
 assert.equal(h.state.automation.deliveries[0].intentAt,undefined);assert.equal(h.page.window.__bridgeDraftChoiceV1,offer);
 assert.equal(h.page.clicks,0);assert.equal(text(h.page),'draft');
});
test('minimum contract: a text-free media draft is not empty and can only be handled through an explicit choice',async()=>{
 for(const choice of ['append','ignore']) {
  const h=await setup(),p=h.page;draft(p,'');const para=p.editor.lastChild,img=p.add(para,'img');
  h.publish(1);await h.tick();assert.equal(p.choiceButtons().length,2);assert.equal(p.clicks,0);
  assert(!h.calls.some(c=>c.op==='commit'));p.userClick(p.choiceButtons()[choice==='append'?0:1]);await flush();
  assert.deepEqual(h.getResult(),{ok:true});assert.equal(p.editor.childNodes[0],para);assert.equal(para.childNodes[0],img);
  assert.equal(p.editor.childNodes.length,choice==='append'?2:1);assert.equal(p.clicks,0);
  assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.consumed.length,1);
 }
});
test('draft_commit reports exact document-proven blocked_before_mutation only before any DOM/input effect',async()=>{
 for(const kind of ['IME','route','wrong lease']) {
  const h=await setup(),p=h.page;draft(p,'preserved draft');h.publish(1);await h.tick();
  p.onPageMessage=()=>new Promise(()=>{});p.userClick(p.choiceButtons()[0]);
  const binding=h.state.binding,token=p.window.__bridgeDraftChoiceV1.token;
  const packet={eventId:event(1).work_ref,reportSha:sha,noticeVersion:2,token};
  const ready=await h.io.page(binding,{...packet,op:'draft_prepare'});assert.equal(ready.ok,true);
  if(kind==='IME')p.doc.emit({type:'compositionstart',target:p.editor});
  if(kind==='wrong lease')ready.lease='not-the-lease';
  if(kind==='route')p.location.href=OTHER;
  const before=p.body.cloneNode(true),connected=p.window.__bridgeDraftChoiceV1.host.isConnected;let inputs=0;
  p.doc.addEventListener('input',()=>inputs++);
  const result=await h.io.page(binding,{...packet,op:'draft_commit',lease:ready.lease});
  const code={IME:'IME_ACTIVE',route:'ROUTE_CHANGED_REBIND'}[kind] || 'DRAFT_CHOICE_STALE';
  assert.deepEqual(result,{ok:true,stage:'blocked_before_mutation',code,documentId:'doc-1'});
  assert(p.body.isEqualNode(before));assert.equal(inputs,0);assert.equal(p.clicks,0);
  assert.equal(p.window.__bridgeDraftChoiceV1.host.isConnected,connected);
 }
});
test('draft_commit never labels an after-append reconciliation or input exception as a pre-mutation refusal',async()=>{
 for(const kind of ['reconciliation','input exception']) {
  const h=await setup(),p=h.page;draft(p,'preserved draft');h.publish(1);await h.tick();
  let response;const page=h.io.page;h.io.page=async(b,r)=>{const result=await page(b,r);if(r.op==='draft_commit')response=result;return result;};
  if(kind==='reconciliation')p.onYield=()=>p.editor.lastChild.childNodes[0].nodeValue='external notice';
  else p.editor.addEventListener('input',()=>{throw Error('HOST_INPUT_EXCEPTION');});
  p.userClick(p.choiceButtons()[0]);await flush();
  assert.notEqual(response?.stage,'blocked_before_mutation');assert.equal(h.getResult().ok,false);
  assert.equal(p.editor.childNodes.length,2);assert.equal(p.clicks,0);
  assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.consumed.length,1);
 }
});
test('draft offer does not mutate, focus, expose prompt text or allocate an intent; untrusted clicks do nothing',async()=>{
 const h=await setup();draft(h.page,'synthetic private draft');h.publish(1);await h.tick();
 const buttons=h.page.choiceButtons();assert.equal(buttons.length,2);assert.equal(text(h.page),'synthetic private draft');
 assert.equal(h.page.clicks,0);assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
 assert.equal(h.state.automation.deliveries[0].merge,undefined);assert.equal(h.page.window.__bridgeDraftChoiceV1.host.shadowRoot,undefined);
 buttons[0].click();await flush();assert.equal(h.messages.length,0);assert.equal(text(h.page),'synthetic private draft');
 await h.wake();assert.equal(h.page.choiceButtons()[0],buttons[0]);assert.equal(h.page.clicks,0);
});
for(const choice of ['append','ignore'])test('explicit '+choice+' has one shared handled terminal and no Send/receipt, including double click and restart',async()=>{
 const h=await setup();draft(h.page,'latest draft');h.publish(1);h.publish(2);await h.tick();
 const expected=mergedNotice([event(1),event(2)].map(noticeItem));
 const buttons=h.page.choiceButtons(),clicked=buttons[choice==='append'?0:1];
 h.page.userClick(clicked);h.page.userClick(clicked);await flush();
 assert.deepEqual(h.getResult(),{ok:true});assert.equal(h.messages.length,1);assert.equal(h.page.choiceButtons().length,0);
 assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref,event(2).work_ref]);
 assert.equal(h.page.clicks,0);assert.equal(text(h.page),choice==='append'?'latest draft\n'+expected:'latest draft');
 assert(!JSON.stringify(h.messages).includes('latest draft'));assert(!JSON.stringify(h.state).includes('latest draft'));
 await h.wake();assert.equal(h.page.clicks,0);assert.equal(h.page.choiceButtons().length,0);
});
test('offer reads latest draft only on explicit choice; preserves paragraphs, newline and caret without flattening',async()=>{
 const h=await setup();draft(h.page,'earlier');h.publish(1);await h.tick();const button=h.page.choiceButtons()[0];
 draft(h.page,'latest');const first=h.page.editor.lastChild;h.page.add(h.page.editor,'p').textContent='second paragraph';
 h.page.userClick(button);await flush();assert.deepEqual(h.getResult(),{ok:true});
 assert.equal(h.page.editor.childNodes[0],first);assert.equal(first.textContent,'latest');
 assert.equal(text(h.page),'latest\nsecond paragraph\n'+completionMessage({...event(1),noticeVersion:2}));
 assert.equal(h.page.clicks,0);
});
test('close, worker restart and exact-route refresh leave undecided backlog durable and offer again',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();const row=h.state.automation.deliveries[0];
 h.io.exactTabs=async()=>[];await h.wake();assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
 const replacement=fixture();draft(replacement,'reopened draft');h.pages.set(1,replacement);
 h.io.exactTabs=async r=>r===CHAT?[{id:1,incognito:false}]:[];
 await h.wake();replacement.clock.now+=2100;await h.wake();
 assert.equal(replacement.choiceButtons().length,2);assert.equal(h.state.automation.deliveries[0].work_ref,row.work_ref);
 assert.equal(h.state.automation.deliveries[0].intentAt,undefined);assert.equal(replacement.clicks,0);
});
test('no choice then an empty composer retires offer and uses existing automatic Send exactly once',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();assert.equal(h.page.choiceButtons().length,2);
 h.page.edit('');h.page.renderVoice();h.page.clock.now+=2100;await h.wake();
 assert.equal(h.page.choiceButtons().length,0);assert.equal(h.page.clicks,1);
 assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
 await h.wake();assert.equal(h.page.clicks,1);
});
for(const kind of ['IME','unexpected editable','duplicate tabs','navigation'])test('choice fails closed on '+kind+' without mutation',async()=>{
 const h=await setup();draft(h.page,'original');h.publish(1);await h.tick();const button=h.page.choiceButtons()[0];
 if(kind==='IME')h.page.doc.emit({type:'compositionstart',target:h.page.editor});
 if(kind==='unexpected editable')h.page.add(h.page.footer,'div',{contenteditable:'true'});
 if(kind==='duplicate tabs')h.io.exactTabs=async()=>[{id:1},{id:2}];
 if(kind==='navigation')h.page.navigate(OTHER);
 h.page.userClick(button);await flush();
 assert.equal(text(h.page),'original');assert.equal(h.page.clicks,0);
 assert.notEqual(h.state.automation.deliveries[0].status,'handled');
});
test('save must ACK intent before append; failed intent save does not mutate or claim completion',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 h.writeHook=s=>{if(s.automation.consumed.includes(event(1).work_ref))throw Error('WRITE_FAILED');};
 h.page.userClick(h.page.choiceButtons()[0]);await flush();
 assert.equal(text(h.page),'draft');assert.equal(h.page.clicks,0);assert.equal(h.getResult().ok,false);
 assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
});
test('lost append result never appends twice or writes a terminal history row',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 const page=h.io.page;h.io.page=async(b,r)=>{const result=await page(b,r);if(r.op==='draft_commit')throw Error('ACK_LOST');return result;};
 h.page.userClick(h.page.choiceButtons()[0]);await flush();const after=text(h.page);
 assert.equal(after,'draft\n'+completionMessage({...event(1),noticeVersion:2}));
 assert.equal(h.getResult().ok,false);assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);h.io.page=page;
 await h.wake();h.publish(2);await h.wake();assert.equal(text(h.page),after);assert.equal(h.page.clicks,0);
 assert.equal(h.state.automation.deliveries.length,1);assert.equal(h.state.automation.deliveries[0].work_ref,event(2).work_ref);
});
test('successful diagnostic Bind retires the previous Chat offer without changing receiver or pending deliveries',async()=>{
 const h=await setup();draft(h.page,'original draft');h.publish(1);await h.tick();
 const deliveries=structuredClone(h.state.automation.deliveries);
 assert.equal(h.page.choiceButtons().length,2);h.selected=2;
 await h.worker.run('bind');
 assert.equal(h.page.choiceButtons().length,0);assert.equal(h.state.binding.route,OTHER);
 assert.equal(h.state.automation.route,CHAT);assert.deepEqual(h.state.automation.deliveries,deliveries);
 assert.equal(deliveries[0].status,'waiting');assert.equal(deliveries[0].intentAt,undefined);
 assert.equal(text(h.page),'original draft');assert.equal(text(h.pages.get(2)),'');
 assert.equal(h.messages.length,0);assert.equal(h.page.clicks,0);assert.equal(h.pages.get(2).clicks,0);
});
test('failed diagnostic Bind preserves the old offer and does not claim a new receiver or handled delivery',async()=>{
 const h=await setup();draft(h.page,'original draft');h.publish(1);await h.tick();
 const buttons=h.page.choiceButtons(),deliveries=structuredClone(h.state.automation.deliveries);h.selected=2;
 h.pageHook=async(b,r)=>{if(r.op==='bind')throw Error('BIND_FAILED');};
 await assert.rejects(h.worker.run('bind'),/BIND_FAILED/);
 assert.deepEqual(h.page.choiceButtons(),buttons);assert.equal(h.state.binding,null);
 assert.equal(h.state.automation.route,CHAT);assert.deepEqual(h.state.automation.deliveries,deliveries);
 assert.equal(text(h.page),'original draft');assert.equal(text(h.pages.get(2)),'');
 assert.equal(h.messages.length,0);assert.equal(h.page.clicks,0);assert.equal(h.pages.get(2).clicks,0);
});
test('new feed membership invalidates clicked offer before intent; later offer groups each identity once',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();const old=h.page.choiceButtons()[0];
 h.publish(2);await h.tick();h.page.userClick(old);await flush();assert.equal(text(h.page),'draft');assert.equal(h.messages.length,0);
 h.page.userClick(h.page.choiceButtons()[0]);await flush();const rows=h.state.automation.deliveries;
 assert.deepEqual(rows,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref,event(2).work_ref]);assert.equal(h.messages.length,1);
});
for(const choice of ['append','ignore'])test('opaque draft '+choice+': long Chinese rich paragraphs and simple 1 retain all original nodes/formatting',async()=>{
 for(const rich of [true,false]) {
  const h=await setup(),p=h.page;draft(p,rich?'':'1');
  if(rich) {
   const span=p.add(p.editor.lastChild,'span',{class:'restored-rich',style:'color: blue; font-weight: 700;'});
   p.add(span,'strong').textContent='合成草稿标记。请先说明判断依据，再比较不同方案；不要改变原有目标。'.repeat(12000);
   p.add(span,'em').textContent='补充说明：换行和软折行保持原样，汉🙂e\u0301。';
   const quote=p.add(p.editor,'blockquote',{class:'rich-wrapper'}),para=p.add(quote,'p');
   para.textContent='第二段保持格式。';p.add(para,'br');para.appendChild(p.doc.createTextNode('这是实际硬换行后的内容。'));
   p.renderSend();
  }
  const original=[...p.editor.childNodes],copies=original.map(n=>n.cloneNode(true)),before=text(p),inputs=[];
  const nested=p.editor.querySelectorAll('*').map(node=>({node,children:[...node.childNodes]}));
  p.editor.focus=()=>assert.fail('append must not focus editor');p.window.getSelection=()=>assert.fail('append must not move selection');
  p.doc.addEventListener('input',e=>inputs.push(e.data));h.publish(1);await h.tick();
  assert.equal(p.choiceButtons().length,2);assert.equal(text(p),before);assert.equal(inputs.length,0);
  const button=p.choiceButtons()[choice==='append'?0:1];p.userClick(button);p.userClick(button);await flush();
  assert.deepEqual(h.getResult(),{ok:true});assert.equal(p.clicks,0);assert.equal(h.messages.length,1);
  assert(original.every((n,i)=>p.editor.childNodes[i]===n && n.isEqualNode(copies[i])));
  assert(nested.every(({node,children})=>node.isConnected && children.every((child,i)=>node.childNodes[i]===child)));
  const notice=completionMessage({...event(1),noticeVersion:2});
  if(choice==='append') {
   assert.equal(p.editor.childNodes.length,original.length+1);assert.equal(p.editor.lastChild.tagName,'P');
   assert.equal(p.editor.lastChild.textContent,notice);assert.equal(text(p),before+'\n'+notice);
   assert.deepEqual(inputs,['\n'+notice]);
  }else {assert.equal(p.editor.childNodes.length,original.length);assert.equal(text(p),before);assert.deepEqual(inputs,[]);}
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
  if(rich)assert(!JSON.stringify([h.state,h.messages]).includes('合成草稿标记'));
  assert.deepEqual(Object.keys(h.messages[0]).sort(),['action','project_ref','token']);
  await h.wake();assert.equal(p.choiceButtons().length,0);assert.equal(p.clicks,0);assert.equal(text(p),choice==='append'?before+'\n'+notice:before);
 }
});
test('explicit recipient switch retires old offer, keeps old unknown exact, and moves only clean backlog',async()=>{
 const h=await setup(),page=h.io.page;h.publish(1);
 h.io.page=async(b,r)=>{const result=await page(b,r);if(r.op==='commit')throw Error('ACK_LOST');return result;};
 await h.tick();h.io.page=page;const old=event(1).work_ref;
 assert.deepEqual(h.state.automation.deliveries,[]);assert(h.state.automation.consumed.includes(old));
 h.publish(2);await h.tick();draft(h.pages.get(2),'new draft');h.selected=2;
 await h.worker.run('enable',{delayMs:0});h.pages.get(2).clock.now+=2100;await h.tick();
 assert(h.state.automation.consumed.includes(old));assert.equal(h.state.automation.deliveries[0].route,OTHER);
 assert.equal(h.pages.get(2).choiceButtons().length,2);h.pages.get(2).userClick(h.pages.get(2).choiceButtons()[1]);await flush();
 assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[old,event(2).work_ref]);
 assert.equal(h.page.clicks,1);assert.equal(h.pages.get(2).clicks,0);
});
test('same-Chat append and ignore handle only distinct new Work despite attributed or unattributed old unknown',async()=>{
 for(const oldRoute of [CHAT,undefined])for(const choice of ['append','ignore']) {
  const h=await setup(),s=h.state,old={...event(1),epoch,route:oldRoute,status:'attempted_unknown',
   intentAt:10,outcome:'unknown',code:'COMMIT_API_UNKNOWN_NO_RETRY'};
  s.automation.deliveries=[old];s.automation.cursor=1;h.state=s;
  draft(h.page,'current draft');h.publish(1);h.publish(2);await h.tick();
  assert.equal(h.page.choiceButtons().length,2);assert.equal(h.page.clicks,0);
  h.page.userClick(h.page.choiceButtons()[choice==='append'?0:1]);await flush();
  assert.deepEqual(h.getResult(),{ok:true});const row={...event(2),noticeVersion:2};
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[old.work_ref,event(2).work_ref]);
  assert.equal(text(h.page),choice==='append'?'current draft\n'+completionMessage(row):'current draft');
  await h.wake();assert.equal(h.page.choiceButtons().length,0);assert.equal(h.page.clicks,0);
  assert.deepEqual(h.state.automation.deliveries,[]);assert(h.state.automation.consumed.includes(old.work_ref));
 }
});
test('wired native worker choice uses exact sender document and route locks, survives worker replacement, and sends nothing',async()=>{
 const f=wired([A]);assert.equal((await f.send(A,'enable',{delayMs:0})).ok,true);const p=f.pages.get(1);p.clock.now+=2100;
 draft(p,'draft');f.publish(A,1);f.listeners.alarm({name:'bridge-completion-poll'});await settle();
 assert.equal(p.choiceButtons().length,2);
 f.rewire();p.userClick(p.choiceButtons()[1]);await settle();await flush();
 const s=await f.readState(A);assert.deepEqual(s.automation.deliveries,[]);assert.equal(p.clicks,0);
 assert.equal(text(p),'draft');assert.equal(s.automation.consumed.length,1);
});


test('lost pre-mutation intent ACK freezes choice without appending, across later wakeups',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 const write=h.io.write;let lost=false;
 h.io.write=async(k,s)=>{await write(k,s);if(!lost&&s.automation.consumed.includes(event(1).work_ref)){lost=true;throw Error('ACK_LOST');}};
 h.page.userClick(h.page.choiceButtons()[0]);await flush();
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(text(h.page),'draft');
 h.io.write=write;
 await h.wake();assert.deepEqual(h.state.automation.deliveries,[]);
 assert(h.state.automation.consumed.includes(event(1).work_ref));assert.equal(text(h.page),'draft');
 assert(!h.calls.some(c=>c.op==='draft_commit'));
});
test('ignore waits for the one pre-mutation durable write, without a second terminal write',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 const write=h.io.write;let entered,release,writes=0;const waiting=new Promise(r=>entered=r),gate=new Promise(r=>release=r);
 h.io.write=async(k,s)=>{if(s.automation.consumed.includes(event(1).work_ref)){writes++;entered();await gate;}await write(k,s);};
 h.page.userClick(h.page.choiceButtons()[1]);await waiting;
 assert.equal(h.getResult(),undefined);assert.equal(h.state.automation.deliveries.length,1);
 assert.equal(text(h.page),'draft');release();await flush();assert.deepEqual(h.getResult(),{ok:true});
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(writes,1);assert.equal(h.page.clicks,0);
});
for(const drift of ['document','binding','draft reconciliation'])test('post-intent '+drift+' drift leaves uncertainty pinned without another append',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 const page=h.io.page;
 if(drift==='document')h.io.page=async(b,r)=>{if(r.op==='draft_commit')throw Error('DOCUMENT_CHANGED');return page(b,r);};
 if(drift==='binding')h.pageHook=async(b,r)=>{if(r.op==='draft_commit')await h.page.op({op:'bind',route:CHAT,generation:'replacement'});};
 if(drift==='draft reconciliation')h.page.onYield=()=>{h.page.editor.textContent='external reconciliation';};
 h.page.userClick(h.page.choiceButtons()[0]);await flush();
 const after=h.page.editor.textContent;
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.page.clicks,0);
 h.io.page=page;h.pageHook=async()=>{};h.page.onYield=()=>{};
 await h.wake();assert.equal(h.page.editor.textContent,after);assert.equal(h.page.choiceButtons().length,0);
});
test('legacy handled plus queued cross-epoch duplicate is suppressed without a history-cap failure',async()=>{
 const h=await setup();draft(h.page,'draft');const s=h.state;
 s.automation.deliveries=[{...event(1),epoch,route:OTHER,status:'handled',intentAt:10},
  {...event(1),epoch:'c'.repeat(32),route:CHAT,status:'queued',dueAt:0}];h.state=s;
 await h.worker.load();assert.deepEqual(h.state.automation.deliveries,[]);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);assert.equal(h.page.clicks,0);
});
test('native sender rejects page/iframe/other-document spoofing; actual append holds route before project locks',async()=>{
 const f=wired([A]),held=new Set(),order=[];
 const original=f.native.navigator.locks.request;
 f.native.navigator.locks.request=(name,opts,fn)=>original(name,opts,async lock=>{
  held.add(name);order.push(name);try{return await fn(lock);}finally{held.delete(name);}
 });
 await f.send(A,'enable',{delayMs:0});const p=f.pages.get(1);p.clock.now+=2100;draft(p,'draft');
 f.publish(A,1);f.listeners.alarm({name:'bridge-completion-poll'});await settle();
 const button=p.choiceButtons()[0];assert(button);
 const message={action:'draft_choice',project_ref:A.project_ref,token:p.window.__bridgeDraftChoiceV1.token};
 for(const sender of [
  {id:'a'.repeat(32),frameId:1,documentId:'doc-1',url:CHAT,tab:{id:1}},
  {id:'web-page',frameId:0,documentId:'doc-1',url:CHAT,tab:{id:1}},
  {id:'a'.repeat(32),frameId:0,documentId:'doc-1',url:CHAT}
 ])assert.equal(f.listeners.message(message,sender,()=>{throw Error('untrusted reply');}),false);
 const wrong=await new Promise(resolve=>f.listeners.message(message,{id:'a'.repeat(32),frameId:0,documentId:'different',url:CHAT,tab:{id:1}},resolve));
 assert.equal(wrong.ok,false);assert.equal(text(p),'draft');
 p.onYield=()=>{
  assert(held.has('bridge-notice:route:'+CHAT));assert(held.has('bridge-notice:project:'+A.scope_id));
  assert(order.lastIndexOf('bridge-notice:route:'+CHAT)<order.lastIndexOf('bridge-notice:project:'+A.scope_id));
 };
 p.userClick(button);await settle();await flush();
 const state=await f.readState(A);assert.deepEqual(state.automation.deliveries,[]);
 assert.equal(text(p),'draft\nproject_ref=alpha；Agent 已结束：work-0000000000000001。');assert.equal(p.clicks,0);
});

test('only one inline prompt per exact page; separate projects remain separate groups',async()=>{
 const f=wired([A,B]);await f.send(A,'enable',{delayMs:0});await f.send(B,'enable',{delayMs:0});
 const p=f.pages.get(1);p.clock.now+=2100;draft(p,'draft');f.publish(A,1);f.publish(B,2);
 f.listeners.alarm({name:'bridge-completion-poll'});await settle();assert.equal(p.choiceButtons().length,2);
 p.userClick(p.choiceButtons()[1]);await settle();
 const states=[await f.readState(A),await f.readState(B)];assert.equal(states.filter(s=>s.automation.consumed.length===1).length,1);
 f.listeners.alarm({name:'bridge-completion-poll'});await settle();assert.equal(p.choiceButtons().length,2);
 p.userClick(p.choiceButtons()[1]);await settle();
 assert.deepEqual((await f.readState(A)).automation.deliveries,[]);
 assert.deepEqual((await f.readState(B)).automation.deliveries,[]);assert.equal(p.clicks,0);
});
test('oversize eligible backlog handles only the offered bounded group, with no false failure or splitting frozen members',async()=>{
 const h=await setup();draft(h.page,'draft');
 for(let i=1;i<=14;i++)h.publish({batch_ref:'batch-'+i.toString(16).padStart(16,'0'),project_ref:'gpt-agent-bridge',
  sequence:i,ready_at:5,requested:528,not_submitted:0,members:Array.from({length:528},(_,n)=>({
   work_ref:'work-'+(i*1000+n).toString(16).padStart(16,'0'),state:'agent_turn_settled',result_class:'result_ready',
   classification_report_status:'readable',report_status:'readable',report_sha256:sha}))});
 await h.tick();h.page.userClick(h.page.choiceButtons()[1]);await flush();assert.deepEqual(h.getResult(),{ok:true});
 const handled=h.state.automation.consumed;
 assert(handled.length>1 && handled.length<14);assert.equal(h.state.automation.deliveries.length,14-handled.length);
 assert(h.state.automation.deliveries.every(e=>['queued','waiting'].includes(e.status)&&!Object.hasOwn(e,'intentAt')&&!Object.hasOwn(e,'mergedInto')));
 await h.tick();h.page.userClick(h.page.choiceButtons()[1]);await flush();
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(h.state.automation.consumed.length,14);assert.equal(h.page.clicks,0);
});

for(const action of ['disable','unbind'])test(action+' retires an undecided prompt without consuming the real queue',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 const row=structuredClone(h.state.automation.deliveries[0]);assert.equal(h.page.choiceButtons().length,2);
 await h.worker.run(action);assert.equal(h.page.choiceButtons().length,0);
 assert.deepEqual(h.state.automation.deliveries[0],row);assert.equal(h.state.automation.enabled,false);
 assert.equal(text(h.page),'draft');assert.equal(h.page.clicks,0);
});
test('active IME protects Append without retiring the offer; compositionend permits immediate explicit Append',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();const button=h.page.choiceButtons()[0];
 h.page.doc.emit({type:'compositionstart',target:h.page.editor});h.page.userClick(button);await flush();
 assert.equal(h.messages.length,0);assert.equal(h.page.choiceButtons()[0],button);
 assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
 h.page.doc.emit({type:'compositionend',target:h.page.editor});
 h.page.userClick(button);await flush();assert.deepEqual(h.getResult(),{ok:true});assert.equal(h.page.clicks,0);
 assert.deepEqual(h.state.automation.deliveries,[]);
});

test('detached inline host is reoffered on the next poll instead of leaving a hidden permanent choice',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();
 const old=h.page.window.__bridgeDraftChoiceV1.host;old.remove();await h.wake();
 const shown=h.page.window.__bridgeDraftChoiceV1.host;assert.notEqual(shown,old);assert(shown.isConnected);
 assert.equal(h.page.choiceButtons().length,2);assert.equal(h.state.automation.deliveries[0].intentAt,undefined);
});
test('editor replacement before choice preparation appends only to the unique current bound composer',async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);await h.tick();let replacement;
 h.pageHook=async(b,r)=>{if(r.op==='draft_prepare'){
  replacement=h.page.doc.createElement('div');replacement.attrs={...h.page.editor.attrs};
  h.page.add(replacement,'p').textContent='replacement draft';h.page.rich.replaceChild(replacement,h.page.editor);
 }};
 h.page.userClick(h.page.choiceButtons()[0]);await flush();assert(replacement);
 assert.equal(replacement.textContent,'replacement draft'+completionMessage({...event(1),noticeVersion:2}));assert.deepEqual(h.getResult(),{ok:true});
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);assert.equal(h.page.clicks,0);
});

test('explicit switch while an undecided offer is visible retires it and sends the clean backlog once only in the new Chat',async()=>{
 const h=await setup();draft(h.page,'original draft');h.publish(1);await h.tick();
 const oldButton=h.page.choiceButtons()[0],before=h.state,old=structuredClone(before.automation.deliveries[0]);
 h.selected=2;await h.worker.run('enable',{delayMs:0});h.pages.get(2).clock.now+=2100;
 assert.equal(h.page.choiceButtons().length,0);h.page.userClick(oldButton);await flush();assert.equal(h.messages.length,0);
 assert.deepEqual(h.state.automation.deliveries[0],{...old,route:OTHER});
 assert.equal(h.state.automation.cursor,before.automation.cursor);assert.equal(h.state.automation.epoch,before.automation.epoch);
 await h.tick();await h.wake();assert.equal(h.page.clicks,0);assert.equal(h.pages.get(2).clicks,1);
 assert.equal(text(h.page),'original draft');assert.deepEqual(h.state.automation.deliveries,[]);
});

for(const layout of ['direct','span','attachment'])for(const choice of ['append','ignore'])
test('refresh: restored '+(layout==='span'?'formatted Chinese SPAN with Send':'direct text with Voice')+' reoffers without new Work or prompt, then '+choice+' uses the new document',async()=>{
 const f=refreshWiring([refreshProject]);let worker=f.start();await f.enable(worker,refreshProject);
 const connect=(page,documentId)=>{page.onPageMessage=message=>new Promise(resolve=>{
  const accepted=worker.listeners.message(message,{id:'a'.repeat(32),frameId:0,documentId,
   url:page.location.href,tab:{id:1,incognito:false}},resolve);
  if(!accepted)resolve({ok:false});
 });};
 const value=layout==='span'?'保留中文段落和原有格式；继续分析方案，勿替换内容。'.repeat(50)+'汉🙂e\u0301':layout==='attachment'?'':'preserved draft';let preservedSpan,preservedText,attachment;
 const restoreAttachment=p=>{p.attachments.hidden=false;attachment=p.add(p.attachments,'div');p.add(attachment,'img');};
 let page=f.pages.get(1);connect(page,f.docs.get(1));draft(page,value);f.publish(refreshProject,1);
 if(layout==='attachment')restoreAttachment(page);
 worker.tick();await settleRefresh();assert.equal(page.choiceButtons().length,2);
 const original=structuredClone((await f.record(refreshKey(refreshProject))).automation.deliveries[0]);
 for(let refresh=0;refresh<2;refresh++) {
  const previousDocument=f.docs.get(1),previousToken=page.window.__bridgeDraftChoiceV1.token;
  f.refresh();page=f.pages.get(1);connect(page,f.docs.get(1));
  // Restore DOM without a keypress or prompt; the observed SPAN case has Send.
  page.editor.textContent='';const paragraph=page.add(page.editor,'p');
  if(layout==='span') {
   preservedSpan=page.add(paragraph,'span',{class:'restored',style:'color: blue; font-weight: 700;'});preservedSpan.textContent=value;
   preservedText=preservedSpan.childNodes[0];page.renderSend();
  } else paragraph.textContent=value;
  if(layout==='attachment')restoreAttachment(page);
  assert.equal(page.button.getAttribute('aria-label'),layout==='span'?'Send':'Start Voice');
  worker=f.start();worker.tick();await settleRefresh();
  let state=await f.record(refreshKey(refreshProject));assert.notEqual(state.binding.documentId,previousDocument);
  assert.equal(state.automation.deliveries[0].code,'DRAFT_CHOICE_PENDING');
  const stale=await new Promise(resolve=>worker.listeners.message({action:'draft_choice',project_ref:refreshProject.project_ref,token:previousToken},
   {id:'a'.repeat(32),frameId:0,documentId:previousDocument,url:CHAT,tab:{id:1,incognito:false}},resolve));
  assert.equal(stale.ok,false);
  const stop=refresh===0?page.add(page.doc,'button',{'data-testid':'stop-button'}):null;
  f.advance(60000);worker.tick();await settleRefresh();
  if(stop){assert.equal(page.choiceButtons().length,2);stop.remove();f.advance(60000);worker.tick();await settleRefresh();}
  assert.equal(page.choiceButtons().length,2);const button=page.choiceButtons()[0];
  for(let minute=0;minute<3;minute++){f.advance(60000);worker.tick();await settleRefresh();assert.equal(page.choiceButtons()[0],button);}
  state=await f.record(refreshKey(refreshProject));const row=state.automation.deliveries[0];
  assert.equal(row.work_ref,original.work_ref);assert.equal(row.route,CHAT);assert.equal(row.epoch,original.epoch);
  assert.equal(state.automation.cursor,1);assert.equal(row.intentAt,undefined);assert.equal(row.merge,undefined);
  assert.equal(row.code,'DRAFT_CHOICE_PENDING');assert.equal(text(page),value);assert.equal(page.clicks,0);
 }
 const decision=page.choiceButtons()[choice==='append'?0:1];page.userClick(decision);await settleRefresh();await flush();
 const state=await f.record(refreshKey(refreshProject)),row={...original,noticeVersion:4};
 assert.deepEqual(state.automation.deliveries,[]);assert.equal(state.automation.consumed.length,1);assert.equal(page.clicks,0);
 assert.equal(text(page),choice==='append'?value+'\n'+completionMessage(row):value);
 if(layout==='attachment')assert.equal(page.attachments.childNodes[0],attachment);
 if(layout==='span') {
  assert.equal(page.editor.childNodes[0].childNodes[0],preservedSpan);
  assert.equal(preservedSpan.childNodes[0],preservedText);assert.equal(preservedText.nodeValue,value);
 }
 worker=f.start();f.advance(180000);worker.tick();await settleRefresh();assert.equal(page.choiceButtons().length,0);assert.equal(page.clicks,0);
});

test('span readback: mixed Unicode, hard breaks and original span nodes survive one exact append',async()=>{
 const h=await setup();draft(h.page,'prefix ');const p=h.page.editor.childNodes[0];
 const span=h.page.add(p,'span');span.textContent='汉🙂e\u0301';const original=span.childNodes[0];
 h.page.add(p,'br');p.appendChild(h.page.doc.createTextNode('tail'));
 const sentinel=h.page.add(p,'br',{class:'ProseMirror-trailingBreak'});
 h.publish(1);await h.tick();assert.equal(h.page.choiceButtons().length,2);
 h.page.userClick(h.page.choiceButtons()[0]);await flush();const row={...event(1),noticeVersion:2};
 assert.deepEqual(h.state.automation.deliveries,[]);assert.equal(text(h.page),'prefix 汉🙂e\u0301\ntail\n'+completionMessage(row));
 assert.equal(p.childNodes[1],span);assert.equal(span.childNodes[0],original);assert.equal(p.lastChild,sentinel);
 assert.equal(h.page.clicks,0);assert.equal(row.receipt,undefined);
});

test('current draft: a concurrent Unicode edit stays untouched while the exact appended notice is verified',async()=>{
 const h=await setup();draft(h.page,'');const p=h.page.editor.childNodes[0],span=h.page.add(p,'span');
 span.textContent='汉🙂e\u0301';h.page.renderSend();h.publish(1);await h.tick();assert.equal(h.page.choiceButtons().length,2);
 h.page.onYield=()=>{span.childNodes[0].nodeValue='汉🙂é';};
 h.page.userClick(h.page.choiceButtons()[0]);await flush();
 assert.deepEqual(h.state.automation.deliveries,[]);const row={...event(1),noticeVersion:2};assert.deepEqual(h.getResult(),{ok:true});assert.equal(span.textContent,'汉🙂é');
 assert.equal(row.receipt,undefined);const after=text(h.page);h.page.onYield=()=>{};
 await h.wake();assert.equal(text(h.page),after);assert.equal(h.page.choiceButtons().length,0);assert.equal(h.page.clicks,0);
});

test('explicit Append accepts current text, formatting and node edits without overwriting or flattening',async()=>{
 for(const kind of ['text','format','node']) {
  const h=await setup();draft(h.page,'current draft');h.publish(1);await h.tick();const p=h.page.editor.lastChild;let current;
  h.pageHook=async(b,r)=>{if(r.op==='draft_commit') {
   if(kind==='text')p.childNodes[0].nodeValue='external latest draft';
   if(kind==='format')p.setAttribute('style','font-weight:700');
   if(kind==='node')h.page.editor.replaceChild(p.cloneNode(true),p);
   current=h.page.editor.childNodes[0];
  }};
  h.page.userClick(h.page.choiceButtons()[0]);await flush();
  assert.deepEqual(h.getResult(),{ok:true});assert.equal(h.page.editor.childNodes.length,2);assert.equal(h.page.clicks,0);
  assert.equal(h.page.editor.childNodes[0],current);assert.equal(current.textContent,kind==='text'?'external latest draft':'current draft');
  if(kind==='format')assert.equal(current.getAttribute('style'),'font-weight:700');
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
 }
});

test('opaque append verifies its own notice only; changed notice stays unknown and never retries',async()=>{
 for(const kind of ['equal-text original replacement','notice change']) {
  const h=await setup();draft(h.page,'original');const p=h.page.editor.lastChild;
  h.page.add(p,'strong',{class:'rich'}).textContent='汉🙂e\u0301';h.publish(1);await h.tick();
  h.page.onYield=()=>{
   if(kind==='equal-text original replacement')h.page.editor.replaceChild(p.cloneNode(true),p);
   else h.page.editor.lastChild.childNodes[0].nodeValue='different notice';
  };
  h.page.userClick(h.page.choiceButtons()[0]);await flush();
  assert.equal(h.getResult().ok,kind==='equal-text original replacement');assert.equal(h.page.clicks,0);assert.deepEqual(h.state.automation.deliveries,[]);
  assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
  const after=h.page.editor.cloneNode(true);h.page.onYield=()=>{};await h.wake();
  assert(h.page.editor.isEqualNode(after));assert.equal(h.page.choiceButtons().length,0);
 }
});

for(const result of [{ok:false,code:'DRAFT_CHOICE_UNAVAILABLE'},null,{ok:false,code:'private draft text'}])
test('refresh: rejected or invalid offer result has a bounded truthful waiting code: '+JSON.stringify(result),async()=>{
 const h=await setup();draft(h.page,'draft');h.publish(1);const page=h.io.page;
 h.io.page=async(b,r)=>r.op==='draft_offer'?result:page(b,r);await h.tick();
 const row=h.state.automation.deliveries[0];assert.equal(row.status,'waiting');assert.equal(row.intentAt,undefined);
 assert.equal(row.code,result?.code==='DRAFT_CHOICE_UNAVAILABLE'?'DRAFT_CHOICE_UNAVAILABLE':'DRAFT_CHOICE_UNCONFIRMED');
 assert.equal(text(h.page),'draft');assert.equal(h.page.clicks,0);
});

for(const composing of [false,true])test('active draft: immediate typing/IME offers a stable nonmutating choice; Ignore never waits',async()=>{
 const h=await setup(),p=h.page;draft(p,'正在输入中文🙂');p.doc.emit({type:composing?'compositionstart':'input',target:p.editor});
 const before=p.editor.cloneNode(true);h.publish(1);await h.tick();const button=p.choiceButtons()[1];assert(button);
 await h.wake();assert.equal(p.choiceButtons()[1],button);assert(p.editor.isEqualNode(before));
 p.userClick(button);await flush();assert.deepEqual(h.getResult(),{ok:true});assert(p.editor.isEqualNode(before));
 assert.equal(p.clicks,0);assert.equal(p.window.__bridgeSyntheticNoticeV1.composing,composing);
 assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
});
test('manual Append uses latest text and files across click, async preparation and commit without a time lease',async()=>{
 const h=await setup(),p=h.page;draft(p,'早先草稿');h.publish(1);await h.tick();const button=p.choiceButtons()[0];
 p.edit('点击前的当前草稿');p.body.appendChild(p.file);p.file.files=[{}];
 h.pageHook=async(b,r)=>{if(r.op==='draft_commit'){p.edit('点击后的当前草稿🙂');p.file.files=[{}];p.clock.now+=180000;}};
 p.userClick(button);await flush();assert.deepEqual(h.getResult(),{ok:true});
 assert.equal(text(p),'点击后的当前草稿🙂\n'+completionMessage({...event(1),noticeVersion:2}));assert.equal(p.file.files.length,1);assert.equal(p.clicks,0);
 assert(!JSON.stringify(h.state).includes('当前草稿'));await h.wake();assert.equal(p.editor.childNodes.length,2);
});
for(const [submit,owner] of [['Send click',false],['Send click',true],['native submit',true],['Enter',false],['Enter',true]])test('manual Append refuses submission after choice before async mutation: '+submit+', owner='+owner,async()=>{
 const h=await setup({owner}),p=h.page;draft(p,'已决定发送的草稿');h.publish(1);await h.tick();
 h.pageHook=async(b,r)=>{if(r.op==='draft_commit'){
  if(submit==='Send click')p.button.click();
  if(submit==='native submit')p.owner.requestSubmit(p.button);
  if(submit==='Enter')p.doc.emit({type:'keydown',target:p.editor,key:'Enter'});
  p.edit('下一条消息草稿');
 }};
 p.userClick(p.choiceButtons()[0]);await flush();assert.equal(h.getResult().ok,false);assert.equal(text(p),'下一条消息草稿');
 assert.deepEqual(h.state.automation.consumed,[]);assert.equal(h.state.automation.deliveries[0].code,'DRAFT_CHOICE_STALE');
 h.pageHook=async()=>{};await h.wake();assert.equal(p.choiceButtons().length,2);
 p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true});
 assert.equal(text(p),'下一条消息草稿\n'+completionMessage({...event(1),noticeVersion:2}));assert.equal(p.clicks,submit==='Send click'?1:0);
});
test('manual Append protects composition at click and commit, then accepts immediately after compositionend',async()=>{
 const h=await setup(),p=h.page;draft(p,'合成中文');h.publish(1);await h.tick();const button=p.choiceButtons()[0];
 p.doc.emit({type:'compositionstart',target:p.editor});p.userClick(button);await flush();assert.equal(h.messages.length,0);
 assert.equal(p.choiceButtons()[0],button);p.doc.emit({type:'compositionend',target:p.editor});
 let once=true;h.pageHook=async(b,r)=>{if(once&&r.op==='draft_commit'){once=false;p.doc.emit({type:'compositionstart',target:p.editor});}};
 p.userClick(button);await flush();assert.equal(h.getResult().ok,false);assert.equal(text(p),'合成中文');assert.deepEqual(h.state.automation.consumed,[]);
 p.doc.emit({type:'compositionend',target:p.editor});await h.wake();p.userClick(p.choiceButtons()[0]);await flush();
 assert.deepEqual(h.getResult(),{ok:true});assert.equal(p.clicks,0);
});
for(const phase of ['before commit','during prefill'])for(const attachment of [false,true])
test('fresh shell: restored '+(attachment?'attachment':'text')+' '+phase+' prevents automatic Send without a guessed hydration delay',async()=>{
 const h=await setup(),p=h.page;h.publish(1);
 const restore=()=>{if(attachment){p.attachments.hidden=false;p.add(p.attachments,'span').textContent='synthetic';}else p.edit('刷新恢复的中文草稿');};
 if(phase==='before commit')h.pageHook=async(b,r)=>{if(r.op==='commit')restore();};else p.onYield=restore;
 await h.tick();assert.equal(p.clicks,0);assert.equal(attachment?p.attachments.childNodes.length:0,attachment?1:0);
 if(!attachment)assert.equal(p.editor.textContent,'刷新恢复的中文草稿');
 if(phase==='before commit')assert.deepEqual(h.state.automation.consumed,[]);else assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
});
test('fresh bind has no quiet delay, empty active IME still refuses auto Send and offers nothing',async()=>{
 const h=await setup(),p=h.page;p.clock.now-=2100;h.publish(1);p.doc.emit({type:'compositionstart',target:p.editor});
 await h.tick();assert.equal(p.clicks,0);assert.equal(p.choiceButtons().length,0);assert.equal(h.state.automation.deliveries[0].code,'IME_ACTIVE');
 p.doc.emit({type:'compositionend',target:p.editor});await h.wake();assert.equal(p.clicks,1);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
});

for(const phase of ['before commit','during prefill'])for(const content of ['text','text and attachment'])
test('new document hydration: '+content+' restores '+phase+' silently with no new input or Work',async()=>{
 const f=refreshWiring([refreshProject]);let w=f.start();await f.enable(w,refreshProject);const previous=f.docs.get(1);
 f.refresh();const p=f.pages.get(1);assert.notEqual(f.docs.get(1),previous);const draftText='恢复的中文草稿，不能被自动发送。';let restored=false;
 const restore=()=>{if(restored)return;restored=true;p.editor.textContent='';p.add(p.editor,'p').textContent=draftText;
  if(content==='text and attachment'){p.attachments.hidden=false;p.add(p.attachments,'img');}};
 if(phase==='before commit')f.hooks.scriptBefore=async s=>{if(s.args[0].op==='commit')restore();};else p.onYield=restore;
 f.publish(refreshProject,1);w=f.start();w.tick();await settleRefresh();const state=await f.record(refreshKey(refreshProject));
 assert.equal(state.binding.documentId,f.docs.get(1));assert(restored);assert.equal(p.clicks,0);assert.equal(p.editor.textContent,draftText);
 assert.equal(p.window['__bridgeNoticeProject:'+refreshProject.project_ref].revision,0);
 assert.equal(p.attachments.childNodes.length,content==='text and attachment'?1:0);
 if(phase==='before commit') {
  assert.deepEqual(state.automation.consumed,[]);assert.equal(state.automation.deliveries[0].code,'DRAFT_PRESENT');
  f.hooks.scriptBefore=async()=>{};w.tick();await settleRefresh();assert.equal(p.choiceButtons().length,2);
 } else {
  assert.equal(state.automation.consumed.length,1);assert.deepEqual(state.automation.deliveries,[]);p.onYield=()=>{};
  w=f.start();f.advance(180000);w.tick();await settleRefresh();assert.equal(p.choiceButtons().length,0);
 }
 assert.equal(p.clicks,0);assert.equal(p.editor.textContent,draftText);
});
test('manual choice ignores harmless keydown and foreign-form submissions, not current user edits',async()=>{
 const h=await setup({owner:true}),p=h.page;draft(p,'草稿');h.publish(1);await h.tick();
 h.pageHook=async(b,r)=>{if(r.op==='draft_commit'){
  p.doc.emit({type:'keydown',target:p.editor,key:'ArrowLeft'});
  const foreign=p.add(p.doc,'form'),send=p.add(foreign,'button',{type:'submit','aria-label':'Send'});send.click();
  p.edit('继续编辑的草稿');
 }};
 p.userClick(p.choiceButtons()[0]);await flush();assert.deepEqual(h.getResult(),{ok:true});assert.equal(p.clicks,0);
 assert.equal(text(p),'继续编辑的草稿\n'+completionMessage({...event(1),noticeVersion:2}));
});
test('Ignore does not inspect the draft, files, current IME or submission state after its trusted click',async()=>{
 const h=await setup({owner:true}),p=h.page;draft(p,'当前草稿');h.publish(1);await h.tick();
 h.pageHook=async(b,r)=>{if(r.op==='draft_commit'){
  p.button.click();p.edit('下一条草稿');p.doc.emit({type:'compositionstart',target:p.editor});
  p.body.appendChild(p.file);p.file.files=[{}];p.add(p.footer,'span',{role:'progressbar'});
 }};
 p.userClick(p.choiceButtons()[1]);await flush();assert.deepEqual(h.getResult(),{ok:true});assert.equal(text(p),'下一条草稿');
 assert.equal(p.file.files.length,1);assert.equal(p.clicks,1);assert.deepEqual(h.state.automation.consumed,[event(1).work_ref]);
});
test('same-document prior adapter state gets the submission fence before offering a new choice',async()=>{
 const h=await setup({owner:true}),p=h.page,state=p.window.__bridgeSyntheticNoticeV1;
 // Prior page-local adapter state has edit/navigation listeners, but no new
 // submission counter or listeners. No persistent/user storage is migrated.
 delete state.submissions;p.doc.listeners.click=[];p.doc.listeners.submit=[];
 p.doc.listeners.keydown=p.doc.listeners.keydown.slice(0,1);
 draft(p,'保留原草稿');h.publish(1);await h.tick();assert.equal(state.submissions,0);
 h.pageHook=async(b,r)=>{if(r.op==='draft_commit'){p.button.click();p.edit('下一条草稿');}};
 p.userClick(p.choiceButtons()[0]);await flush();assert.equal(h.getResult().ok,false);assert.equal(text(p),'下一条草稿');
 assert.deepEqual(h.state.automation.consumed,[]);assert.equal(p.clicks,1);
});
