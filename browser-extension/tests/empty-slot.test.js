import {notice as legacyNotice} from './fixtures/legacy-controls/policy.js';
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {createHash} from "node:crypto";
import {fixture,harness,CHAT,boundPreparation} from "./harness.js";
import {notice} from "../extension/policy.js";
import {inspectAttachmentSlots} from "../extension/slot-diagnostic.js";

const CODE="ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY";
const last=s=>s.events.at(-1);
// Frozen actual historical adapter, already packaged for legacy closure regressions.
// Keep the whole-file identity check and serialized negative control independent
// of later current-adapter changes (such as the optional layout control).
const historical=fs.readFileSync(new URL("./fixtures/legacy-controls/adapter.js",import.meta.url),"utf8");
assert.equal(createHash("sha256").update(historical).digest("hex"),
  "49f0c4b6cbc5b35de62ddaa09014b36e096f67971e3cce9defc183daba7d8202");
const oldOperation=historical.replace("export async function","async function");
const tree=node=>({type:node.nodeType,tag:node.tagName,attrs:node.attrs?{...node.attrs}:undefined,
  value:node.nodeValue,children:(node.childNodes || []).map(tree)});
const child=(p,kind)=>{
  if(kind==="empty element")return p.add(p.attachments,"div");
  const comment=kind.includes("comment");
  const value=kind==="text"?"synthetic attachment":kind==="whitespace"?" \n\t":kind==="comment"?"synthetic comment":"";
  return p.attachments.appendChild({nodeType:comment?8:3,nodeValue:value,textContent:value,childNodes:[]});
};
async function bind(p) {
  const r=await p.op({op:"bind",route:CHAT,generation:"empty-slot"});
  assert.equal(r.ok,true);p.clock.now+=2100;
  return {route:CHAT,generation:"empty-slot",documentToken:r.documentToken};
}
async function unchangedUnknown(h,s,code,expected=notice(last(s).id)) {
  assert.equal(last(s).status,"attempted_unknown");assert.equal(last(s).code,code);
  assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
  assert.equal(h.page.editor.textContent,expected);
  const before=h.state,text=h.page.editor.textContent;
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await assert.rejects(h.worker.run("arm",{delayMs:0}),/ACTIVE_OR_UNCERTAIN_EVENT_EXISTS/);
  await h.newWorker().run("alarm");
  assert.deepEqual(h.state,before);assert.equal(h.page.editor.textContent,text);assert.equal(h.page.clicks,0);
}

test("empty slot: exact historical adapter rejects unhidden visible empty slot at Bind and Prepare",async()=>{
  const p=fixture(oldOperation);p.attachments.hidden=false;p.body.attrs["data-composer-layout"]="multiline";
  assert.equal(p.attachments.childNodes.length,0);assert.equal(p.attachments.getClientRects().length,1);
  const before=tree(p.doc);
  const rejected=await p.op({op:"bind",route:CHAT,generation:"old"});
  assert.equal(rejected.ok,false);assert.equal(rejected.code,CODE);
  assert.deepEqual(tree(p.doc),before);assert.equal(p.clicks,0);
  p.attachments.hidden=true;
  const request=await bind(p);p.attachments.hidden=false;
  const inspect=await p.op({...request,op:"prepare"});
  assert.equal(inspect.ok,false);assert.equal(inspect.code,CODE);
  assert.deepEqual(tree(p.doc),before);assert.equal(p.clicks,0);assert.equal(p.voiceClicks,0);
});

for(const hidden of [false,true])
test("empty slot: candidate Bind/Inspect accepts empty hidden="+hidden+" without DOM mutation",async()=>{
  const h=harness();h.page.attachments.hidden=hidden;h.page.body.attrs["data-composer-layout"]="multiline";
  const before=tree(h.page.doc);let input=0;
  h.page.doc.addEventListener("input",()=>input++);
  for(const control of [h.page.addContext,h.page.reasoning,h.page.dictate])control.onClick=()=>assert.fail("auxiliary click");
  await h.bind();const s=await h.worker.run("inspect");
  assert.equal(s.inspection,"READY_FOR_EXPLICIT_ARM");assert.equal(s.events.length,0);
  assert.deepEqual(tree(h.page.doc),before);assert.equal(input,0);
  assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);assert.equal(h.page.voiceClicks,0);
  // Existing binding/listeners/prepare lease remain normal; zero mutation here means DOM/input/click.
});

for(const owner of [false,true])for(const transition of ["replace","reuse"])
test("empty slot: synthetic same-empty-slot hidden to visible with Send "+transition+" and owner="+owner,async()=>{
  const h=harness({owner,transition}),slot=h.page.attachments;
  await h.bind();h.page.onYield=()=>{slot.hidden=false;h.page.body.attrs["data-composer-layout"]="multiline";};
  const s=await h.arm();
  assert.equal(h.page.body.querySelectorAll("[data-composer-attachments]")[0],slot);
  assert.equal(slot.childNodes.length,0);assert.equal(slot.getAttribute("hidden"),null);
  assert.equal(h.page.button.getAttribute("aria-label"),"Send");assert.equal(h.page.button.getAttribute("type"),"submit");
  assert.equal(h.page.button.form,h.page.owner);assert.equal(h.page.clicks,1);assert.equal(h.page.voiceClicks,0);
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  assert.equal(last(s).status,"handled");assert.equal(last(s).code,"SEND_CLICK_INVOKED");
  const before=h.state;await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await h.newWorker().run("alarm");assert.equal(h.page.clicks,1);assert.deepEqual(h.state,before);
});

for(const hidden of [false,true])for(const kind of ["empty element","text","whitespace","empty text","comment","empty comment"])
test("empty slot: hidden="+hidden+" with "+kind+" is a draft at Prepare and unsafe after prefill",async()=>{
  const p=fixture();p.attachments.hidden=hidden;child(p,kind);
  const before=tree(p.doc),r=await boundPreparation(p,"reject");
  assert.equal(r.ok,false);assert.equal(r.code,'DRAFT_PRESENT');assert.deepEqual(tree(p.doc),before);assert.equal(p.clicks,0);
  const h=harness();h.page.attachments.hidden=hidden;await h.bind();h.page.onYield=()=>child(h.page,kind);
  await unchangedUnknown(h,await h.arm(),CODE);
});

for(const phase of ["before insertion","after prefill"])
for(const kind of ["missing","duplicate","wrong tag","replacement"])
test("empty slot: "+kind+" visible slot "+phase+" still rejects",async()=>{
  const h=harness();h.page.attachments.hidden=false;await h.bind();
  const mutate=()=>{
    const p=h.page;
    if(kind==="missing")p.body.removeChild(p.attachments);
    if(kind==="duplicate")p.add(p.body,"div",{"data-composer-attachments":""});
    if(kind==="wrong tag")p.attachments.tagName="SPAN";
    if(kind==="replacement"){
      const next=p.add(p.doc,"div",{"data-composer-attachments":""});p.body.replaceChild(next,p.attachments);
    }
  };
  if(phase==="before insertion")h.pageHook=(_,r)=>{if(r.op==="commit")mutate();};else h.page.onYield=mutate;
  const s=await h.arm();
  if(phase==="before insertion"){
    assert.equal(last(s).status,"paused");assert.equal(last(s).code,kind==="replacement"?"COMPOSER_REPLACED":CODE);
    assert.equal(h.page.editor.textContent,"");assert.equal(h.page.clicks,0);
  }else await unchangedUnknown(h,s,kind==="replacement"?"STALE_AFTER_PREFILL_LEFT_IN_PLACE":CODE);
});

for(const [name,mutate,code] of [
  ["selected file",p=>{p.body.appendChild(p.file);p.file.files=[{}];},"ATTACHMENT"],
  ...["img","video","audio","canvas"].map(tag=>[tag,p=>p.add(p.body,tag),"ATTACHMENT"]),
  ["attachment marker",p=>p.add(p.body,"div",{"data-testid":"attachment"}),"ATTACHMENT"],
  ["upload progress",p=>p.add(p.body,"div",{"data-testid":"upload-progress"}),"COMPOSER_NOT_READY"],
])test("empty slot: visible empty slot does not bypass "+name+" guard",async()=>{
  const p=fixture();p.attachments.hidden=false;mutate(p);
  const r=await boundPreparation(p,"reject");
  assert.equal(r.ok,false);assert.equal(r.code,code==='COMPOSER_NOT_READY'?code:'DRAFT_PRESENT');assert.equal(p.editor.textContent,"");assert.equal(p.clicks,0);
  const h=harness();h.page.attachments.hidden=false;await h.bind();h.page.onYield=()=>mutate(h.page);
  await unchangedUnknown(h,await h.arm(),code);
});

test("empty slot: draft and child-target IME remain blocking with visible empty slot",async()=>{
  const h=harness();h.page.attachments.hidden=false;await h.bind();
  h.page.edit("retained draft");h.page.clock.now+=2100;
  assert.equal((await h.worker.run("inspect")).inspection,"DRAFT_PRESENT");
  const paused=await h.arm();assert.equal(last(paused).code,"DRAFT_PRESENT");
  assert.equal(h.page.editor.textContent,"retained draft");assert.equal(h.page.clicks,0);
  const ime=harness();ime.page.attachments.hidden=false;await ime.bind();
  ime.page.doc.emit({type:"compositionstart",target:ime.page.editor.childNodes[0].childNodes[0]});
  ime.page.clock.now+=2100;
  assert.equal((await ime.worker.run("inspect")).inspection,"IME_ACTIVE");
  assert.equal(last(await ime.arm()).code,"IME_ACTIVE");assert.equal(ime.page.clicks,0);
});

test("empty slot: rebind during prefill stays unknown without clicking",async()=>{
  const h=harness();h.page.attachments.hidden=false;await h.bind();let rebound;
  h.page.onYield=()=>{rebound=h.page.op({op:"bind",route:CHAT,generation:"replacement-generation"});};
  const s=await h.arm();assert.equal((await rebound).ok,true);
  await unchangedUnknown(h,s,"STALE_BINDING_REBIND_PREFILL_LEFT_IN_PLACE");
});

test("empty slot: historical visible-empty unknown survives candidate diagnostics and cannot retry",async()=>{
  const h=harness(),old=fixture(oldOperation);h.pages.set(1,old);
  await h.worker.run("bind");old.clock.now+=2100;
  old.onYield=()=>{old.attachments.hidden=false;};
  const failed=await h.arm();assert.equal(last(failed).code,CODE);assert.equal(last(failed).status,"attempted_unknown");
  assert.equal(old.clicks,0);assert.equal(old.editor.textContent,legacyNotice(last(failed).id));
  // Synthetic update: retained Controller state, new candidate function, same draft/route.
  h.pages.set(1,h.page);h.page.attachments.hidden=false;h.page.editor.textContent=old.editor.textContent;h.page.renderSend();
  h.io.slotDiagnostic=async target=>structuredClone(vm.runInNewContext("("+inspectAttachmentSlots.toString()+")",{
    document:h.page.doc,location:h.page.location,URL,
    getComputedStyle:()=>({display:"block",visibility:"visible"})
  })({route:target.route}));
  const before=h.state,text=h.page.editor.textContent;let writes=0;
  h.writeHook=()=>{writes++;};
  const inspected=await h.worker.run("inspect");
  assert.equal(inspected.inspection,"SLOT_DIAGNOSTIC_CURRENT_ONLY_UNKNOWN_NO_RETRY");
  const slot=inspected.slotDiagnostic.bodies[0].slots[0];
  assert.equal(slot.childCount,0);assert.equal(slot.hiddenPresent,false);assert.equal(slot.display,"block");
  assert.deepEqual(last(inspected),last(before));assert.deepEqual(h.state,before);assert.equal(writes,0);
  await unchangedUnknown(h,h.state,CODE,legacyNotice(last(h.state).id));assert.equal(writes,0);assert.equal(h.page.editor.textContent,text);
});
