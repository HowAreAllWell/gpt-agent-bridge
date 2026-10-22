import test from "node:test";
import assert from "node:assert/strict";
import {fixture,harness,CHAT,boundPreparation} from "./harness.js";
import {notice} from "../extension/policy.js";
import {Automation} from "../extension/automation.js";
const last=s=>s.events.at(-1);
const BODY="div[data-composer-body]";
const FOOTER="div[data-composer-footer-responsive]";
const SELECTOR='div[contenteditable="true"][role="textbox"][data-composer-markdown]';
const SLOT="__bridgeSyntheticNoticeV1";
// Candidate Chinese labels, exercised on synthetic DOM; not a live UI receipt.
for(const owner of [false,true])for(const transition of ['replace','reuse'])
test('controls: localized voice to Send preserves ownership and one click '+owner+'/'+transition,async()=>{
  const h=harness({owner,transition});
  h.page.button.attrs['aria-label']='开始语音';
  h.page.onYield=()=>{h.page.button.attrs['aria-label']='发送消息';};
  await h.bind();const s=await h.arm();
  assert.equal(last(s).code,'SEND_CLICK_INVOKED');assert.equal(h.page.clicks,1);
  assert.equal(h.page.button.getAttribute('type'),'submit');
  assert.equal(h.page.button.getAttribute('aria-label'),'发送消息');
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  await assert.rejects(h.worker.run('retry'),/NOT_SAFE_TO_RETRY/);
});
for(const [type,label] of [['button','Start Voice'],['button','开始语音'],['submit','Send'],['submit','发送消息']])
test('controls: localized mixed or duplicate primary rejects '+label,async()=>{
  const p=fixture();p.button.attrs['aria-label']='开始语音';
  p.add(p.footer,'button',{type,'aria-label':label});
  const r=await boundPreparation(p,'localized-duplicate');
  assert.equal(r.code,'PRIMARY_UNKNOWN_OR_AMBIGUOUS');
  assert.equal(p.editor.textContent,'');assert.equal(p.clicks,0);
});
for(const label of ['Send','发送消息'])
test('controls: localized post-prefill duplicate Send leaves unknown '+label,async()=>{
  const h=harness();h.page.button.attrs['aria-label']='开始语音';
  h.page.onYield=()=>{
    h.page.button.attrs['aria-label']='发送消息';
    h.page.add(h.page.footer,'button',{type:'submit','aria-label':label});
  };
  await h.bind();const s=await h.arm();
  assert.equal(last(s).status,'attempted_unknown');assert.equal(h.page.clicks,0);
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  await assert.rejects(h.worker.run('retry'),/NOT_SAFE_TO_RETRY/);
});
// The user-confirmed target is a unique native submitter, not a translated label.
for(const voice of ['Start Voice','开始语音'])for(const label of ['Send','发送消息','发送',undefined])
for(const owner of [false,true])for(const transition of ['replace','reuse'])
test('controls: native Send label independent '+voice+'/'+label+'/'+owner+'/'+transition,async()=>{
  const h=harness({owner,transition});h.page.button.attrs['aria-label']=voice;
  h.page.onYield=()=>{if(label===undefined)delete h.page.button.attrs['aria-label'];else h.page.button.attrs['aria-label']=label;};
  await h.bind();const s=await h.arm();
  assert.equal(last(s).code,'SEND_CLICK_INVOKED');assert.equal(h.page.clicks,1);
  assert.equal(h.page.button.getAttribute('type'),'submit');assert.equal(h.page.editor.textContent,notice(last(s).id));
  await assert.rejects(h.worker.run('retry'),/NOT_SAFE_TO_RETRY/);
});
for(const phase of ['before','after'])for(const kind of ['default button','submit button','submit input','image input'])
test('controls: native associated submitter outside composer blocks '+phase+'/'+kind,async()=>{
 const h=harness({owner:true}),p=h.page;p.owner.attrs.id='synthetic-owner';
 const add=()=>{const button=kind.includes('button');const attrs={form:'synthetic-owner'};
  if(kind!=='default button')attrs.type=kind.startsWith('image')?'image':'submit';
  const extra=p.add(p.doc,button?'button':'input',attrs);assert.equal(extra.form,p.owner);return extra;};
 if(phase==='before')add();else p.onYield=add;
 await h.bind();const s=await h.arm();assert.equal(p.clicks,0);
 assert.equal(last(s).status,phase==='before'?'paused':'attempted_unknown');
 assert.equal(p.editor.textContent,phase==='before'?'':notice(last(s).id));
 if(phase==='after')await assert.rejects(h.worker.run('retry'),/NOT_SAFE_TO_RETRY/);
});
for(const place of ['footer','inside editor','form outside body'])
test('controls: native extra unlabeled submitter blocks after prefill '+place,async()=>{
 const h=harness({owner:true}),p=h.page;
 p.onYield=()=>p.add(place==='footer'?p.footer:place==='inside editor'?p.editor:p.owner,'button',{type:'submit'});
 await h.bind();const s=await h.arm();assert.equal(last(s).status,'attempted_unknown');assert.equal(p.clicks,0);
 assert.equal(p.editor.textContent,notice(last(s).id));await assert.rejects(h.worker.run('retry'),/NOT_SAFE_TO_RETRY/);
});
for(const kind of ['hidden','unrelated form'])
test('controls: native irrelevant submitter is not a duplicate '+kind,async()=>{
 const h=harness({owner:true}),p=h.page;p.owner.attrs.id='synthetic-owner';
 p.onYield=()=>{const attrs={type:'submit'};
  if(kind==='hidden'){attrs.form='synthetic-owner';attrs.hidden='';}
  else{p.add(p.doc,'form',{id:'unrelated'});attrs.form='unrelated';}
  p.add(p.doc,'button',attrs);
 };
 await h.bind();const s=await h.arm();assert.equal(last(s).code,'SEND_CLICK_INVOKED');assert.equal(p.clicks,1);
});
for(const label of ['开始语音','发送消息'])
test('controls: localized primary never sends an existing user draft '+label,async()=>{
  const h=harness();h.page.button.attrs={type:label==='开始语音'?'button':'submit','aria-label':label};
  h.page.editor.textContent='synthetic user draft';await h.bind();const s=await h.arm();
  assert.equal(last(s).code,'DRAFT_PRESENT');assert.equal(last(s).status,'paused');
  assert.equal(h.page.editor.textContent,'synthetic user draft');assert.equal(h.page.clicks,0);
});
test('minimum contract: harmless toolbar, transcript and ownership-preserving layout changes still send only the exact Send',async()=>{
  for(const mutate of [
    p=>p.reasoning.remove(),p=>{p.dictate.attrs['aria-label']='听写';p.dictate.disabled=true;},
    p=>p.add(p.footer,'button',{type:'button','aria-label':'Formatting'}),
    p=>p.add(p.body,'button',{type:'button','aria-label':'展开','data-composer-expand-toggle':'','aria-expanded':'false'}),
    p=>{p.add(p.doc,'iframe');p.add(p.conversation,'div',{role:'alert'}).textContent='copied';},
    p=>p.add(p.body,'span').textContent='Press Enter to send',
    p=>p.add(p.body,'div',{...p.editor.attrs,hidden:''}),
    p=>p.body.appendChild(p.rich),
    p=>{p.button.attrs['aria-label']='开始语音';},
    p=>p.add(p.addContext,'img',{width:'16',height:'16'}),
    p=>p.add(p.doc,'div',{'data-composer-body':''}),
    p=>{p.footer.tagName='SPAN';},
    p=>p.add(p.footer,'button',{...p.reasoning.attrs}),
    p=>p.addContext.remove()
  ]) {
    const h=harness();mutate(h.page);await h.bind();const s=await h.arm();
    assert.equal(last(s).code,'SEND_CLICK_INVOKED');assert.equal(h.page.clicks,1);assert.equal(h.page.voiceClicks,0);
  }
});
test('controls: mixed Voice and Send leaves real Work pending before intent and sends once after ambiguity clears',async()=>{
  const h=harness(),epoch='a'.repeat(32),event={work_ref:'work-0000000000000001',project_ref:'gpt-agent-bridge',
    sequence:1,ready_at:5,result_class:'result_ready',report_status:'readable',report_sha256:'b'.repeat(64)};
  let published=false,sends=0,inputs=0,intentWrites=0;
  h.io.exactTabs=async route=>route===CHAT?[{id:1,incognito:false}]:[];
  h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
  h.io.feed=async q=>({epoch,events:published&&(q?.check===event.work_ref || !q?.check && (q?.after||0)<1)?[event]:[],
    cursor:published?1:0,latest:published?1:0});
  h.writeHook=s=>{if(s.automation?.consumed?.includes(event.work_ref) || s.automation?.deliveries?.some(e=>e.intentAt!==undefined))intentWrites++;};
  h.worker=new Automation(h.io);await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;
  const voice=h.page.button,send=h.page.add(h.page.footer,'button',{type:'submit','aria-label':'Send'});
  send.onClick=()=>sends++;h.page.editor.addEventListener('input',()=>inputs++);published=true;
  await h.worker.run('tick');
  assert.deepEqual({pending:h.state.automation.deliveries.map(e=>({id:e.work_ref,code:e.code,intentAt:e.intentAt})),
    consumed:h.state.automation.consumed,text:h.page.editor.textContent,inputs,sends:h.page.clicks+sends,intentWrites},
    {pending:[{id:event.work_ref,code:'PRIMARY_UNKNOWN_OR_AMBIGUOUS',intentAt:undefined}],consumed:[],text:'',inputs:0,sends:0,intentWrites:0});
  assert(!h.calls.some(c=>c.op==='commit'));
  h.worker=new Automation(h.io);await h.worker.run('tick');assert.equal(intentWrites,0);assert.equal(inputs,0);
  send.remove();await h.worker.run('tick');
  assert.equal(sends,0);assert.equal(h.page.clicks,1);assert.equal(inputs,1);
  assert.deepEqual(h.state.automation.deliveries,[]);assert.deepEqual(h.state.automation.consumed,[event.work_ref]);
  h.worker=new Automation(h.io);await h.worker.run('tick');assert.equal(h.page.clicks,1);
});
test('controls: hidden primary templates do not make the one visible Voice ambiguous',async()=>{
  const h=harness();
  h.page.add(h.page.footer,'button',{type:'button','aria-label':'Start Voice',hidden:''});
  h.page.add(h.page.footer,'button',{type:'submit','aria-label':'Send',hidden:''});
  await h.bind();const s=await h.arm();assert.equal(last(s).code,'SEND_CLICK_INVOKED');assert.equal(h.page.clicks,1);
});
function replacement(p,node,attrs={...node.attrs}) {
  const next=p.add(p.doc,node.tagName.toLowerCase(),attrs);
  while(node.childNodes.length)next.appendChild(node.childNodes[0]);
  node.parentNode.replaceChild(next,node);
  return next;
}

test("controls: observed empty voice body binds/inspects without a form, fill, click or event",async()=>{
  const h=harness();let inputs=0;
  h.page.doc.addEventListener("input",()=>inputs++);
  assert.equal(h.page.doc.querySelectorAll("form").length,0); // Synthetic surrounding document.
  assert.equal(h.page.editor.closest(BODY),h.page.body);
  assert.equal(h.page.editor.closest(FOOTER),h.page.footer);
  assert.equal(h.page.button.getAttribute("aria-label"),"Start Voice");
  await h.bind();
  const s=await h.worker.run("inspect");
  assert.equal(s.inspection,"READY_FOR_EXPLICIT_ARM");
  assert.equal(s.events.length,0);assert.equal(inputs,0);
  assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
});

for(const owner of [false,true])for(const transition of ["replace","reuse"])
test("controls: synthetic "+transition+" voice to Send with outer form "+owner+" clicks only Send once",async()=>{
  const h=harness({owner,transition});const voice=h.page.button;await h.bind();
  assert.equal(h.page.button.form,h.page.owner);
  const s=await h.arm();
  assert.equal(h.page.button===voice,transition==="reuse");
  assert.equal(h.page.button.getAttribute("type"),"submit");
  assert.equal(h.page.button.getAttribute("aria-label"),"Send");
  assert.equal(h.page.clicks,1);assert.equal(h.page.voiceClicks,0);
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  assert.equal(last(s).status,"handled");
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
});

test("controls: observed nonempty Send snapshot can bind but never bypasses draft protection",async()=>{
  const h=harness();h.page.editor.childNodes[0].textContent="1";h.page.renderSend();
  await h.bind();assert.equal((await h.worker.run("inspect")).inspection,"DRAFT_PRESENT");
  const s=await h.arm();
  assert.equal(last(s).status,"paused");assert.equal(last(s).code,"DRAFT_PRESENT");
  assert.equal(h.page.editor.textContent,"1");assert.equal(h.page.clicks,0);
});

test("controls: reasoning effort and generated identifiers are not selector requirements",async()=>{
  const h=harness();
  h.page.reasoning.attrs.id="different-generated-id";
  h.page.reasoning.attrs["data-selected-reasoning-effort"]="different";
  h.page.reasoning.textContent="Another effort label";
  await h.bind();assert.equal((await h.worker.run("inspect")).inspection,"READY_FOR_EXPLICIT_ARM");
  assert.equal(h.page.clicks,0);
});

for(const [name,mutate,code] of [
  ["missing body",p=>{delete p.body.attrs["data-composer-body"];},"COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS"],
  ["non-div attachment slot",p=>{p.attachments.tagName="SPAN";},"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["nested body",p=>{const b=p.add(p.body,"div",{"data-composer-body":""});b.appendChild(p.footer);},"COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS"],
  ["missing footer",p=>{delete p.footer.attrs["data-composer-footer-responsive"];},"COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS"],
  ["nested footer",p=>p.add(p.footer,"div",{"data-composer-footer-responsive":""}),"COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS"],
  ["hidden body",p=>{p.body.hidden=true;},"COMPOSER_UNKNOWN_OR_AMBIGUOUS"],
  ["missing voice",p=>p.footer.removeChild(p.button),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["duplicate voice",p=>p.add(p.footer,"button",{...p.button.attrs}),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["mixed Voice and Send",p=>p.add(p.footer,'button',{type:'submit','aria-label':'Send'}),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["two real Sends across footer/body",p=>{p.add(p.footer,'button',{type:'submit','aria-label':'Send'});p.add(p.body,'button',{type:'submit','aria-label':'Send'});},"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["hidden voice",p=>{p.button.hidden=true;},"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["disabled voice",p=>{p.button.disabled=true;},"COMPOSER_CONTROL_DISABLED"],
  ["foreign button",p=>{p.body.appendChild(p.button);},"FORM_OWNER_MISMATCH"],
  ["unsupported voice label",p=>{p.button.attrs["aria-label"]="开启语音";},"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["open reasoning",p=>{p.reasoning.attrs["aria-expanded"]="true";},"OPEN_COMPOSER_CONTROL"],
  ["busy dictation",p=>{p.dictate.attrs["aria-busy"]="true";},"COMPOSER_NOT_READY"],
  ["busy body",p=>{p.body.attrs["aria-busy"]="true";},"COMPOSER_NOT_READY"],
  ["foreign form association",p=>{const f=p.add(p.doc,"form",{id:"foreign"});p.button.attrs.form="foreign";assert.equal(p.button.form,f);},"FORM_OWNER_MISMATCH"],
  ["unresolved form association",p=>{p.button.attrs.form="missing";},"FORM_OWNER_MISMATCH"],
  ["nested form",p=>{const f=p.add(p.body,"form");f.appendChild(p.footer);},"FORM_OWNER_MISMATCH"],
  ["missing attachment slot",p=>p.body.removeChild(p.attachments),"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["visible populated attachment slot",p=>{p.attachments.hidden=false;p.add(p.attachments,"div");},"DRAFT_PRESENT"],
  ["hidden populated attachment slot",p=>p.add(p.attachments,"div"),"DRAFT_PRESENT"],
  ["duplicate attachment slot",p=>p.add(p.body,"div",{"data-composer-attachments":"",hidden:""}),"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["file selected",p=>{p.body.appendChild(p.file);p.file.files=[{}];},"DRAFT_PRESENT"],
  ["upload progress",p=>p.add(p.body,"div",{role:"progressbar"}),"COMPOSER_NOT_READY"],
  ["composer error",p=>p.add(p.body,'div',{role:'alert'}),"VISIBLE_FRAME_OR_ALERT"],
  ["composer iframe",p=>p.add(p.body,'iframe'),"VISIBLE_FRAME_OR_ALERT"],
  ["blocking dialog",p=>p.add(p.doc,'div',{role:'dialog'}),"DIALOG_OR_CHALLENGE"],
  ["other editable",p=>p.add(p.body,"span",{contenteditable:"true"}),"UNKNOWN_COMPOSER_CONTROL"]
]) test("controls: "+name+" binds identity but fails closed at Prepare without mutation",async()=>{
  const p=fixture();mutate(p);const before=p.editor.textContent;
  const r=await boundPreparation(p,"reject");
  assert.equal(r.ok,false);assert.equal(r.code,code);
  assert.equal(p.clicks,0);assert.equal(p.voiceClicks,0);assert.equal(p.editor.textContent,before);
});

for(const name of ["voice replacement","voice attribute mutation","body","footer","editor","owner","attachment slot"])
test("controls: "+name+" changes after prepare block before insertion",async()=>{
  const h=harness();await h.bind();
  h.pageHook=(_,r)=>{
    if(r.op!=="commit")return;
    const p=h.page;
    if(name==="voice replacement")replacement(p,p.button);
    if(name==="voice attribute mutation")p.button.attrs["aria-label"]="Other";
    if(name==="body")replacement(p,p.body);
    if(name==="footer")replacement(p,p.footer);
    if(name==="editor")replacement(p,p.editor);
    if(name==="owner"){const f=p.add(p.doc,"form");f.appendChild(p.body);}
    if(name==="auxiliary")replacement(p,p.reasoning);
    if(name==="attachment slot")replacement(p,p.attachments);
  };
  const s=await h.arm();
  assert.equal(last(s).status,"paused");
  assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
});

for(const name of ["no render","replacement remains voice","reuse remains voice","multiple Send","missing Send",
  "disabled Send","aria-disabled Send","hidden Send",
  "foreign Send","body replacement","footer replacement","editor replacement",
  "owner replacement","attachment inserted","late deadline"])
test("controls: "+name+" after prefill preserves unknown and never clicks",async()=>{
  const h=harness();await h.bind();
  if(name==="no render" || name==="replacement remains voice" || name==="reuse remains voice")h.page.transition="none";
  h.page.onYield=()=>{
    const p=h.page;
    if(name==="replacement remains voice")replacement(p,p.button);
    if(name==="reuse remains voice")p.button.attrs["data-state"]="open";
    if(name==="multiple Send")p.add(p.footer,"button",{...p.button.attrs});
    if(name==="missing Send")p.footer.removeChild(p.button);
    if(name==="disabled Send")p.button.disabled=true;
    if(name==="aria-disabled Send")p.button.attrs["aria-disabled"]="true";
    if(name==="hidden Send")p.button.hidden=true;
    if(name==="reused leftover voice attribute")p.button.attrs["data-state"]="closed";
    if(name==="foreign Send")p.body.appendChild(p.button);
    if(name==="new unknown button")p.add(p.footer,"button",{type:"button","aria-label":"Other"});
    if(name==="body replacement")replacement(p,p.body);
    if(name==="footer replacement")replacement(p,p.footer);
    if(name==="editor replacement")replacement(p,p.editor);
    if(name==="owner replacement"){const f=p.add(p.doc,"form");f.appendChild(p.body);}
    if(name==="auxiliary replacement")replacement(p,p.reasoning);
    if(name==="attachment inserted")p.add(p.attachments,"div");
    if(name==="late deadline")p.clock.now+=4000;
  };
  const s=await h.arm(), text=h.page.doc.querySelectorAll(SELECTOR)[0].textContent;
  assert.equal(last(s).status,"attempted_unknown");
  assert.equal(text,notice(last(s).id));
  assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await h.newWorker().run("alarm");assert.equal(h.page.clicks,0);
  assert.equal(h.page.doc.querySelectorAll(SELECTOR)[0].textContent,text);
});

for(const kind of ["replace Send","mutate Send","expire lease","edit revision","change form owner"])
test("controls: final synchronous Send revalidation catches "+kind,async()=>{
  const h=harness();await h.bind();
  h.page.onYield=()=>{
    const p=h.page;let changed=false;
    Object.defineProperty(p.button,"disabled",{get(){
      if(!changed){
        changed=true;
        if(kind==="replace Send")replacement(p,p.button);
        if(kind==="mutate Send")p.button.attrs.type="button";
        if(kind==="expire lease")p.clock.now+=4000;
        if(kind==="edit revision")p.window[SLOT].revision++;
        if(kind==="change form owner"){const f=p.add(p.doc,"form");f.appendChild(p.body);}
      }
      return false;
    }});
  };
  const s=await h.arm();
  assert.equal(last(s).status,"attempted_unknown");assert.equal(h.page.clicks,0);
  assert.equal(h.page.voiceClicks,0);assert.equal(h.page.editor.textContent,notice(last(s).id));
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
});

test("controls: an empty draft with Send alone cannot prove idle Voice",async()=>{
  const p=fixture();p.button.attrs={type:"submit","aria-label":"Send"};
  const r=await boundPreparation(p,"mismatch");
  assert.equal(r.ok,false);assert.equal(r.code,'EMPTY_PRIMARY_NOT_VOICE');assert.equal(p.clicks,0);
});

for(const phase of ["before","after"])
test("controls: existing outer form identity replacement "+phase+" insertion rejects",async()=>{
  const h=harness({owner:true});await h.bind();const original=h.page.owner;
  const move=()=>{const next=h.page.add(h.page.doc,"form");next.appendChild(h.page.body);assert.notEqual(h.page.button.form,original);};
  if(phase==="before")h.pageHook=(_,r)=>{if(r.op==="commit")move();};
  else h.page.onYield=move;
  const s=await h.arm();
  assert.equal(last(s).status,phase==="before"?"paused":"attempted_unknown");
  assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
  assert.equal(h.page.editor.textContent,phase==="before"?"":notice(last(s).id));
});

test("controls: deadline expiring during the last prefill guard causes no insertion",async()=>{
  const h=harness();await h.bind();
  h.pageHook=(_,r)=>{
    if(r.op==="commit")Object.defineProperty(h.page.button,"disabled",{get(){h.page.clock.now+=4000;return false;}});
  };
  const s=await h.arm();
  assert.equal(last(s).status,"paused");assert.equal(last(s).code,"STALE_PAGE_OBSERVATION");
  assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);
});

test('controls: auxiliary rerender and new non-submit buttons during prefill do not change the Send owner',async()=>{
 const h=harness();await h.bind();h.page.onYield=()=>{
  replacement(h.page,h.page.reasoning);h.page.add(h.page.footer,'button',{type:'button'});
  h.page.button.attrs['data-state']='closed';
 };
 const s=await h.arm();assert.equal(last(s).code,'SEND_CLICK_INVOKED');assert.equal(h.page.clicks,1);
});
test('controls: hidden empty attachment slot remains owned during a Stop-triggered safe withdrawal',async()=>{
 for(const sibling of [false,true]) {
 const h=harness();await h.bind();let stopped=false,result;const page=h.io.page;
  if(sibling)h.page.body.appendChild(h.page.rich);
 h.io.page=async(b,r)=>{const response=await page(b,r);if(r.op==='commit')result=response;return response;};
 h.page.onYield=()=>{if(!stopped){stopped=true;h.page.add(h.page.footer,'button',{type:'button','aria-label':'Stop'});}};
 await h.arm();assert.equal(result.stage,'rolled_back_before_click');assert.equal(h.page.editor.textContent,'');
 assert.equal(h.page.attachments.hidden,true);assert.equal(h.page.clicks,0);
 }
});
for(const when of ['before invocation','during prefill'])test('revocation contract: explicit dismissal fences a prepared Send '+when,async()=>{
 const p=fixture(),binding=await p.op({op:'bind',route:CHAT,generation:'revocation'});p.clock.now+=2100;
 const q={route:CHAT,generation:'revocation',documentToken:binding.documentToken};
 const ready=await p.op({...q,op:'prepare'});assert.equal(ready.ok,true);
 if(when==='before invocation')await p.op({...q,op:'draft_dismiss'});
 else p.onYield=()=>{p.op({...q,op:'draft_dismiss'});};
 const result=await p.op({...q,op:'commit',lease:ready.lease,eventId:'work-0000000000000001',reportSha:'b'.repeat(64),noticeVersion:2});
 assert.equal(p.clicks,0);assert.equal(result.stage,when==='before invocation'?'blocked_before_mutation':'after_mutation');
 assert.equal(p.editor.textContent,'before invocation'===when?'':'Agent 已结束：work-0000000000000001。');
});
