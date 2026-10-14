import test from "node:test";
import assert from "node:assert/strict";
import {fixture,harness,CHAT} from "./harness.js";
import {notice} from "../extension/policy.js";
const last=s=>s.events.at(-1);
const BODY="div[data-composer-body]";
const FOOTER="div[data-composer-footer-responsive]";
const SELECTOR='div[contenteditable="true"][role="textbox"][data-composer-markdown]';
const SLOT="__bridgeSyntheticNoticeV1";
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
  assert.equal(last(s).status,"attempted_unknown");
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
  ["duplicate body",p=>p.add(p.doc,"div",{"data-composer-body":""}),"COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS"],
  ["conflicting non-div body",p=>p.add(p.doc,"span",{"data-composer-body":""}),"COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS"],
  ["non-div footer",p=>{p.footer.tagName="SPAN";},"COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS"],
  ["non-div attachment slot",p=>{p.attachments.tagName="SPAN";},"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["nested body",p=>{const b=p.add(p.body,"div",{"data-composer-body":""});b.appendChild(p.footer);},"COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS"],
  ["missing footer",p=>{delete p.footer.attrs["data-composer-footer-responsive"];},"COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS"],
  ["nested footer",p=>p.add(p.footer,"div",{"data-composer-footer-responsive":""}),"COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS"],
  ["hidden body",p=>{p.body.hidden=true;},"COMPOSER_UNKNOWN_OR_AMBIGUOUS"],
  ["missing voice",p=>p.footer.removeChild(p.button),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["duplicate voice",p=>p.add(p.footer,"button",{...p.button.attrs}),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["voice and Send",p=>p.add(p.footer,"button",{type:"submit","aria-label":"Send"}),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["hidden voice",p=>{p.button.hidden=true;},"UNKNOWN_COMPOSER_CONTROL"],
  ["disabled voice",p=>{p.button.disabled=true;},"COMPOSER_CONTROL_DISABLED"],
  ["foreign button",p=>{p.body.appendChild(p.button);},"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["unknown control",p=>p.add(p.footer,"button",{type:"button","aria-label":"Unknown"}),"UNKNOWN_COMPOSER_CONTROL"],
  ["missing add-context",p=>p.footer.removeChild(p.addContext),"AUXILIARY_CONTROL_UNKNOWN_OR_AMBIGUOUS"],
  ["duplicate reasoning",p=>p.add(p.footer,"button",{...p.reasoning.attrs}),"AUXILIARY_CONTROL_UNKNOWN_OR_AMBIGUOUS"],
  ["dictation localization unsupported",p=>{p.dictate.attrs["aria-label"]="听写";},"AUXILIARY_CONTROL_UNKNOWN_OR_AMBIGUOUS"],
  ["voice localization unsupported",p=>{p.button.attrs["aria-label"]="开始语音";},"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
  ["open reasoning",p=>{p.reasoning.attrs["aria-expanded"]="true";},"OPEN_COMPOSER_CONTROL"],
  ["busy dictation",p=>{p.dictate.attrs["aria-busy"]="true";},"BUSY_OR_UPLOAD"],
  ["busy body",p=>{p.body.attrs["aria-busy"]="true";},"BUSY_OR_UPLOAD"],
  ["unknown content",p=>{p.add(p.body,"span").textContent="unknown";},"UNKNOWN_COMPOSER_CONTENT"],
  ["foreign form association",p=>{const f=p.add(p.doc,"form",{id:"foreign"});p.button.attrs.form="foreign";assert.equal(p.button.form,f);},"FORM_OWNER_MISMATCH"],
  ["unresolved form association",p=>{p.button.attrs.form="missing";},"FORM_OWNER_MISMATCH"],
  ["nested form",p=>{const f=p.add(p.body,"form");f.appendChild(p.footer);},"FORM_OWNER_MISMATCH"],
  ["missing attachment slot",p=>p.body.removeChild(p.attachments),"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["visible populated attachment slot",p=>{p.attachments.hidden=false;p.add(p.attachments,"div");},"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["hidden populated attachment slot",p=>p.add(p.attachments,"div"),"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["duplicate attachment slot",p=>p.add(p.body,"div",{"data-composer-attachments":"",hidden:""}),"ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY"],
  ["file selected",p=>{p.body.appendChild(p.file);p.file.files=[{}];},"ATTACHMENT"],
  ["upload progress",p=>p.add(p.body,"div",{role:"progressbar"}),"BUSY_OR_UPLOAD"],
  ["other editable",p=>p.add(p.body,"span",{contenteditable:"true"}),"UNKNOWN_COMPOSER_CONTROL"]
]) test("controls: "+name+" fails closed at Bind without mutation",async()=>{
  const p=fixture();mutate(p);const before=p.editor.textContent;
  const r=await p.op({op:"bind",route:CHAT,generation:"reject"});
  assert.equal(r.ok,false);assert.equal(r.code,code);
  assert.equal(p.clicks,0);assert.equal(p.voiceClicks,0);assert.equal(p.editor.textContent,before);
});

for(const name of ["voice replacement","voice attribute mutation","body","footer","editor","owner","auxiliary","attachment slot"])
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
  "disabled Send","aria-disabled Send","wrong Send label","arbitrary submit","reused leftover voice attribute",
  "foreign Send","new unknown button","body replacement","footer replacement","editor replacement",
  "owner replacement","auxiliary replacement","attachment inserted","late deadline"])
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
    if(name==="wrong Send label")p.button.attrs["aria-label"]="Start Voice";
    if(name==="arbitrary submit")delete p.button.attrs["aria-label"];
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

test("controls: an empty draft with Send is a state mismatch, not a voice fallback",async()=>{
  const p=fixture();p.button.attrs={type:"submit","aria-label":"Send"};
  const r=await p.op({op:"bind",route:CHAT,generation:"mismatch"});
  assert.equal(r.code,"EMPTY_PRIMARY_NOT_VOICE");assert.equal(p.clicks,0);
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
