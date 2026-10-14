import {inspectAttachmentSlots, validSlotSnapshot} from "./slot-diagnostic.js";
import {ProjectControllers} from "./projects.js";
import {observeReceipt} from "./receipt.js";
import {POLL, completionId} from "./completion-policy.js";
import {domOperation} from "./adapter.js";
import {ALARM} from "./policy.js";

export function wireWorker(chrome, connection, fetch = globalThis.fetch) {
// Listeners registered synchronously; alarms wake a sleeping worker. No MCP dependency.
const workerInstance = crypto.randomUUID();
async function feed(query={}, status, catalog=false) {
  if(!connection || connection.extension_id!==chrome.runtime.id)
    throw Error("LOCAL_CONNECTION_NOT_CONFIGURED");
  const url=new URL(catalog?"/browser-notifications/v1/projects":"/browser-notifications/v1/events",connection.url);
  if(url.origin!=="http://127.0.0.1:8765")throw Error("LOCAL_CONNECTION_INVALID");
  for(const [key,value] of Object.entries(query))url.searchParams.set(key,String(value));
  const response=await fetch(url.href,{method:status?"POST":"GET",credentials:"omit",cache:"no-store",
    headers:{Authorization:"Bearer "+connection.token,...(status?{"Content-Type":"application/json"}:{})},
    body:status?JSON.stringify(status):undefined,signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw Error("BRIDGE_FEED_UNAVAILABLE");
  return response.json();
}
const trusted = Promise.all([
  chrome.storage.local.setAccessLevel({accessLevel:"TRUSTED_CONTEXTS"}),
  chrome.storage.session.setAccessLevel({accessLevel:"TRUSTED_CONTEXTS"})
]);
const bounded = async operation => {
  let timer;
  try {
    return await Promise.race([operation, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("API_OUTCOME_UNKNOWN")), 8000);
    })]);
  } finally { clearTimeout(timer); }
};
const commonIO = {
  exactTabs:async expected => (await chrome.tabs.query({url:"https://chatgpt.com/*"})).filter(t=>t.url===expected),
  pollAlarm:name => chrome.alarms.create(name,{periodInMinutes:1,delayInMinutes:1}),
  async reportStatus(s,project) {
    const a=s.automation; if(!a)return;
    const row=e=>({id:completionId(e)||e.id,status:e.status,code:e.code,outcome:e.outcome,intentAt:e.intentAt,receiptAt:e.receiptAt,receipt:e.receipt,pageAtPrepare:e.pageAtPrepare,epoch:e.epoch,report_sha256:e.report_sha256,member_count:e.members?.length});
    return feed({project_ref:project.project_ref,scope_id:project.scope_id}, {enabled:a.enabled,route:a.route,error:a.error,epoch:a.epoch,cursor:a.cursor,worker:workerInstance,observedAt:Date.now(),
      binding:s.binding?{tabId:s.binding.tabId,route:s.binding.route,documentId:s.binding.documentId}:null,
      deliveries:a.deliveries.slice(-32).map(row),legacy:s.events.map(row)});
  },
  async receipt(binding,request) {
    await chrome.tabs.get(binding.tabId).then(t=>{if(t.url!==binding.route)throw Error("TARGET_CHANGED_REBIND");});
    const results=await bounded(chrome.scripting.executeScript({target:{tabId:binding.tabId,documentIds:[binding.documentId]},world:"ISOLATED",func:observeReceipt,args:[{...request,route:binding.route}]}));
    if(results?.length!==1 || results[0].documentId!==binding.documentId || results[0].result?.ok!==true)throw Error("RECEIPT_UNAVAILABLE");
    return results[0].result;
  },
  async boot() {
    await trusted;
    let {boot} = await chrome.storage.session.get("boot");
    if (!boot) { boot = crypto.randomUUID(); await chrome.storage.session.set({boot}); }
    return boot;
  },
  async read(key) { return (await chrome.storage.local.get(key))[key]; },
  async write(key, value) { await chrome.storage.local.set({[key]:value}); },
  selectedTab:async () => (await chrome.tabs.query({active:true,currentWindow:true}))[0],
  tab:id => chrome.tabs.get(id),
  uuid:() => crypto.randomUUID(),
  now:() => Date.now(),
  clearAlarm:name => chrome.alarms.clear(name),
  alarm:(name, when) => chrome.alarms.create(name, {when}),
  async slotDiagnostic(target) {
    // Explicit read-only Inspect only; no binding fallback, page timers or send adapter.
    const results = await chrome.scripting.executeScript({
      target:{tabId:target.tabId,frameIds:[0]}, world:"ISOLATED", func:inspectAttachmentSlots,
      args:[{route:target.route}]
    });
    if (results?.length !== 1 || results[0].frameId !== 0 ||
        typeof results[0].documentId !== "string" || !results[0].documentId ||
        !results[0].result || Object.keys(results[0].result).sort().join(",") !== "ok,snapshot" ||
        results[0].result.ok !== true || !validSlotSnapshot(results[0].result.snapshot))
      throw new Error("SLOT_DIAGNOSTIC_RESULT_UNKNOWN");
    return {ok:true,snapshot:results[0].result.snapshot};
  },
  async page(binding, request) {
    const target = binding.documentId ? {tabId:binding.tabId,documentIds:[binding.documentId]} :
      {tabId:binding.tabId,frameIds:[0]};
    const results = await bounded(chrome.scripting.executeScript({
      target, world:"ISOLATED", func:domOperation,
      args:[{...request, project:binding.project, route:binding.route, generation:binding.generation, documentToken:binding.documentToken}]
    }));
    if (results?.length !== 1 || results[0].frameId !== 0 || !results[0].documentId ||
        binding.documentId && results[0].documentId !== binding.documentId ||
        !results[0].result || typeof results[0].result.ok !== "boolean") throw new Error("SCRIPT_RESULT_UNKNOWN");
    return {...results[0].result, documentId:results[0].documentId};
  }
};
const controller = new ProjectControllers({
  read:commonIO.read,write:commonIO.write,catalog:()=>feed({},undefined,true),
  forProject:p=>({...commonIO,
    feed:q=>feed({...q,project_ref:p.project_ref,scope_id:p.scope_id}),
    reportStatus:s=>commonIO.reportStatus(s,p),
    clearAlarm:async name=>name===POLL?false:commonIO.clearAlarm(name+":"+p.scope_id),
    alarm:(name,when)=>commonIO.alarm(name+":"+p.scope_id,when)
  })
},connection?.project_ref || null);
const actions = new Set(["status","bind","inspect","arm","retry","cancel","unbind","confirm","enable","disable","verify","close_delivery"]);
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("popup.html") || sender.tab)
    return false;
  if (!message || !actions.has(message.action) ||
      Object.keys(message).some(k => !["action","delayMs","id","project_ref"].includes(k))) {
    reply({ok:false,code:"INVALID_MESSAGE"}); return false;
  }
  (message.action==='status' && !message.project_ref ? controller.catalog(true).then(projects=>({projects})) : controller.run(message.project_ref,message.action,message)).then(
    result => reply({ok:true,...result}),
    error => reply({ok:false,code:/^[A-Z_]{1,80}$/.test(error?.message || "") ?
      error.message : "OPERATION_FAILED_OR_STATE_UNKNOWN_INSPECT_NO_RESEND"})
  );
  return true;
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === POLL) controller.tick().catch(() => {});
});
async function start() {
  await trusted;
  await chrome.alarms.create(POLL,{periodInMinutes:1,delayInMinutes:1});
  await controller.tick(true);
}
chrome.runtime.onStartup.addListener(() => { start().catch(() => {}); });
chrome.runtime.onInstalled.addListener(() => { start().catch(() => {}); });

}
