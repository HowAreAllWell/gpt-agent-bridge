import {settle} from './native-fixture.js';
import {setupWorker,seedIndex} from "./worker-setup.js";
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import {inspectAttachmentSlots,validSlotSnapshot} from "../extension/slot-diagnostic.js";
import {fixture,harness,CHAT,OTHER} from "./harness.js";
import {KEY,notice} from "../extension/policy.js";
const SLOT="__bridgeSyntheticNoticeV1";
const CODE="ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY";
const last=s=>s.events.at(-1);
const flush=settle;
function collect(p,overrides={},request={route:CHAT}) {
  const context={document:p.doc,location:p.location,URL,window:p.window,
    getComputedStyle:el=>({display:el.hidden?"none":"block",visibility:"visible"}),...overrides};
  return structuredClone(vm.runInNewContext("("+inspectAttachmentSlots.toString()+")",context)(request));
}
function textNode(text,nodeType=3) {
  return {nodeType,nodeValue:text,textContent:text,childNodes:[]};
}
async function unknownFixture() {
  const h=harness();await h.bind();
  h.page.onYield=()=>h.page.attachments.appendChild(textNode(" "));
  await h.arm();
  assert.equal(last(h.state).status,"attempted_unknown");
  assert.equal(last(h.state).code,CODE);assert.equal(h.page.clicks,0);
  h.io.slotDiagnostic=async target=>{
    assert.equal(target.route,CHAT);
    return collect(h.page);
  };
  return h;
}
function forbidMutation(h) {
  const before=h.state, text=h.page.editor.textContent, alarm=[...h.alarms];
  let selected=0, diagnostics=0;const forbiddenCalls=[];
  const get=h.io.selectedTab, diagnostic=h.io.slotDiagnostic;
  h.io.selectedTab=async()=>{selected++;return get();};
  h.io.slotDiagnostic=async target=>{diagnostics++;return diagnostic(target);};
  for(const name of ["write","boot","clearAlarm","alarm","page","uuid"])
    h.io[name]=async()=>{forbiddenCalls.push(name);throw Error("FORBIDDEN_"+name);};
  return {before,check(){assert.deepEqual(h.state,before);assert.equal(h.page.editor.textContent,text);
    assert.equal(h.page.clicks,0);assert.deepEqual([...h.alarms],alarm);assert.deepEqual(forbiddenCalls,[]);},
    get selected(){return selected;},get diagnostics(){return diagnostics;}};
}

test("slot diagnostic: absent and duplicate slots report counts, not guard guesses",()=>{
  const p=fixture();
  let r=collect(p);assert.equal(r.ok,true);assert(validSlotSnapshot(r.snapshot));
  assert.equal(r.snapshot.bodyCount,1);assert.equal(r.snapshot.bodies[0].slotCount,1);
  assert.equal(r.snapshot.bodies[0].slots[0].childCount,0);
  p.body.removeChild(p.attachments);
  r=collect(p);assert.equal(r.snapshot.bodies[0].slotCount,0);
  p.add(p.body,"div",{"data-composer-attachments":""});
  p.add(p.body,"span",{"data-composer-attachments":""});
  r=collect(p);assert.equal(r.snapshot.bodies[0].slotCount,2);
  assert.deepEqual(r.snapshot.bodies[0].slots.map(s=>s.tag),["DIV","SPAN"]);
});

for(const [value,state] of [[null,"absent"],["","empty"],["hidden","hidden"],["until-found","until-found"],["private filename","other"]])
test("slot diagnostic: hidden enum "+state+" and independent CSS/rect values",()=>{
  const p=fixture();if(value===null)delete p.attachments.attrs.hidden;else p.attachments.attrs.hidden=value;
  p.attachments.getClientRects=()=>[{},{}];
  const r=collect(p,{getComputedStyle:()=>({display:"flex",visibility:"hidden"})});
  const s=r.snapshot.bodies[0].slots[0];
  assert.equal(s.hiddenPresent,value!==null);assert.equal(s.hiddenState,state);
  assert.equal(s.display,"flex");assert.equal(s.visibility,"hidden");assert.equal(s.rectCount,2);
  assert(!JSON.stringify(r).includes("private filename"));
});

test("slot diagnostic: whitespace, comments and element text expose only booleans/counts",()=>{
  const p=fixture();
  p.attachments.appendChild(textNode(" \n\t"));
  p.attachments.appendChild(textNode("private-comment",8));
  const span=p.add(p.attachments,"span");span.textContent="private-file-name.pdf";
  const r=collect(p), children=r.snapshot.bodies[0].slots[0].children;
  assert.deepEqual(children,[
    {nodeType:3,tag:null,childCount:0,hasNonWhitespace:false},
    {nodeType:8,tag:null,childCount:0,hasNonWhitespace:true},
    {nodeType:1,tag:"SPAN",childCount:1,hasNonWhitespace:true}
  ]);
  assert(!/private|pdf/.test(JSON.stringify(r)));
});

test("slot diagnostic: 4 bodies / 4 slots / 8 children with true counts and truncation",()=>{
  const p=fixture();p.doc.removeChild(p.body);
  for(let i=0;i<6;i++){
    const b=p.add(p.doc,"div",{"data-composer-body":"","data-composer-layout":"single-line"});
    for(let j=0;j<7;j++){
      const s=p.add(b,"div",{"data-composer-attachments":"",hidden:""});
      for(let k=0;k<11;k++)s.appendChild(textNode("secret-"+k));
    }
  }
  const r=collect(p);assert(validSlotSnapshot(r.snapshot));
  assert.equal(r.snapshot.bodyCount,6);assert.equal(r.snapshot.bodiesTruncated,true);
  assert.equal(r.snapshot.bodies.length,4);
  for(const b of r.snapshot.bodies){
    assert.equal(b.slotCount,7);assert.equal(b.slotsTruncated,true);assert.equal(b.slots.length,4);
    for(const s of b.slots){assert.equal(s.childCount,11);assert.equal(s.childrenTruncated,true);assert.equal(s.children.length,8);}
  }
  assert(!JSON.stringify(r).includes("secret"));
});

test("slot diagnostic: layout/tag/style values cannot return arbitrary strings or body content",()=>{
  const p=fixture();p.body.attrs["data-composer-layout"]="PRIVATE_BODY_VALUE".repeat(1000);
  p.attachments.tagName="PRIVATE_CUSTOM_TAG";
  Object.defineProperty(p.editor,"textContent",{get(){throw Error("EDITOR_READ");}});
  Object.defineProperty(p.body,"textContent",{get(){throw Error("BODY_TEXT_READ");}});
  const r=collect(p,{getComputedStyle:()=>({display:"PRIVATE_CSS",visibility:"PRIVATE_CSS"})});
  assert.equal(r.ok,true);assert(validSlotSnapshot(r.snapshot));
  const b=r.snapshot.bodies[0],s=b.slots[0];
  assert.equal(b.layout,"other");assert.equal(s.tag,"OTHER");assert.equal(s.display,"other");assert.equal(s.visibility,"other");
  assert(!JSON.stringify(r).includes("PRIVATE"));
});

for(const existing of [false,true])
test("slot diagnostic: "+(existing?"existing":"absent")+" SLOT and listeners remain untouched",()=>{
  const p=fixture(), slot={generation:"old",lease:{token:"old-lease"},revision:7};
  if(existing)p.window[SLOT]=slot;
  const windowKeys=Object.keys(p.window),listeners={...p.doc.listeners},navigation=[...p.window.navigation.listeners];
  p.editor.textContent="KEEP PREFILL";
  p.doc.addEventListener=()=>{throw Error("LISTENER");};
  p.doc.createTextNode=()=>{throw Error("CREATE");};
  p.editor.appendChild=()=>{throw Error("APPEND");};
  p.editor.dispatchEvent=()=>{throw Error("DISPATCH");};
  p.button.click=()=>{throw Error("CLICK");};
  const r=collect(p,{setTimeout(){throw Error("TIMER");},MutationObserver:class{constructor(){throw Error("OBSERVER");}}});
  assert.equal(r.ok,true);
  assert.deepEqual(Object.keys(p.window),windowKeys);assert.equal(p.window[SLOT],existing?slot:undefined);
  assert.deepEqual(slot,{generation:"old",lease:{token:"old-lease"},revision:7});
  assert.deepEqual(p.doc.listeners,listeners);assert.deepEqual(p.window.navigation.listeners,navigation);
  assert.equal(p.editor.textContent,"KEEP PREFILL");assert.equal(p.clicks,0);
});

test("slot diagnostic: collector route rejection and read errors contain no raw exception",()=>{
  const p=fixture();p.location.href=OTHER;
  assert.equal(collect(p).code,"SLOT_DIAGNOSTIC_ROUTE_MISMATCH");
  p.location.href=CHAT;
  const r=collect(p,{getComputedStyle(){throw Error("SECRET_EXCEPTION");}});
  assert.equal(r.code,"SLOT_DIAGNOSTIC_READ_UNAVAILABLE");assert(!JSON.stringify(r).includes("SECRET"));
});

for(const mode of ["binding","startup","boot-loss"])
test("slot diagnostic: Controller retains unknown/pre-fill with "+mode+" and does not write",async()=>{
  const h=await unknownFixture();
  if(mode==="startup")await h.worker.run("startup");
  if(mode==="boot-loss")h.boot="new-boot";
  const f=forbidMutation(h), s=await h.worker.run("inspect");
  assert.equal(s.inspection,"SLOT_DIAGNOSTIC_CURRENT_ONLY_UNKNOWN_NO_RETRY");
  assert(validSlotSnapshot(s.slotDiagnostic));assert.equal(last(s).code,CODE);assert.equal(last(s).status,"attempted_unknown");
  assert.deepEqual(s.binding,f.before.binding);assert.equal(f.selected,2);assert.equal(f.diagnostics,1);f.check();
});

for(const kind of ["wrong route","incognito","tab access","script access","target changed","state changed","malformed result"])
test("slot diagnostic: Controller "+kind+" refuses without writes/sends or READY",async()=>{
  const h=await unknownFixture();
  if(kind==="wrong route")h.io.selectedTab=async()=>({id:1,url:OTHER,incognito:false});
  if(kind==="incognito")h.io.selectedTab=async()=>({id:1,url:CHAT,incognito:true});
  if(kind==="tab access")h.io.tab=async()=>{throw Error("NO_ACCESS");};
  if(kind==="script access")h.io.slotDiagnostic=async()=>{throw Error("SECRET");};
  if(kind==="target changed"){let n=0;h.io.selectedTab=async()=>({id:++n===1?1:2,url:CHAT,incognito:false});}
  if(kind==="state changed"){const read=h.io.read;let n=0;h.io.read=async k=>{const s=await read(k);if(++n===2)s.revision++;return s;};}
  if(kind==="malformed result")h.io.slotDiagnostic=async()=>({ok:true,snapshot:{leak:"SECRET"}});
  const f=forbidMutation(h),s=await h.worker.run("inspect");
  assert(s.inspection.startsWith("SLOT_DIAGNOSTIC_"));assert(!s.inspection.includes("CURRENT_ONLY"));
  assert(!s.inspection.includes("READY"));assert.equal(s.slotDiagnostic,undefined);f.check();
});

test("slot diagnostic: unrelated unknown and missing diagnostic event do not enter collector",async()=>{
  const h=await unknownFixture();const state=h.state;last(state).code="CLICK_ATTEMPTED_RECEIPT_UNKNOWN";h.state=state;
  const f=forbidMutation(h);
  const s=await h.worker.run("inspect");assert.equal(s.inspection,"SLOT_DIAGNOSTIC_EVENT_UNAVAILABLE_NO_RETRY");
  assert.equal(f.selected,0);assert.equal(f.diagnostics,0);f.check();
  const empty={...state,events:[],binding:null};
  const refused=await h.worker.inspectSlot(empty,undefined);
  assert.equal(refused.inspection,"SLOT_DIAGNOSTIC_EVENT_UNAVAILABLE_NO_RETRY");assert.equal(f.diagnostics,0);
});

test("slot diagnostic: normal unattempted Inspect stays unchanged and status never collects",async()=>{
  const h=harness();await h.bind();h.io.slotDiagnostic=async()=>{throw Error("MUST_NOT_COLLECT");};
  assert.equal((await h.worker.run("inspect")).inspection,"READY_FOR_EXPLICIT_ARM");
  const u=await unknownFixture();let diagnostics=0;u.io.slotDiagnostic=async()=>{diagnostics++;return collect(u.page);};
  await u.worker.run("status");assert.equal(diagnostics,0);
  await u.worker.run("inspect");assert.equal(diagnostics,1);
  const status=await u.worker.run("status");assert.equal(diagnostics,1);assert.equal(status.slotDiagnostic,undefined);
  await assert.rejects(u.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  assert.equal(u.page.clicks,0);
});

for(const mutate of [
 s=>{s.extra="secret";},s=>{s.bodyCount=-1;},s=>{s.bodiesTruncated=true;},
 s=>{s.bodies[0].layout="secret";},s=>{s.bodies[0].slots[0].hiddenState="secret";},
 s=>{s.bodies[0].slots[0].display="url(secret)";},s=>{s.bodies[0].slots[0].rectCount=NaN;},
 s=>{s.bodies[0].slots[0].children=[{text:"secret"}];}
])test("slot diagnostic: fixed-shape validator refuses injected/oversized/invalid fields",()=>{
  const s=collect(fixture()).snapshot;mutate(s);assert.equal(validSlotSnapshot(s),false);
});

async function actualWorker() {
  const setup=await unknownFixture(), page=setup.page;
  const data={[KEY]:setup.state},session={boot:setup.state.boot};
  const listeners={},writes=[],calls=[],alarms=[],queries=[];
  let selected={id:1,url:CHAT,incognito:false},resultFault=null;
  const event=name=>({addListener:fn=>{listeners[name]=fn;}});
  const storage=(dict,name)=>({
    setAccessLevel:async()=>{},
    get:async key=>({[key]:structuredClone(dict[key])}),
    set:async value=>{writes.push({name,value:structuredClone(value)});Object.assign(dict,structuredClone(value));}
  });
  globalThis.chrome={
    storage:{local:storage(data,"local"),session:storage(session,"session")},
    tabs:{query:async()=>{queries.push("selected");return [selected];},get:async()=>({...selected})},
    scripting:{executeScript:async spec=>{
      calls.push(spec);if(resultFault==="throw")throw Error("PRIVATE_ACCESS_ERROR");
      assert.equal(spec.func,inspectAttachmentSlots);
      const result=collect(page,{},spec.args[0]);
      let receipt={frameId:0,documentId:"current-document",result};
      if(resultFault==="frame")receipt.frameId=1;
      if(resultFault==="document")receipt.documentId="";
      if(resultFault==="extra")receipt.result={...result,private:"SECRET"};
      if(resultFault==="snapshot")receipt.result={ok:true,snapshot:{secret:"SECRET"}};
      return resultFault==="multiple"?[receipt,receipt]:[receipt];
    }},
    alarms:{create:async()=>alarms.push("create"),clear:async()=>{alarms.push("clear");return true;},onAlarm:event("alarm")},
    runtime:{id:"prototype",getURL:p=>"chrome-extension://prototype/"+p,onMessage:event("message"),onStartup:event("startup"),onInstalled:event("installed")}
  };
  seedIndex(data);const stored=await setupWorker(chrome);writes.length=0; // one-time migration finished before the operation under test
  return {page,data,stored,session,listeners,writes,calls,alarms,queries,
    set selected(value){selected=value;},set resultFault(value){resultFault=value;},
    send:action=>new Promise(resolve=>{
      assert.equal(listeners.message({action,project_ref:"gpt-agent-bridge"},{id:"prototype",url:"chrome-extension://prototype/popup.html"},resolve),true);
    })};
}

for(const cleared of [false,true])
test("slot diagnostic: actual worker "+(cleared?"onInstalled-cleared":"existing")+" binding and actual popup Inspect",async()=>{
  const w=await actualWorker();
  if(cleared){w.listeners.installed();await flush();assert.equal((await w.stored.read(KEY)).binding,null);}
  const stored=await w.stored.read(KEY),prefill=w.page.editor.textContent;
  w.writes.length=0;w.alarms.length=0;
  const elements={};
  for(const id of ["destination","feedback","project","status","preview","armed","arm","delay","marker","bind","inspect","retry","cancel","unbind","confirm","automatic","automatic-status","enable","disable","verify","work-marker","close_delivery"])
    elements[id]={textContent:"",value:"",disabled:false,checked:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
  const messages=[];
  const popup=fs.readFileSync(new URL("../extension/popup.js",import.meta.url),"utf8").replace(/^import .*;\n/,"");
  elements.project.value="gpt-agent-bridge";elements.project.replaceChildren=()=>{};elements.project.add=()=>{};
    vm.runInNewContext(popup,{setTimeout,clearTimeout,Option:function(text,value){return {text,value};},document:{getElementById:id=>elements[id]},notice,
    chrome:{runtime:{sendMessage:async m=>{messages.push(m.action);return w.send(m.action);}}}});
  await flush();assert.deepEqual(messages,["status"]);assert.equal(w.calls.length,0);
  assert(!elements.status.textContent.includes("slotDiagnostic"));
  elements.inspect.listeners.click();await flush();
  assert.deepEqual(messages,["status","inspect"]);assert.equal(w.calls.length,1);
  const shown=elements.status.textContent;
  assert(shown.includes("SLOT_DIAGNOSTIC_CURRENT_ONLY_UNKNOWN_NO_RETRY"));
  assert(shown.includes("附件槽：仅当前结构"));
  assert(shown.includes("attempted_unknown"));assert(shown.includes(CODE));
  assert(!shown.includes(CHAT));
  assert.deepEqual(w.calls[0].target,{tabId:1,frameIds:[0]});assert.equal(w.calls[0].world,"ISOLATED");
  assert.deepEqual(w.calls[0].args,[{route:CHAT}]);
  assert.deepEqual(await w.stored.read(KEY),stored);assert.equal(w.writes.length,0);assert.equal(w.alarms.length,0);
  assert.equal(w.page.editor.textContent,prefill);assert.equal(w.page.clicks,0);
  const retry=await w.send("retry");assert.equal(retry.ok,false);assert.equal(retry.code,"NOT_SAFE_TO_RETRY");
});

for(const fault of ["throw","frame","document","extra","snapshot","multiple"])
test("slot diagnostic: actual worker rejects "+fault+" receipt without mutation",async()=>{
  const w=await actualWorker(),before=await w.stored.read(KEY);w.resultFault=fault;
  const r=await w.send("inspect");
  assert.equal(r.ok,true);assert(!r.state.inspection.includes("READY"));
  assert.equal(r.state.slotDiagnostic,undefined);assert.deepEqual(await w.stored.read(KEY),before);
  assert.equal(w.writes.length,0);assert.equal(w.alarms.length,0);assert.equal(w.page.clicks,0);
  assert(!JSON.stringify(r).includes("SECRET"));assert(!JSON.stringify(r).includes("PRIVATE"));
});

test("slot diagnostic: actual worker wrong selected route never injects",async()=>{
  const w=await actualWorker(),before=await w.stored.read(KEY);
  w.selected={id:2,url:OTHER,incognito:false};
  const r=await w.send("inspect");
  assert.equal(r.state.inspection,"SLOT_DIAGNOSTIC_TARGET_MISMATCH_NO_RETRY");
  assert.equal(w.calls.length,0);assert.equal(w.writes.length,0);assert.deepEqual(await w.stored.read(KEY),before);
});

test("slot diagnostic: missing body and exact-limit arrays retain truthful zero/truncation",()=>{
  const p=fixture();p.doc.removeChild(p.body);
  let s=collect(p).snapshot;
  assert.equal(s.bodyCount,0);assert.equal(s.bodiesTruncated,false);assert.deepEqual(s.bodies,[]);
  const b=p.add(p.doc,"div",{"data-composer-body":""});
  const slot=p.add(b,"div",{"data-composer-attachments":""});
  for(let i=0;i<8;i++)slot.appendChild(textNode(""));
  s=collect(p).snapshot;assert.equal(s.bodies[0].layout,"absent");
  assert.equal(s.bodies[0].slots[0].childCount,8);assert.equal(s.bodies[0].slots[0].childrenTruncated,false);
  assert(validSlotSnapshot(s));
});

test("slot diagnostic: full Project route is retained, never interchanged with its bare Chat",async()=>{
  const h=await unknownFixture();
  const project="https://chatgpt.com/g/g-p-"+"a".repeat(32)+"-synthetic-project"+new URL(CHAT).pathname;
  const state=h.state;last(state).route=project;state.binding.route=project;h.state=state;
  h.page.location.href=project;
  h.io.slotDiagnostic=async target=>collect(h.page,{}, {route:target.route});
  const f=forbidMutation(h);
  const good=await h.worker.run("inspect");assert(validSlotSnapshot(good.slotDiagnostic));f.check();
  h.io.selectedTab=async()=>({id:1,url:CHAT,incognito:false});
  const bad=await h.worker.run("inspect");
  assert.equal(bad.inspection,"SLOT_DIAGNOSTIC_TARGET_MISMATCH_NO_RETRY");f.check();
});

test("slot diagnostic: post-observation target navigation rejects before exposing a snapshot",async()=>{
  const h=await unknownFixture();let reads=0;
  h.io.tab=async()=>({id:1,url:++reads===1?CHAT:OTHER,incognito:false});
  const f=forbidMutation(h),s=await h.worker.run("inspect");
  assert.equal(s.slotDiagnostic,undefined);assert(!s.inspection.includes("READY"));f.check();
});

test("slot diagnostic: popup failure remains explicit and never retries or creates a notification",async()=>{
  const w=await actualWorker(),before=await w.stored.read(KEY);w.resultFault="throw";
  const elements={};
  for(const id of ["destination","feedback","project","status","preview","armed","arm","delay","marker","bind","inspect","retry","cancel","unbind","confirm","automatic","automatic-status","enable","disable","verify","work-marker","close_delivery"])
    elements[id]={textContent:"",value:"",disabled:false,checked:false,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
  const messages=[];
  const source=fs.readFileSync(new URL("../extension/popup.js",import.meta.url),"utf8").replace(/^import .*;\n/,"");
  elements.project.value="gpt-agent-bridge";elements.project.replaceChildren=()=>{};elements.project.add=()=>{};
    vm.runInNewContext(source,{setTimeout,clearTimeout,Option:function(text,value){return {text,value};},document:{getElementById:id=>elements[id]},notice,
    chrome:{runtime:{sendMessage:async m=>{messages.push(m.action);return w.send(m.action);}}}});
  await flush();elements.inspect.listeners.click();await flush();
  const shown=elements.status.textContent;
  assert(shown.includes("NO_RETRY"));assert(!shown.includes("附件槽："));
  assert(shown.includes("attempted_unknown"));
  assert.deepEqual(messages,["status","inspect"]);assert.equal(w.calls.length,1);
  assert.equal(w.writes.length,0);assert.deepEqual(await w.stored.read(KEY),before);
});

test("slot diagnostic: actual worker missing scripting API refuses without storage/alarm changes",async()=>{
  const w=await actualWorker(),before=await w.stored.read(KEY);
  delete chrome.scripting.executeScript;
  const r=await w.send("inspect");
  assert.equal(r.state.slotDiagnostic,undefined);assert(!r.state.inspection.includes("READY"));
  assert.equal(w.writes.length,0);assert.equal(w.alarms.length,0);assert.deepEqual(await w.stored.read(KEY),before);
});
