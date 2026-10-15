import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {createHash} from "node:crypto";
import {fixture,harness,CHAT,boundPreparation} from "./harness.js";
import {notice} from "../extension/policy.js";

const last=s=>s.events.at(-1);
const SLOT="__bridgeSyntheticNoticeV1";
const attrs={type:"button","aria-label":"Expand","data-composer-expand-toggle":""};
// Exact accepted installed adapter: frozen v2 plus the accepted empty-slot edit.
// Hash the entire actual adapter, then execute it through the serialized VM path.
const historical=fs.readFileSync(new URL("./fixtures/legacy-controls/adapter.js",import.meta.url),"utf8")
  .replace('slots[0].getAttribute("hidden") === null ||\n        visible(slots[0]) || slots[0].childNodes.length)',
    'slots[0].childNodes.length)');
assert.equal(createHash("sha256").update(historical).digest("hex"),
  "ec87797d05d23e6a48fd4a69b8736b35422ae9ad0c868dcda7c638ac91550f27");
const oldOperation=historical.replace("export async function","async function");

// Observed Expand ancestry: BUTTON -> SPAN -> DIV -> composer body, outside footer.
// Surrounding form/no-form document, SVG/title content and every transition/timing
// below are synthetic. Native button.form was NOT measured in the live receipt.
function expand(p) {
  const node=p.add(p.add(p.add(p.body,"div"),"span"),"button",{...attrs});
  p.add(p.add(node,"svg"),"title").textContent="synthetic layout artwork";
  node.onClick=()=>assert.fail("Expand must never be clicked");
  return node;
}
const tree=n=>({type:n.nodeType,tag:n.tagName,attrs:n.attrs?{...n.attrs}:undefined,
  value:n.nodeValue,children:(n.childNodes || []).map(tree)});
async function stopped(h,s) {
  assert.equal(last(s).status,"attempted_unknown");assert.equal(last(s).outcome,"preclick_stop");
  assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  const before=h.state,text=h.page.editor.textContent;
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await assert.rejects(h.worker.run("arm",{delayMs:0}),/ACTIVE_OR_UNCERTAIN_EVENT_EXISTS/);
  await h.newWorker().run("alarm");
  assert.deepEqual(h.state,before);assert.equal(h.page.editor.textContent,text);assert.equal(h.page.clicks,0);
}

test("Expand: exact installed adapter rejects observed nonempty five-button shape",async()=>{
  const p=fixture(oldOperation);p.attachments.hidden=false;p.editor.textContent="synthetic existing draft";p.renderSend();
  const e=expand(p);assert.equal(p.body.querySelectorAll("button").length,5);
  assert.equal(e.closest("div[data-composer-footer-responsive]"),null);
  const before=tree(p.doc),r=await p.op({op:"bind",route:CHAT,generation:"old"});
  assert.equal(r.code,"UNKNOWN_COMPOSER_CONTROL");assert.deepEqual(tree(p.doc),before);assert.equal(p.clicks,0);
});

test("Expand: exact installed adapter stops after synthetic appearance at prefill; current Controller retains evidence",async()=>{
  const h=harness(),p=fixture(oldOperation);h.pages.set(1,p);
  await h.worker.run("bind");p.clock.now+=2100;p.onYield=()=>expand(p);
  const s=await h.arm();assert.equal(last(s).code,"UNKNOWN_COMPOSER_CONTROL");
  assert.equal(last(s).outcome,"preclick_stop");assert.equal(p.clicks,0);
  assert.equal(p.editor.textContent,notice(last(s).id));
  const before=h.state;
  // Loading the new adapter does not close or replay an old stopped event.
  h.pages.set(1,h.page);h.page.editor.textContent=p.editor.textContent;h.page.renderSend();expand(h.page);
  await h.newWorker().run("status");assert.deepEqual(h.state,before);
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await assert.rejects(h.worker.run("arm",{delayMs:0}),/ACTIVE_OR_UNCERTAIN_EVENT_EXISTS/);
  assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,p.editor.textContent);
});

for(const owner of [false,true])for(const present of [false,true])
test(`Expand: Bind/Inspect with owner=${owner}, optional=${present} neither fill nor click`,async()=>{
  const h=harness({owner});if(present)expand(h.page);h.page.attachments.hidden=false;
  const before=tree(h.page.doc);let inputs=0;h.page.doc.addEventListener("input",()=>inputs++);
  await h.bind();const s=await h.worker.run("inspect");
  assert.equal(s.inspection,"READY_FOR_EXPLICIT_ARM");assert.equal(s.events.length,0);
  assert.deepEqual(tree(h.page.doc),before);assert.equal(inputs,0);
  assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
});

test("Expand: current observed nonempty shape binds but existing draft still blocks Inspect/Arm",async()=>{
  const h=harness();expand(h.page);h.page.editor.textContent="synthetic existing draft";h.page.renderSend();
  await h.bind();assert.equal((await h.worker.run("inspect")).inspection,"DRAFT_PRESENT");
  assert.equal(last(await h.arm()).code,"DRAFT_PRESENT");assert.equal(h.page.clicks,0);
  assert.equal(h.page.editor.textContent,"synthetic existing draft");
});

for(const owner of [false,true])for(const transition of ["replace","reuse"])
for(const mode of ["absent","appears after prefill","present throughout","replaced layout node"])
test(`Expand: ${mode}, Voice->Send ${transition}, synthetic owner=${owner} clicks only Send once`,async()=>{
  const h=harness({owner,transition}),voice=h.page.button;
  const initial=mode==="present throughout" || mode==="replaced layout node" ? expand(h.page) : null;
  await h.bind();h.page.onYield=()=>{
    h.page.body.attrs["data-composer-layout"]="multiline";h.page.attachments.hidden=false;
    if(mode==="appears after prefill")expand(h.page);
    if(mode==="replaced layout node"){initial.parentNode.removeChild(initial);expand(h.page);}
  };
  const s=await h.arm();
  assert.equal(h.page.button===voice,transition==="reuse");
  assert.equal(h.page.button.getAttribute("aria-label"),"Send");assert.equal(h.page.button.form,h.page.owner);
  assert.equal(h.page.clicks,1);assert.equal(h.page.voiceClicks,0);
  assert.equal(last(s).code,"CLICK_ATTEMPTED_RECEIPT_UNKNOWN");assert.equal(last(s).outcome,"clicked");
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  const before=h.state;await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await h.newWorker().run("alarm");assert.deepEqual(h.state,before);assert.equal(h.page.clicks,1);
});

const cases=[
  ["duplicate marker",(p,e)=>expand(p)],
  ["marker on non-button",(p,e)=>{e.tagName="SPAN";}],
  ["nonempty marker",(p,e)=>{e.attrs["data-composer-expand-toggle"]="true";}],
  ["missing marker",(p,e)=>{delete e.attrs["data-composer-expand-toggle"];}],
  ["submit type",(p,e)=>{e.attrs.type="submit";}],
  ["missing type",(p,e)=>{delete e.attrs.type;}],
  ["Collapse",(p,e)=>{e.attrs["aria-label"]="Collapse";}],
  ["translated label",(p,e)=>{e.attrs["aria-label"]="展开";}],
  ...["role","aria-expanded","aria-haspopup","aria-disabled","aria-busy","data-state",
    "data-composer-navigation-target","data-codex-intelligence-trigger"].map(name=>[
      "unexpected "+name,(p,e)=>{e.attrs[name]="false";}]),
  ["hidden",(p,e)=>{e.hidden=true;}],
  ["disabled",(p,e)=>{e.disabled=true;}],
  ["inside footer",(p,e)=>p.footer.appendChild(e)],
  ["inside editor",(p,e)=>p.editor.appendChild(e)],
  ["inside attachment slot",(p,e)=>p.attachments.appendChild(e)],
  ["wraps footer",(p,e)=>e.appendChild(p.footer)],
  ["wraps attachment slot",(p,e)=>e.appendChild(p.attachments)],
  ["marker on body",(p,e)=>{p.body.attrs["data-composer-expand-toggle"]="";}],
  ["functional collision",(p,e)=>{e.parentNode.removeChild(e);p.dictate.attrs["data-composer-expand-toggle"]="";}],
  ["primary collision",(p,e)=>{e.parentNode.removeChild(e);p.button.attrs["data-composer-expand-toggle"]="";}],
  ["unknown sixth button",(p,e)=>p.add(p.body,"button",{type:"button"})],
  ["unmarked fifth button",(p,e)=>{e.parentNode.removeChild(e);p.add(p.body,"button",{type:"button","aria-label":"Expand"});}],
  ["nested button",(p,e)=>p.add(e,"button",{type:"button"})],
  ["foreign native form owner",(p,e)=>{p.add(p.doc,"form",{id:"foreign"});e.attrs.form="foreign";}],
  ["unresolved native form owner",(p,e)=>{e.attrs.form="absent";}],
  ["nested form",(p,e)=>p.add(p.body,"form").appendChild(e)],
  ["unknown text outside layout",(p,e)=>{p.add(p.body,"span").textContent="unrecognized content";}],
  ["selected file inside layout",(p,e)=>{e.appendChild(p.file);p.file.files=[{}];}],
  ["visible file inside layout",(p,e)=>{e.appendChild(p.file);p.file.hidden=false;}],
  ...["input","textarea","select"].map(tag=>[tag+" inside layout",(p,e)=>p.add(e,tag)]),
  ["link inside layout",(p,e)=>p.add(e,"a",{href:"synthetic"})],
  ["editable inside layout",(p,e)=>p.add(e,"span",{contenteditable:"true"})],
  ["role button inside layout",(p,e)=>p.add(e,"span",{role:"button"})],
  ...["img","video","audio","canvas"].map(tag=>[tag+" inside layout",(p,e)=>p.add(e,tag)]),
  ["upload inside layout",(p,e)=>p.add(e,"span",{role:"progressbar"})],
  ["missing primary",(p,e)=>p.footer.removeChild(p.button)],
  ["duplicate primary",(p,e)=>p.add(p.footer,"button",{...p.button.attrs})],
  ["disabled primary",(p,e)=>{p.button.disabled=true;}],
  ["primary outside footer",(p,e)=>p.body.appendChild(p.button)],
  ["missing auxiliary",(p,e)=>p.footer.removeChild(p.dictate)],
  ["duplicate auxiliary",(p,e)=>p.add(p.footer,"button",{...p.dictate.attrs})],
  ["auxiliary outside footer",(p,e)=>p.body.appendChild(p.dictate)],
  ["hidden auxiliary",(p,e)=>{p.dictate.hidden=true;}],
  ["functional collision without marker",(p,e)=>{
    p.footer.removeChild(p.dictate);p.addContext.attrs["aria-label"]="Dictate";p.addContext.attrs["aria-busy"]="false";
  }]
];
for(const [name,mutate] of cases)
test("Expand: "+name+" rejects at Prepare and after prefill without any click",async()=>{
  const p=fixture();mutate(p,expand(p));const before=tree(p.doc);
  const r=await boundPreparation(p,"reject");
  assert.equal(r.ok,false);assert.deepEqual(tree(p.doc),before);assert.equal(p.clicks,0);
  const h=harness();await h.bind();h.page.onYield=()=>mutate(h.page,expand(h.page));
  const s=await h.arm();assert.notEqual(last(s).code,"CLICK_ATTEMPTED_RECEIPT_UNKNOWN");
  // A deliberately inserted node in editor is retained, never cleared by the adapter.
  if(name==="inside editor"){
    assert.equal(last(s).status,"attempted_unknown");assert.equal(last(s).outcome,"preclick_stop");
    assert.equal(h.page.clicks,0);assert.ok(h.page.editor.textContent.startsWith(notice(last(s).id)));
    await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  }else await stopped(h,s);
});

for(const owner of [false,true])test("Expand: overridden native owner mismatch rejects with closest form unchanged, owner="+owner,async()=>{
  const p=fixture(undefined,{owner}),e=expand(p);
  assert.equal(e.closest("form"),p.owner);
  Object.defineProperty(e,"form",{get:()=>p.add(p.doc,"form")});
  const r=await boundPreparation(p,"native-owner");
  assert.equal(r.code,"FORM_OWNER_MISMATCH");assert.equal(p.clicks,0);
});

for(const kind of ["body","footer","editor","slot","owner","revision","route","deadline","rebind"])
test("Expand: existing "+kind+" interference still stops the post-prefill attempt",async()=>{
  const h=harness();await h.bind();let rebound;
  h.page.onYield=()=>{
    const p=h.page;expand(p);
    if(["body","footer","editor","slot"].includes(kind)){
      const node=kind==="slot"?p.attachments:p[kind];
      const next=p.add(p.doc,node.tagName.toLowerCase(),{...node.attrs});
      while(node.childNodes.length)next.appendChild(node.childNodes[0]);node.parentNode.replaceChild(next,node);
    }
    if(kind==="owner")p.add(p.doc,"form").appendChild(p.body);
    if(kind==="revision")p.window[SLOT].revision++;
    if(kind==="route")p.navigate(CHAT+"?changed=1");
    if(kind==="deadline")p.clock.now+=4000;
    if(kind==="rebind")rebound=p.op({op:"bind",route:CHAT,generation:"new-generation"});
  };
  const s=await h.arm();if(rebound)assert.equal((await rebound).ok,true);
  assert.equal(last(s).status,"attempted_unknown");assert.equal(last(s).outcome,"preclick_stop");assert.equal(h.page.clicks,0);
  const editor=h.page.doc.querySelectorAll('[data-composer-markdown]')[0];
  assert.equal(editor.textContent,notice(last(s).id));await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
});

test("Expand: final synchronous guard rechecks layout after post-render observation",async()=>{
  const h=harness();await h.bind();h.page.onYield=()=>{
    const e=expand(h.page);let once=false;
    Object.defineProperty(h.page.button,"disabled",{get(){if(!once){once=true;e.attrs["aria-label"]="Collapse";}return false;}});
  };
  const s=await h.arm();assert.equal(last(s).code,"UNKNOWN_COMPOSER_CONTROL");await stopped(h,s);
});

test("Expand: captured Voice identity still cannot change between prepare and insertion",async()=>{
  const h=harness();expand(h.page);await h.bind();
  h.pageHook=(_,r)=>{if(r.op==="commit"){
    const p=h.page,next=p.add(p.doc,"button",{...p.button.attrs});p.footer.replaceChild(next,p.button);
  }};
  const s=await h.arm();assert.equal(last(s).code,"COMPOSER_REPLACED");assert.equal(last(s).status,"paused");
  assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);
});

test("Expand: malformed layout appearing between prepare and insertion stops before fill",async()=>{
  const h=harness();await h.bind();h.pageHook=(_,r)=>{
    if(r.op==="commit")expand(h.page).attrs["aria-expanded"]="true";
  };
  const s=await h.arm();assert.equal(last(s).status,"paused");
  assert.equal(last(s).code,"OPEN_COMPOSER_CONTROL");
  assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);
});

for(const kind of ["child IME","child edit"])
test("Expand: "+kind+" during prefill preserves text and blocks Send",async()=>{
  const h=harness();await h.bind();h.page.onYield=()=>{
    expand(h.page);h.page.doc.emit({type:kind==="child IME"?"compositionstart":"input",
      target:h.page.editor.childNodes[0].childNodes[0]});
  };
  const s=await h.arm();assert.equal(last(s).code,kind==="child IME"?"IME_ACTIVE":"RECENT_EDIT");await stopped(h,s);
});
