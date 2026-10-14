import {settle} from './native-fixture.js';
import {setupWorker,seedIndex} from "./worker-setup.js";
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import {fixture,CHAT} from "./harness.js";
const flush=settle;
async function workerFixture() {
  const page=fixture(), data={}, session={}, listeners={},access=[],calls=[];
  let rejectScript=false,request=0;
  const event=name=>({addListener:fn=>{listeners[name]=fn;}});
  const storage=(dict,kind)=>({
    setAccessLevel:async options=>{access.push({kind,...options});},
    get:async key=>({[key]:structuredClone(dict[key])}),
    set:async value=>{Object.assign(dict,structuredClone(value));}
  });
  globalThis.chrome={
    storage:{local:storage(data,"local"),session:storage(session,"session")},
    tabs:{query:async()=>[{id:1,url:page.location.href,incognito:false}],get:async()=>({id:1,url:page.location.href,incognito:false})},
    scripting:{executeScript:async spec=>{
      calls.push(spec);
      if(rejectScript)throw Error("scripting access revoked");
      return [{frameId:0,documentId:"browser-doc",result:await page.op(spec.args[0])}];
    }},
    alarms:{create:async()=>{},clear:async()=>true,onAlarm:event("alarm")},
    runtime:{id:"prototype",getURL:path=>"chrome-extension://prototype/"+path,onMessage:event("message"),
      onStartup:event("startup"),onInstalled:event("installed")}
  };
  seedIndex(data);const stored=await setupWorker(chrome);
  return {page,data,session,listeners,access,calls,set rejectScript(v){rejectScript=v;},
    send:message=>new Promise(resolve=>{
      const keep=listeners.message({...message,project_ref:"gpt-agent-bridge"},{id:"prototype",url:"chrome-extension://prototype/popup.html"},resolve);
      assert.equal(typeof keep,"boolean");request++;
    })};
}
test("MV3 wiring restricts local+session storage and injects only isolated bound document",async()=>{
  const h=await workerFixture();
  assert.equal((await h.send({action:"bind"})).ok,true);
  h.page.clock.now+=2100;
  const result=await h.send({action:"arm",delayMs:0});
  assert.equal(result.state.events[0].status,"attempted_unknown");assert.equal(h.page.clicks,1);
  assert.deepEqual(h.access,[{kind:"local",accessLevel:"TRUSTED_CONTEXTS"},{kind:"session",accessLevel:"TRUSTED_CONTEXTS"}]);
  assert(h.calls.every(c=>c.world==="ISOLATED" && c.target.tabId===1));
  assert.deepEqual(h.calls[0].target.frameIds,[0]);
  assert.deepEqual(h.calls.at(-1).target.documentIds,["browser-doc"]);
  assert.equal(h.calls.at(-1).args[0].route,CHAT);
});
test("worker refuses page/foreign sender and caller-supplied arbitrary prompt",async()=>{
  const h=await workerFixture();let replies=0;
  assert.equal(h.listeners.message({action:"arm",delayMs:0},{id:"other",url:CHAT},()=>replies++),false);
  assert.equal(h.listeners.message({action:"arm",delayMs:0},{id:"prototype",url:CHAT,tab:{id:1}},()=>replies++),false);
  assert.equal(replies,0);assert.equal(h.calls.length,0);
  const response=await h.send({action:"arm",delayMs:0,prompt:"not allowed"});
  assert.equal(response.code,"INVALID_MESSAGE");assert.equal(h.calls.length,0);
});
test("actual worker maps rejected or missing scripting API to no attempt",async()=>{
  for(const missing of [false,true]){
    const h=await workerFixture();await h.send({action:"bind"});h.page.clock.now+=2100;
    if(missing)delete chrome.scripting.executeScript;else h.rejectScript=true;
    const response=await h.send({action:"arm",delayMs:0});
    assert.equal(response.state.events[0].status,"paused");assert.equal(h.page.clicks,0);
    assert.equal(response.state.events[0].code,"PREPARE_API_UNAVAILABLE_REBIND");
  }
});
test("Chrome onStartup listener preserves IDs and disarms automatic sends",async()=>{
  const h=await workerFixture();await h.send({action:"bind"});h.page.clock.now+=2100;
  const before=await h.send({action:"arm",delayMs:60000});
  h.listeners.startup();await flush();
  const after=await h.send({action:"status"});
  assert.equal(after.state.binding,null);
  assert.equal(after.state.events[0].id,before.state.events[0].id);
  assert.equal(after.state.events[0].status,"paused");
});
test("popup missing/rejected message API shows uncertainty and does not retry",async()=>{
  const source=fs.readFileSync(new URL("../extension/popup.js",import.meta.url),"utf8").replace(/^import .*;\n/,"");
  for(const missing of [false,true]){
    let sends=0;
    const elements={};
    for(const id of ["project","status","preview","armed","arm","delay","marker","bind","inspect","retry","cancel","unbind","confirm","automatic","automatic-status","enable","disable","verify","work-marker","close_delivery"])
      elements[id]={textContent:"",value:"",disabled:false,checked:true,addEventListener(){}};
    const runtime=missing?{}:{sendMessage:async()=>{sends++;throw Error("lost");}};
    elements.project.value="gpt-agent-bridge";elements.project.replaceChildren=()=>{};elements.project.add=()=>{};
    vm.runInNewContext(source,{Option:function(text,value){return {text,value};},document:{getElementById:id=>elements[id]},chrome:{runtime},notice:()=>"",console});
    await flush();
    assert.equal(sends,missing?0:1);
    assert(elements.status.textContent.includes("不自动重试"));
    assert.equal(elements.arm.disabled,true);assert.equal(elements.armed.checked,false);
  }
});
