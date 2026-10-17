import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {fixture,harness,CHAT,OTHER} from "./harness.js";
import {route,notice,LIMIT} from "../extension/policy.js";
const last=s=>s.events.at(-1);
test("route policy excludes home/new/Work/other origin/query and requires existing ordinary UUID route",()=>{
  assert.equal(route(CHAT),CHAT);
  for(const url of ["https://chatgpt.com/","https://chatgpt.com/?q=x","https://chatgpt.com/work/c/x","https://chatgpt.com/g/g-x/c/11111111-1111-1111-1111-111111111111",CHAT+"?x=1",CHAT+"#x",CHAT+"/","https://evil.example/c/x","http://chatgpt.com/c/x"])
    assert.equal(route(url),null,url);
});
const PROJECT_PREFIX = "https://chatgpt.com/g/g-p-"+"a".repeat(32)+"-synthetic-project";
const PROJECT_CHAT = PROJECT_PREFIX+new URL(CHAT).pathname;
const ROUTE_EVENT = "test-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const routeChanges = [
  ["different Project ID",PROJECT_CHAT,PROJECT_CHAT.replace("a".repeat(32),"b".repeat(32))],
  ["different Project slug",PROJECT_CHAT,PROJECT_CHAT.replace("synthetic-project","another-project")],
  ["another Chat in the same Project",PROJECT_CHAT,PROJECT_PREFIX+new URL(OTHER).pathname],
  ["Project to bare",PROJECT_CHAT,CHAT],
  ["bare to Project",CHAT,PROJECT_CHAT]
];
test("Project route and bare route bind, inspect, and commit once through the serialized adapter",async()=>{
  for(const url of [CHAT,PROJECT_CHAT]){
    assert.equal(route(url),url);
    const h=harness();h.page.location.href=url;await h.bind();
    const binding=h.state.binding;
    assert.equal(binding.route,url);
    assert.equal((await h.worker.run("inspect")).inspection,"READY_FOR_EXPLICIT_ARM");
    const s=await h.arm();
    assert.deepEqual(s.binding,binding);
    assert.equal(last(s).route,url);
    assert.equal(last(s).status,"attempted_unknown");
    assert.equal(last(s).code,"CLICK_ATTEMPTED_RECEIPT_UNKNOWN");
    assert.equal(h.page.clicks,1);
    assert.equal(h.page.editor.textContent,notice(last(s).id));
    assert.deepEqual(h.calls.map(c=>c.op),["bind","prepare","prepare","commit"]);
    assert(h.calls.every(c=>c.tab===binding.tabId));
    await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
    await h.newWorker().run("alarm");assert.equal(h.page.clicks,1);
  }
});
test("Project route exclusions agree in policy and the serialized adapter",async()=>{
  const invalid = [
    PROJECT_CHAT.replace("/g/g-p-","/g/g-"), // Ordinary custom GPT, not a Project path.
    PROJECT_CHAT.replace("a".repeat(32),"a".repeat(31)),
    PROJECT_CHAT.replace("a".repeat(32),"z".repeat(32)),
    PROJECT_CHAT.replace("a".repeat(32),"A".repeat(32)),
    PROJECT_CHAT.replace("synthetic-project","Synthetic-project"),
    PROJECT_CHAT.replace("synthetic-project","synthetic--project"),
    PROJECT_CHAT.replace("synthetic-project","synthetic_project"),
    PROJECT_CHAT.replace("synthetic-project","prójèct"),
    PROJECT_CHAT.replace("synthetic-project",""),
    PROJECT_CHAT.replace("11111111-","AAAAAAAa-"),
    PROJECT_CHAT.slice(0,-1),
    PROJECT_CHAT+"/extra",PROJECT_CHAT+"/",
    PROJECT_CHAT+"?x=1",PROJECT_CHAT+"#x",PROJECT_CHAT+"?",PROJECT_CHAT+"#",
    CHAT+"?",CHAT+"#",
    PROJECT_CHAT.replace("https:","http:"),
    PROJECT_CHAT.replace("chatgpt.com","foreign.example"),
    PROJECT_CHAT.replace("chatgpt.com","user:pass@chatgpt.com"),
    "https://chatgpt.com/","https://chatgpt.com/work/c/"+CHAT.split("/").at(-1),
    "https://chatgpt.com/share/"+CHAT.split("/").at(-1)
  ];
  for(const url of invalid){
    assert.equal(route(url),null,url);
    const p=fixture();p.location.href=url;
    const parsed=new URL(url);
    const result=await p.op({op:"bind",route:parsed.origin+parsed.pathname,generation:"invalid"});
    assert.equal(result.ok,false,url);
    assert.equal(result.code,"ROUTE_CHANGED_REBIND",url);
    assert.equal(p.clicks,0);assert.equal(p.editor.textContent,"");
  }
});
test("Project destination changes reject stale adapter preparation and commit before mutation",async()=>{
  for(const [name,from,to] of routeChanges){
    assert.equal(route(from),from);assert.equal(route(to),to);assert.notEqual(route(from),route(to),name);
    const p=fixture();p.location.href=from;
    const bound=await p.op({op:"bind",route:from,generation:"old"});
    assert.equal(bound.ok,true,name);p.clock.now+=2100;
    const request={route:from,generation:"old",documentToken:bound.documentToken};
    const prepared=await p.op({...request,op:"prepare"});assert.equal(prepared.ok,true,name);
    // Omit the navigation event so this specifically exercises exact route comparison.
    p.location.href=to;
    const check=await p.op({...request,op:"prepare"});
    assert.equal(check.ok,false,name);assert.equal(check.code,"ROUTE_CHANGED_REBIND",name);
    const result=await p.op({...request,op:"commit",lease:prepared.lease,eventId:ROUTE_EVENT});
    assert.equal(result.stage,"blocked_before_mutation",name);
    assert.equal(result.code,"ROUTE_CHANGED_REBIND",name);
    assert.equal(p.clicks,0,name);assert.equal(p.editor.textContent,"",name);
  }
});
test("Project destination changes pause queued events and explicit rebind cannot reroute them",async()=>{
  for(const [name,from,to] of routeChanges){
    const h=harness();h.page.location.href=from;await h.bind();
    const event=last(await h.worker.run("arm",{delayMs:60000}));
    h.page.navigate(to);h.page.clock.now+=60000;
    const stopped=await h.worker.run("alarm");
    assert.equal(stopped.binding,null,name);assert.equal(last(stopped).status,"paused",name);
    assert.equal(last(stopped).route,from,name);assert.equal(h.page.clicks,0,name);
    assert.equal(h.page.editor.textContent,"",name);
    await h.bind();assert.equal(h.state.binding.route,to,name);
    await assert.rejects(h.worker.run("retry"),/EVENT_CHAT_MISMATCH/,name);
    assert.equal(last(h.state).id,event.id,name);assert.equal(last(h.state).route,from,name);
    assert.equal(h.page.clicks,0,name);assert.equal(h.page.editor.textContent,"",name);
  }
});
test("Project navigation away and back invalidates binding even when the full URL returns",async()=>{
  const h=harness();h.page.location.href=PROJECT_CHAT;await h.bind();
  await h.worker.run("arm",{delayMs:60000});
  h.page.navigate(CHAT);h.page.navigate(PROJECT_CHAT);h.page.clock.now+=60000;
  const s=await h.worker.run("alarm");
  assert.equal(last(s).status,"paused");assert.equal(last(s).code,"STALE_BINDING_REBIND");
  assert.equal(s.binding,null);assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,"");
});
test("Project change after prefill leaves text and remains unknown without retry",async()=>{
  const h=harness();h.page.location.href=PROJECT_CHAT;await h.bind();
  h.page.onYield=()=>h.page.navigate(routeChanges[0][2]);
  const s=await h.arm();
  assert.equal(last(s).route,PROJECT_CHAT);assert.equal(last(s).status,"attempted_unknown");
  assert.equal(last(s).code,"ROUTE_CHANGED_REBIND");assert.equal(s.binding,null);
  assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,notice(last(s).id));
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await h.newWorker().run("alarm");assert.equal(h.page.clicks,0);
});
test("one fixed synthetic send on a fixture with no widget; click remains unknown",async()=>{
  const h=harness();await h.bind();const s=await h.arm();
  assert.equal(h.page.clicks,1);assert.equal(last(s).status,"attempted_unknown");
  assert.equal(last(s).code,"CLICK_ATTEMPTED_RECEIPT_UNKNOWN");
  assert.equal(h.page.editor.textContent,notice(last(s).id));
  assert.equal(h.page.doc.querySelectorAll("iframe").length,0);
});
test("duplicate alarm and two callers use one event and one local attempt",async()=>{
  const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});h.page.clock.now+=60000;
  await Promise.all([h.worker.run("alarm"),h.worker.run("alarm")]);
  assert.equal(h.page.clicks,1);assert.equal(h.state.events.length,1);
  await assert.rejects(h.arm(),/ACTIVE_OR_UNCERTAIN/);
});
test("simultaneous arm actions serialize; second cannot create another ID",async()=>{
  const h=harness();await h.bind();const results=await Promise.allSettled([h.arm(),h.arm()]);
  assert.equal(results.filter(r=>r.status==="fulfilled").length,1);assert.equal(h.page.clicks,1);assert.equal(h.state.events.length,1);
});
test("send uses bound tab, never current or most recent tab",async()=>{
  const h=harness();await h.bind();h.selected=2;h.pages.get(2).location.href=OTHER;
  await h.arm();assert.equal(h.page.clicks,1);assert.equal(h.pages.get(2).clicks,0);
  assert(h.calls.every(c=>c.tab===1));
});
test("route change before arming refuses without creating an event",async()=>{
  const h=harness();await h.bind();h.page.navigate(OTHER);
  assert.equal((await h.arm()).inspection,"TARGET_CHANGED_REBIND");
  assert.equal(h.state.binding,null);assert.equal(h.state.events.length,0);assert.equal(h.page.clicks,0);
});
test("route change after queue cannot send, and SPA away/back still requires rebind",async()=>{
  const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});
  h.page.navigate(OTHER);h.page.clock.now+=60000;
  assert.equal(last(await h.worker.run("alarm")).status,"paused");assert.equal(h.page.clicks,0);
  h.page.navigate(CHAT);await assert.rejects(h.worker.run("retry"),/REBIND_REQUIRED/);
  assert.equal(h.state.binding,null);assert.equal(h.page.clicks,0);
});
for(const [name,mutate,code] of [
 ["draft",p=>{p.editor.textContent="user draft";},"DRAFT_PRESENT"],
 ["whitespace draft",p=>{p.editor.textContent=" ";},"DRAFT_PRESENT"],
 ["IME",p=>p.edit("","compositionstart"),"IME_ACTIVE"],
 ["recent typing",p=>p.edit(""),"RECENT_EDIT"],
 ["busy",p=>{p.body.attrs["aria-busy"]="true";},"BUSY_OR_UPLOAD"],
 ["stop",p=>p.add(p.doc,"button",{"data-testid":"stop-button"}),"BUSY_STOP_PRESENT"],
 ["dialog",p=>p.add(p.doc,"div",{role:"dialog"}),"DIALOG_OR_CHALLENGE"],
 ["upload",p=>{p.body.appendChild(p.file);p.file.files=[{}];},"ATTACHMENT"],
 ["attachment",p=>p.add(p.body,"div",{"data-testid":"attachment"}),"ATTACHMENT"],
 ["unknown attachment filename",p=>{p.add(p.body,"span").textContent="file.pdf";},"UNKNOWN_COMPOSER_CONTENT"],
 ["send ambiguity",p=>p.add(p.footer,"button",{type:"submit","aria-label":"Send"}),"PRIMARY_UNKNOWN_OR_AMBIGUOUS"],
 ["editor ambiguity",p=>p.add(p.body,"div",{...p.editor.attrs}),"COMPOSER_UNKNOWN_OR_AMBIGUOUS"],
 ["offline",p=>{p.navigator.onLine=false;},"OFFLINE"],
 ["challenge iframe",p=>p.add(p.doc,"iframe"),"VISIBLE_FRAME_OR_ALERT"],
 ["unknown control",p=>p.add(p.body,"button",{"data-testid":"unrecognized"}),"UNKNOWN_COMPOSER_CONTROL"],
 ["login/no composer",p=>{p.editor.attrs.contenteditable="false";},"COMPOSER_UNKNOWN_OR_AMBIGUOUS"]
]) test("guard: "+name+" stays unattempted",async()=>{
  const h=harness();await h.bind();mutate(h.page);const text=h.page.editor.textContent,s=await h.arm();
  assert.equal(last(s).status,"paused");assert.equal(last(s).code,code);assert.equal(h.page.clicks,0);
  assert.equal(h.page.editor.textContent,text);assert.equal(last(s).intentAt,undefined);
});
test("explicit safe retry keeps ID; no retry on unknown",async()=>{
  const h=harness();await h.bind();h.page.editor.textContent="draft";
  const id=last(await h.arm()).id;h.page.edit("");h.page.clock.now+=2100;
  const s=await h.worker.run("retry");assert.equal(last(s).id,id);assert.equal(h.page.clicks,1);
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
});
test("scripting rejection before intent pauses; activeTab loss does not click",async()=>{
  const h=harness();await h.bind();h.pageHook=()=>{throw Error("rejected");};
  assert.equal(last(await h.arm()).code,"PREPARE_API_UNAVAILABLE_REBIND");assert.equal(h.page.clicks,0);
  h.failTab=true;await assert.rejects(h.worker.run("retry"),/REBIND_REQUIRED/);
});
test("intent save failure prevents fill and click; ambiguous save stays deduplicated",async()=>{
  const h=harness();await h.bind();h.writeHook=s=>{
    if(last(s)?.status==="attempted_unknown"){h.state=s;throw Error("lost acknowledgement");}
  };
  await assert.rejects(h.arm(),/lost acknowledgement/);
  assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,"");
  h.writeHook=()=>{};h.worker=h.newWorker();await h.worker.run("alarm");
  assert.equal(h.page.clicks,0);await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
});
test("delayed prepare result cannot authorize changed persistent generation",async()=>{
  const h=harness();await h.bind();
  h.pageHook=(_,r)=>{if(r.op==="prepare"){const s=h.state;s.revision++;s.binding.generation="changed";h.state=s;}};
  await assert.rejects(h.arm(),/STALE_STATE/);assert.equal(h.page.clicks,0);
});
test("page edit revision and stale lease are checked after asynchronous preparation",async()=>{
  for(const stale of ["edit","expiry"]){
    const h=harness();await h.bind();
    h.pageHook=(_,r)=>{if(r.op==="commit"){if(stale==="edit")h.page.edit("");else h.page.clock.now+=4000;}};
    const s=await h.arm();assert.equal(last(s).status,"paused");assert.equal(last(s).code,"STALE_PAGE_OBSERVATION");
    assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,"");
  }
});
test("route changes immediately before commit fail before mutation",async()=>{
  const h=harness();await h.bind();h.pageHook=(_,r)=>{if(r.op==="commit")h.page.navigate(OTHER);};
  const s=await h.arm();assert.equal(last(s).status,"paused");assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,"");
});
test("worker restart retains queued record and same alarm ID",async()=>{
  const h=harness();await h.bind();const id=last(await h.worker.run("arm",{delayMs:60000})).id;
  h.worker=h.newWorker();assert.equal(last(await h.worker.run("status")).id,id);
  assert.equal(h.page.clicks,0);h.page.clock.now+=60000;await h.worker.run("alarm");assert.equal(h.page.clicks,1);
});
test("post-click response loss and worker restart never retry",async()=>{
  const h=harness();await h.bind();const original=h.io.page;
  h.io.page=async(b,r)=>{const out=await original(b,r);if(r.op==="commit")throw Error("response lost after click");return out;};
  const s=await h.arm();assert.equal(h.page.clicks,1);assert.equal(last(s).status,"attempted_unknown");
  h.worker=h.newWorker();await h.worker.run("alarm");assert.equal(h.page.clicks,1);
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
});
test("browser restart disarms queued event and requires explicit same-chat rebind/retry",async()=>{
  const h=harness();await h.bind();const id=last(await h.worker.run("arm",{delayMs:60000})).id;
  h.boot="boot-2";h.worker=h.newWorker();h.page.clock.now+=60000;
  const s=await h.worker.run("alarm");assert.equal(s.binding,null);assert.equal(last(s).status,"paused");
  assert.equal(last(s).id,id);assert.equal(h.page.clicks,0);assert.equal(h.alarms.size,0);
  await assert.rejects(h.worker.run("retry"),/REBIND_REQUIRED/);
  await h.bind();await h.worker.run("retry");assert.equal(h.page.clicks,1);
});
test("browser startup disarms even if session boot unexpectedly survives",async()=>{
  const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});
  await h.worker.run("startup");h.page.clock.now+=60000;await h.worker.run("alarm");assert.equal(h.page.clicks,0);
});
for(const kind of ["edit","route","button","revision"])
test("interference after prefill: "+kind+" leaves all text and stays unknown",async()=>{
  const h=harness();await h.bind();
  h.page.onYield=()=>{
    if(kind==="edit")h.page.edit(h.page.editor.textContent+" USER");
    if(kind==="route")h.page.navigate(OTHER);
    if(kind==="button")h.page.button.disabled=true;
    if(kind==="revision")h.page.edit(h.page.editor.textContent);
  };
  const s=await h.arm();assert.equal(h.page.clicks,0);assert.equal(last(s).status,"attempted_unknown");
  assert(h.page.editor.textContent.includes(last(s).id));
  if(kind==="edit")assert(h.page.editor.textContent.endsWith(" USER"));
  await h.worker.run("unbind");assert(h.page.editor.textContent.includes(last(s).id));
});
test("cancel/unbind preserve uncertain history and do not authorize another ID",async()=>{
  const h=harness();await h.bind();const id=last(await h.arm()).id;
  await assert.rejects(h.worker.run("cancel",{id}),/CANCEL_REQUIRES_PRECLICK_EVIDENCE/);await h.worker.run("unbind");
  assert.equal(last(h.state).id,id);assert.equal(last(h.state).status,"attempted_unknown");
  await assert.rejects(h.arm(),/ACTIVE_OR_UNCERTAIN/);
});
test("manual receipt is explicit exact marker, not click success",async()=>{
  const h=harness();await h.bind();const id=last(await h.arm()).id;
  await assert.rejects(h.worker.run("confirm",{id:"wrong"}),/CONFIRM_EXACT/);
  assert.equal(last(await h.worker.run("confirm",{id})).status,"operator_confirmed");
});
test("bounded history refuses instead of evicting old dedup IDs",async()=>{
  const h=harness();await h.bind();
  for(let i=0;i<LIMIT;i++){await h.worker.run("arm",{delayMs:60000});await h.worker.run("cancel",{id:last(h.state).id});}
  await assert.rejects(h.arm(),/HISTORY_FULL/);assert.equal(h.state.events.length,LIMIT);assert.equal(h.page.clicks,0);
});
test("cancelled queue and lost alarm do not silently recreate an event",async()=>{
  const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});await h.worker.run("cancel",{id:last(h.state).id});
  h.page.clock.now+=60000;await h.newWorker().run("alarm");assert.equal(h.page.clicks,0);assert.equal(h.state.events.length,1);
});
test("manifest restricts host access and local feed; no remote code or external messaging",()=>{
  const manifest=JSON.parse(fs.readFileSync(new URL("../extension/manifest.json",import.meta.url)));
  assert.deepEqual(manifest.permissions,["activeTab","scripting","storage","alarms"]);
  for(const key of ["content_scripts","externally_connectable","web_accessible_resources"])assert.equal(manifest[key],undefined);
  assert.deepEqual(manifest.host_permissions,["https://chatgpt.com/*","http://127.0.0.1/*"]);
  assert.equal(manifest.incognito,"not_allowed");assert(manifest.content_security_policy.extension_pages.includes("connect-src http://127.0.0.1:8765"));
  const files=fs.readdirSync(new URL("../extension",import.meta.url)).filter(f=>f.endsWith(".js"));
  const source=files.map(f=>fs.readFileSync(new URL("../extension/"+f,import.meta.url),"utf8")).join("\n");
  assert(!/XMLHttpRequest|WebSocket|EventSource|sendBeacon|setInterval|eval\s*\(|new Function|\.cookies\b|\.debugger\b|\.clipboard\b/.test(source));
  assert(!source.includes('world:"MAIN"'));assert(!source.includes("sendFollowUpMessage"));
  assert(source.includes('accessLevel:"TRUSTED_CONTEXTS"'));
  assert(!source.includes("innerHTML"));
  assert.match(source,/lease\.editor\.removeChild\(inserted\)/);
});

test("SPA away and back before observation invalidates the old binding",async()=>{
 const h=harness();await h.bind();h.page.navigate(OTHER);h.page.navigate(CHAT);
 const s=await h.arm();assert.equal(last(s).code,"STALE_BINDING_REBIND");assert.equal(s.binding,null);assert.equal(h.page.clicks,0);
});
test("missing alarm can be explicitly attempted with the same ID, never auto recreated",async()=>{
 const h=harness();await h.bind();const id=last(await h.worker.run("arm",{delayMs:60000})).id;
 h.alarms.clear();h.worker=h.newWorker();h.page.clock.now+=60000;
 assert.equal(last(await h.worker.run("status")).status,"queued");assert.equal(h.page.clicks,0);
 assert.equal(last(await h.worker.run("retry")).id,id);assert.equal(h.page.clicks,1);
});
test("rebind another chat never reroutes a queued synthetic event",async()=>{
 const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});
 h.selected=2;h.pages.get(2).location.href=OTHER;await h.bind();
 await assert.rejects(h.worker.run("retry"),/EVENT_CHAT_MISMATCH/);assert.equal(h.pages.get(2).clicks,0);
});

test("inspection with lost access disarms pending queue and requires rebind",async()=>{
 const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});h.failTab=true;
 const s=await h.worker.run("inspect");assert.equal(s.binding,null);assert.equal(last(s).status,"paused");
 assert.equal(h.alarms.size,0);assert.equal(h.page.clicks,0);
});
test("incognito/ineligible bind never keeps an older queue armed",async()=>{
 const h=harness();await h.bind();await h.worker.run("arm",{delayMs:60000});
 h.io.selectedTab=async()=>({id:2,url:CHAT,incognito:true});
 await assert.rejects(h.worker.run("bind"),/INELIGIBLE_CHAT/);
 assert.equal(h.state.binding,null);assert.equal(last(h.state).status,"paused");assert.equal(h.page.clicks,0);
});
test("crash before commit response has saved intent, no automatic retry after new worker",async()=>{
 const h=harness();await h.bind();h.pageHook=(_,r)=>{if(r.op==="commit")throw Error("worker/page connection lost before fill");};
 const s=await h.arm();assert.equal(last(s).status,"attempted_unknown");assert.equal(h.page.clicks,0);
 h.pageHook=()=>{};h.worker=h.newWorker();await h.worker.run("alarm");
 await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);assert.equal(h.page.clicks,0);
 h.boot="boot-2";const restart=await h.newWorker().run("status");
 assert.equal(last(restart).status,"attempted_unknown");assert.equal(restart.binding,null);
});


const REPAIR_EVENT = "test-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const REPAIR_SLOT = "__bridgeSyntheticNoticeV1";
const REPAIR_CODE = "STALE_BINDING_REBIND_PREFILL_LEFT_IN_PLACE";
async function preparedRepairPage() {
  const p = fixture();
  const bound = await p.op({op:"bind",route:CHAT,generation:"old"});
  p.clock.now += 2100;
  const req = {route:CHAT,generation:"old",documentToken:bound.documentToken};
  const ready = await p.op({...req,op:"prepare"});
  assert.equal(ready.ok,true);
  return {p,req,commit:{...req,op:"commit",lease:ready.lease,eventId:REPAIR_EVENT}};
}
function assertRepairStopped(p,result) {
  assert.equal(p.clicks,0);
  assert.equal(result.stage,"after_mutation");
  assert.equal(result.code,REPAIR_CODE);
  assert.equal(p.editor.textContent,notice(REPAIR_EVENT));
}
test("repair: delayed replacement bind invalidates surviving old commit within its lease",async()=>{
  const {p,req,commit} = await preparedRepairPage();
  const before = p.clock.now;
  let replacement;
  p.onYield = () => {
    replacement = p.op({op:"bind",route:CHAT,generation:"replacement"});
    p.clock.now += 2100; // Past replacement quiet period, still inside old lease.
  };
  const result = await p.op(commit);
  const bound = await replacement;
  assert.equal(bound.ok,true);
  assert.notEqual(bound.documentToken,req.documentToken);
  assert.equal(p.window[REPAIR_SLOT].generation,"replacement");
  assert(p.clock.now-before < 3000);
  assertRepairStopped(p,result);
});
test("repair: immediate rebind control preserves prefill and cannot hide delayed case",async()=>{
  const {p,commit} = await preparedRepairPage();
  let replacement;
  p.onYield = () => { replacement = p.op({op:"bind",route:CHAT,generation:"replacement"}); };
  const result = await p.op(commit);
  await replacement;
  assert.equal(p.clicks,0);
  assert.equal(result.stage,"after_mutation");
  assert(["RECENT_EDIT",REPAIR_CODE].includes(result.code));
  assert.equal(p.editor.textContent,notice(REPAIR_EVENT));
});
for (const field of ["generation","documentToken"])
test("repair: "+field+" alone changes after await without an edit revision",async()=>{
  const {p,commit} = await preparedRepairPage();
  const revision = p.window[REPAIR_SLOT].revision;
  p.onYield = () => { p.window[REPAIR_SLOT][field] = "replacement-only"; };
  const result = await p.op(commit);
  assert.equal(p.window[REPAIR_SLOT].revision,revision);
  assertRepairStopped(p,result);
});
for (const field of ["generation","documentToken"])
test("repair: "+field+" changes after post-await guard but before final click",async()=>{
  const {p,commit} = await preparedRepairPage();
  // A synthetic getter changes identity after the post-await guard's DOM read.
  // This tests the final boundary, not an assertion about normal DOM getters.
  p.onYield = () => Object.defineProperty(p.button,"disabled",{get() {
    p.window[REPAIR_SLOT][field] = "late-replacement";
    return false;
  }});
  assertRepairStopped(p,await p.op(commit));
});
test("repair: unchanged binding identity still permits one fixed click",async()=>{
  const {p,req,commit} = await preparedRepairPage();
  const result = await p.op(commit);
  assert.equal(p.window[REPAIR_SLOT].generation,req.generation);
  assert.equal(p.window[REPAIR_SLOT].documentToken,req.documentToken);
  assert.equal(p.clicks,1);
  assert.equal(result.stage,"clicked");
  assert.equal(result.code,"CLICK_ATTEMPTED_RECEIPT_UNKNOWN");
  assert.equal(p.editor.textContent,notice(REPAIR_EVENT));
});
test("repair: surviving injection identity loss stays unknown and cannot safely retry",async()=>{
  const h = harness();
  await h.bind();
  let replacement;
  h.page.onYield = () => {
    replacement = h.page.op({op:"bind",route:CHAT,generation:"replacement-worker"});
    h.page.clock.now += 2100;
  };
  const state = await h.arm();
  await replacement;
  assert.equal(h.page.clicks,0);
  assert.equal(last(state).status,"attempted_unknown");
  assert.equal(last(state).code,REPAIR_CODE);
  assert.equal(state.binding,null);
  assert.equal(h.page.editor.textContent,notice(last(state).id));
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await h.newWorker().run("alarm");
  assert.equal(h.page.clicks,0);
});
