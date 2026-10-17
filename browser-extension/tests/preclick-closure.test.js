import {settle} from './native-fixture.js';
import {setupWorker,seedIndex} from "./worker-setup.js";
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {createHash} from "node:crypto";
import {fixture,harness,CHAT} from "./harness.js";
import {Controller} from "../extension/controller.js";
import {KEY,notice,preclickEvidence,validState} from "../extension/policy.js";
import {inspectAttachmentSlots} from "../extension/slot-diagnostic.js";
import {Controller as LegacyController} from "./fixtures/legacy-controls/controller.js";
import {domOperation as legacyAdapter} from "./fixtures/legacy-controls/adapter.js";
const CODE="ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY";
const last=s=>s.events.at(-1);
const flush=settle;
const otherID="test-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const collect=p=>structuredClone(vm.runInNewContext("("+inspectAttachmentSlots.toString()+")",{
  document:p.doc,location:p.location,URL,getComputedStyle:el=>({display:el.hidden?"none":"block",visibility:"visible"})
})({route:CHAT}));
function preserved(original,closed,basis) {
  assert.equal(closed.status,"closed_before_send");assert.equal(closed.outcome,basis);
  const restored={...closed,status:original.status};
  if(Object.hasOwn(original,"outcome"))restored.outcome=original.outcome;else delete restored.outcome;
  assert.deepEqual(restored,original);
}
async function legacy() {
  const h=harness(),p=fixture(legacyAdapter);h.pages.set(1,p);
  const old=new LegacyController(h.io);await old.run("bind");p.clock.now+=2100;
  p.onYield=()=>{p.attachments.hidden=false;};
  const s=await old.run("arm",{delayMs:0});
  assert.equal(last(s).status,"attempted_unknown");assert.equal(last(s).code,CODE);
  assert.equal(Object.hasOwn(last(s),"outcome"),false);assert.equal(p.clicks,0);
  assert.equal(p.editor.textContent,notice(last(s).id));
  // Synthetic source update: same saved state/route/prefill, current candidate function.
  h.pages.set(1,h.page);h.page.attachments.hidden=false;h.page.editor.textContent=p.editor.textContent;h.page.renderSend();
  h.io.slotDiagnostic=async()=>collect(h.page);h.worker=new Controller(h.io);
  return h;
}
async function stopped() {
  const h=harness();await h.bind();h.page.onYield=()=>h.page.attachments.appendChild({nodeType:3,nodeValue:" ",childNodes:[]});
  const s=await h.arm();assert.equal(last(s).outcome,"preclick_stop");assert.equal(last(s).code,CODE);
  return h;
}
async function denied(h) {
  const before=h.state,text=h.page.editor.textContent,clicks=h.page.clicks;
  await assert.rejects(h.worker.run("cancel",{id:last(before).id}),/CANCEL_REQUIRES_PRECLICK_EVIDENCE/);
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await assert.rejects(h.arm(),/ACTIVE_OR_UNCERTAIN_EVENT_EXISTS/);
  assert.deepEqual(h.state,before);assert.equal(h.page.editor.textContent,text);assert.equal(h.page.clicks,clicks);
}

test("closure: frozen actual historical producer bytes match reviewed v2",()=>{
  for(const [name,hash] of [
    ["adapter.js","49f0c4b6cbc5b35de62ddaa09014b36e096f67971e3cce9defc183daba7d8202"],
    ["controller.js","f8741e7a6ff6c363e1ed2783b0531c144154740abd57a71a1d20ba0f5cd23e48"],
    ["policy.js","2309ff01ee97d288c98f63f165965df6d0e35096bd585e61d3d8ae6cb4734390"]
  ])assert.equal(createHash("sha256").update(fs.readFileSync(new URL("./fixtures/legacy-controls/"+name,import.meta.url))).digest("hex"),hash);
});

for(const kind of ["legacy","future"])
test("closure: "+kind+" stop is unchanged by lifecycle/Inspect; only ID-pinned Cancel closes",async()=>{
  const h=kind==="legacy"?await legacy():await stopped(),original=last(h.state),text=h.page.editor.textContent;
  h.io.slotDiagnostic=async()=>collect(h.page);
  for(const action of ["status","startup","inspect","bind","unbind","alarm"]){
    await h.worker.run(action); // Bind now selects identity only; unknown evidence stays intact.
    assert.deepEqual(last(h.state),original);assert.equal(h.page.editor.textContent,text);
  }
  h.boot="new-boot";h.worker=h.newWorker();await h.worker.run("status");
  assert.deepEqual(last(h.state),original);assert.equal(h.state.binding,null);
  const check=await h.worker.run("inspect");assert.equal(check.inspection,"SLOT_DIAGNOSTIC_CURRENT_ONLY_UNKNOWN_NO_RETRY");
  assert.deepEqual(last(check),original);
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await assert.rejects(h.arm(),/ACTIVE_OR_UNCERTAIN_EVENT_EXISTS/);
  const calls=h.calls.length,events=h.state.events.length,alarms=[...h.alarms];
  for(const name of ["page","uuid","alarm","clearAlarm"])h.io[name]=async()=>assert.fail("closure called "+name);
  const closed=await h.worker.run("cancel",{id:original.id});
  preserved(original,last(closed),kind==="legacy"?"legacy_attachment_stop":"preclick_stop");
  assert.equal(h.calls.length,calls);assert.equal(closed.events.length,events);assert.equal(h.page.clicks,0);
  assert.equal(h.page.editor.textContent,text);assert.deepEqual([...h.alarms],alarms);assert(validState(closed));
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await assert.rejects(h.worker.run("confirm",{id:original.id}),/CONFIRM_EXACT_MARKER_REQUIRED/);
  const before=h.state;await h.worker.run("cancel",{id:original.id});await h.worker.run("alarm");
  assert.deepEqual(h.state,before);assert.equal(h.page.clicks,0);
});

for(const [name,alter] of [
  ["explicit unknown",e=>{e.outcome="unknown";}],
  ["clicked evidence",e=>{e.outcome="clicked";}],
  ["legacy marker on unknown",e=>{e.outcome="legacy_attachment_stop";}],
  ["contradictory stage",e=>{e.stage="clicked";}],
  ["contradictory click flag",e=>{e.clicked=true;}],
  ["missing intent",e=>{delete e.intentAt;}],
  ["string intent",e=>{e.intentAt="10000";}],
  ["missing generation",e=>{delete e.generation;}],
  ["guard-looking prefix",e=>{e.code="ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY_ERROR";}],
  ["different guard",e=>{e.code="IME_ACTIVE";}]
])test("closure: legacy "+name+" cannot manufacture evidence",async()=>{
  const h=await legacy(),s=h.state;alter(last(s));h.state=s;
  assert.equal(preclickEvidence(last(s)),null);await denied(h);
});

const good={ok:true,stage:"after_mutation",code:CODE,documentId:"doc-1"};
for(const [name,response] of [
  ["missing",undefined],["null",null],["empty",{}],["rejected ok",{...good,ok:false}],
  ["wrong ok type",{...good,ok:"true"}],["missing stage",{ok:true,code:CODE,documentId:"doc-1"}],
  ["clicked contradictory guard",{...good,stage:"clicked"}],
  ["preclick contradictory clicked code",{...good,code:"CLICK_ATTEMPTED_RECEIPT_UNKNOWN"}],
  ["before-mutation contradictory click",{...good,stage:"blocked_before_mutation",code:"CLICK_ATTEMPTED_RECEIPT_UNKNOWN"}],
  ["future guard",{...good,code:"NEW_GUARD_ERROR"}],
  ["extra click evidence",{...good,clicked:true}],
  ["wrong document",{...good,documentId:"other"}],
  ["malformed code",{...good,code:{}}]
])test("closure: commit "+name+" result remains unknown and blocking",async()=>{
  const h=harness();await h.bind();const page=h.io.page;
  h.io.page=async(b,r)=>r.op==="commit"?structuredClone(response):page(b,r);
  const s=await h.arm();assert.equal(last(s).status,"attempted_unknown");assert.equal(last(s).outcome,"unknown");
  await denied(h);
});

for(const fault of ["rejected","timeout","clicked then rejected"])
test("closure: "+fault+" injection cannot be explicitly closed",async()=>{
  const h=harness();await h.bind();const page=h.io.page;
  h.io.page=async(b,r)=>{
    if(r.op!=="commit")return page(b,r);
    if(fault==="clicked then rejected")await page(b,r);
    throw Error(fault==="timeout"?"API_OUTCOME_UNKNOWN":"rejected");
  };
  const s=await h.arm();assert.equal(last(s).outcome,"unknown");assert.equal(last(s).code,"COMMIT_API_UNKNOWN_REBIND");
  await denied(h);
});

test("closure: actual clicked record remains blocking across restart/rebind/unbind/alarm",async()=>{
  const h=harness();await h.bind();const original=last(await h.arm());assert.equal(original.outcome,"clicked");
  h.boot="new-boot";h.worker=h.newWorker();
  for(const action of ["status","startup","inspect","bind","unbind","alarm"]){
    await h.worker.run(action);assert.deepEqual(last(h.state),original);
  }
  await denied(h);assert.equal(h.page.clicks,1);
});

test("closure: stale/missing ID and repeated Cancel never affect a newer trial",async()=>{
  const h=await stopped(),id=last(h.state).id;
  for(const args of [{},{id:otherID}])await assert.rejects(h.worker.run("cancel",args),/CANCEL_EVENT_CHANGED/);
  await h.worker.run("cancel",{id});const closed=h.state;
  let writes=0;h.writeHook=()=>writes++;await h.worker.run("cancel",{id});assert.equal(writes,0);
  const s=h.state;s.events.push({...last(s),id:otherID,status:"attempted_unknown"});h.state=s;
  await assert.rejects(h.worker.run("cancel",{id}),/CANCEL_EVENT_CHANGED/);assert.deepEqual(h.state,s);
  assert.equal(closed.events.length,1);assert.equal(h.page.clicks,0);
});

for(const persist of [false,true])
test("closure: failed/ambiguous result save persist="+persist+" never auto upgrades or follows up",async()=>{
  const h=harness();await h.bind();h.page.onYield=()=>h.page.attachments.appendChild({nodeType:8,nodeValue:"",childNodes:[]});
  h.writeHook=s=>{if(last(s)?.outcome==="preclick_stop"){if(persist)h.state=s;throw Error("RESULT_SAVE_UNKNOWN");}};
  await assert.rejects(h.arm(),/RESULT_SAVE_UNKNOWN/);h.writeHook=()=>{};
  const before=h.state;h.worker=h.newWorker();await h.worker.run("status");await h.worker.run("alarm");
  assert.deepEqual(h.state,before);assert.equal(last(h.state).status,"attempted_unknown");assert.equal(h.page.clicks,0);
  if(!persist){assert.equal(last(h.state).outcome,"unknown");await denied(h);}
  else assert.equal(last(h.state).outcome,"preclick_stop");
});

for(const persist of [false,true])
test("closure: failed/ambiguous closure save persist="+persist+" is observed without replay",async()=>{
  const h=await stopped(),id=last(h.state).id;let writes=0;const original=last(h.state),text=h.page.editor.textContent;
  h.writeHook=s=>{if(last(s).status==="closed_before_send"){writes++;if(persist)h.state=s;throw Error("CLOSE_SAVE_UNKNOWN");}};
  await assert.rejects(h.worker.run("cancel",{id}),/CLOSE_SAVE_UNKNOWN/);assert.equal(writes,1);h.writeHook=()=>{};
  const saved=h.state;h.worker=h.newWorker();await h.worker.run("status");await h.worker.run("alarm");
  assert.deepEqual(h.state,saved);assert.equal(h.page.editor.textContent,text);assert.equal(h.page.clicks,0);assert.equal(saved.events.length,1);
  if(persist)preserved(original,last(saved),"preclick_stop");else assert.deepEqual(last(saved),original);
});

test("closure: saved intent is unknown before injection and ambiguous intent cannot authorize closure",async()=>{
  const h=harness();await h.bind();h.writeHook=s=>{
    if(last(s)?.code==="INTENT_SAVED_OUTCOME_UNKNOWN"){
      assert.equal(last(s).outcome,"unknown");h.state=s;throw Error("INTENT_SAVE_UNKNOWN");
    }
  };
  await assert.rejects(h.arm(),/INTENT_SAVE_UNKNOWN/);h.writeHook=()=>{};
  assert(!h.calls.some(c=>c.op==="commit"));assert.equal(h.page.editor.textContent,"");await denied(h);
});

test("closure: successor requires separate arm, binding and empty draft before new ID",async()=>{
  const h=await legacy(),original=last(h.state);await h.worker.run("cancel",{id:original.id});
  const closed=h.state;await h.worker.run("status");await h.worker.run("alarm");assert.deepEqual(h.state,closed);
  await h.bind();
  let s=await h.arm();assert.equal(s.inspection,"DRAFT_PRESENT");assert.equal(s.events.length,1);assert.equal(h.page.clicks,0);
  await h.worker.run("unbind");s=await h.arm();assert.equal(s.events.length,1);assert.equal(s.binding,null);
  // Synthetic external draft removal and later, separate authorization; Cancel never does this.
  h.page.editor.textContent="";h.page.button.attrs={type:"button","aria-label":"Start Voice","data-state":"closed"};
  await h.bind();h.page.onYield=()=>{};
  s=await h.worker.run("arm",{delayMs:60000});assert.equal(s.events.length,2);assert.notEqual(last(s).id,original.id);
  preserved(original,s.events[0],"legacy_attachment_stop");assert.equal(last(s).status,"queued");assert.equal(h.page.clicks,0);
});

test("closure: closing one proven stop never releases a different genuine unknown",async()=>{
  const h=await stopped(),s=h.state;const stoppedEvent=last(s);
  s.events.unshift({...stoppedEvent,id:otherID,code:"CLICK_ATTEMPTED_RECEIPT_UNKNOWN",outcome:"clicked"});h.state=s;
  await h.worker.run("cancel",{id:stoppedEvent.id});
  assert.equal(h.state.events[0].outcome,"clicked");await assert.rejects(h.arm(),/ACTIVE_OR_UNCERTAIN_EVENT_EXISTS/);
  assert.equal(h.state.events.length,2);assert.equal(h.page.clicks,0);
});

for(const kind of ["access failure","malformed readiness","stale state"])
test("closure: successor "+kind+" never allocates another ID",async()=>{
  const h=await legacy(),id=last(h.state).id;await h.worker.run("cancel",{id});await h.bind();
  const before=h.state;let ids=0;h.io.uuid=()=>{ids++;assert.fail("unexpected ID allocation");};
  h.io.page=async()=>{
    if(kind==="access failure")throw Error("NO_ACCESS");
    if(kind==="stale state"){const s=h.state;s.revision++;h.state=s;}
    return {ok:true,documentId:"doc-1"};
  };
  if(kind==="stale state")await assert.rejects(h.arm(),/STALE_STATE_NO_ATTEMPT/);else await h.arm();
  assert.deepEqual(h.state.events,before.events);assert.equal(ids,0);assert.equal(h.page.clicks,0);
});

async function wire(initial) {
  const h=initial || await stopped(),data={[KEY]:h.state},session={boot:h.state.boot},listeners={},calls=[],writes=[],messages=[];
  let timeout=false;
  const event=name=>({addListener:fn=>{listeners[name]=fn;}});
  const storage=(obj,kind)=>({setAccessLevel:async()=>{},get:async k=>({[k]:structuredClone(obj[k])}),
    set:async v=>{writes.push(kind);Object.assign(obj,structuredClone(v));}});
  globalThis.chrome={storage:{local:storage(data,"local"),session:storage(session,"session")},
    tabs:{query:async()=>[{id:1,url:CHAT,incognito:false}],get:async()=>({id:1,url:CHAT,incognito:false})},
    scripting:{executeScript:async spec=>{calls.push(spec);if(timeout&&spec.args[0].op==="commit")return new Promise(()=>{});
      const result=spec.func===inspectAttachmentSlots?collect(h.page):await h.page.op(spec.args[0]);
      return [{frameId:0,documentId:"doc-1",result}];}},
    alarms:{create:async()=>{},clear:async()=>true,onAlarm:event("alarm")},
    runtime:{id:"prototype",getURL:p=>"chrome-extension://prototype/"+p,onMessage:event("message"),onStartup:event("startup"),onInstalled:event("installed")}};
  seedIndex(data);const stored=await setupWorker(chrome);writes.length=0; // one-time migration finished before the operation under test
  const send=message=>{messages.push(message);return new Promise(resolve=>{
    assert.equal(listeners.message({...message,project_ref:"gpt-agent-bridge"},{id:"prototype",url:"chrome-extension://prototype/popup.html"},resolve),true);
  });};
  return {h,data,stored,listeners,calls,writes,messages,send,set timeout(v){timeout=v;}};
}

test("closure: actual popup Cancel pins shown ID through worker and displays truthful closure",async()=>{
  const w=await wire(),original=last(await w.stored.read(KEY)),elements={};
  for(const id of ["destination","feedback","project","status","preview","armed","arm","delay","marker","bind","inspect","retry","cancel","unbind","confirm","automatic","automatic-status","enable","disable","verify","work-marker","close_delivery"])
    elements[id]={textContent:"",value:"0",disabled:false,checked:false,handlers:{},addEventListener(name,fn){this.handlers[name]=fn;}};
  const source=fs.readFileSync(new URL("../extension/popup.js",import.meta.url),"utf8").replace(/^import .*;\n/,"");
  elements.project.value="gpt-agent-bridge";elements.project.replaceChildren=()=>{};elements.project.add=()=>{};
    vm.runInNewContext(source,{setTimeout,clearTimeout,Option:function(text,value){return {text,value};},document:{getElementById:id=>elements[id]},chrome:{runtime:{sendMessage:w.send}},notice});
  await flush();assert.equal(w.messages.length,1);assert.equal(w.messages[0].action,"status");
  assert(elements.status.textContent.includes("preclick_stop"));
  const calls=w.calls.length,text=w.h.page.editor.textContent;
  elements.cancel.handlers.click();await flush();
  assert.equal(w.messages.at(-1).action,"cancel");assert.equal(w.messages.at(-1).id,original.id);
  const shown=elements.status.textContent;assert(shown.includes("closed_before_send"));assert(shown.includes(CODE));
  assert.equal(w.calls.length,calls);assert.equal(w.h.page.editor.textContent,text);preserved(original,last(await w.stored.read(KEY)),"preclick_stop");
  // A stale popup must not close the newer record, including after a double click.
  const changed=await w.stored.read(KEY);changed.events.push({...original,id:otherID});changed.revision++;await w.stored.write(KEY,changed);const before=await w.stored.read(KEY);
  elements.cancel.handlers.click();await flush();assert(elements.status.textContent.includes("CANCEL_EVENT_CHANGED"));
  assert.deepEqual(await w.stored.read(KEY),before);assert.equal(w.h.page.clicks,0);
});

test("closure: actual worker timeout remains unknown and Cancel refuses",async()=>{
  const h=harness();await h.bind();const w=await wire(h);w.timeout=true;
  const timer=globalThis.setTimeout;globalThis.setTimeout=(fn,ms)=>timer(fn,ms===8000?0:ms);
  let r;try{r=await w.send({action:"arm",delayMs:0});}finally{globalThis.setTimeout=timer;}
  assert.equal(last(r.state).outcome,"unknown");assert.equal(last(r.state).code,"COMMIT_API_UNKNOWN_REBIND");
  const before=await w.stored.read(KEY);r=await w.send({action:"cancel",id:last(before).id});
  assert.equal(r.ok,false);assert.equal(r.code,"CANCEL_REQUIRES_PRECLICK_EVIDENCE");assert.deepEqual(await w.stored.read(KEY),before);
  assert.equal(w.h.page.clicks,0);
});

test("closure: lost popup closure response triggers no automatic follow-up or replay",async()=>{
  const w=await wire(),elements={};
  for(const id of ["destination","feedback","project","status","preview","armed","arm","delay","marker","bind","inspect","retry","cancel","unbind","confirm","automatic","automatic-status","enable","disable","verify","work-marker","close_delivery"])
    elements[id]={textContent:"",value:"0",disabled:false,checked:false,handlers:{},addEventListener(name,fn){this.handlers[name]=fn;}};
  const source=fs.readFileSync(new URL("../extension/popup.js",import.meta.url),"utf8").replace(/^import .*;\n/,"");
  const sendMessage=async message=>{const r=await w.send(message);if(message.action==="cancel")throw Error("lost response");return r;};
  elements.project.value="gpt-agent-bridge";elements.project.replaceChildren=()=>{};elements.project.add=()=>{};
    vm.runInNewContext(source,{setTimeout,clearTimeout,Option:function(text,value){return {text,value};},document:{getElementById:id=>elements[id]},chrome:{runtime:{sendMessage}},notice});
  await flush();elements.cancel.handlers.click();await flush();await flush();
  assert(elements.status.textContent.includes("不自动重试"));assert.equal(last(await w.stored.read(KEY)).status,"closed_before_send");
  assert.deepEqual(w.messages.map(m=>m.action),["status","cancel"]);assert.equal(w.calls.length,0);
  assert.equal(w.h.page.clicks,0);assert.equal((await w.stored.read(KEY)).events.length,1);
});
