import {notice} from "./policy.js";
const $ = id => document.getElementById(id);
const example = "test-00000000-0000-0000-0000-000000000000";
let busy = false;
let cancelId;
function render(s) {
  const e = s.events.at(-1);
  $("automatic-status").textContent=s.automation?.enabled?"自动通知已启用；状态和等待原因见下方。":"自动通知未启用。";
  cancelId = e?.id; // Pin Cancel to the event actually displayed, never a later trial.
  $("status").textContent = JSON.stringify({
    binding:s.binding ? {project:s.binding.project,tab:s.binding.tabId,chat:s.binding.route,generation:s.binding.generation} : null,
    inspection:s.inspection, slotDiagnostic:s.slotDiagnostic,
    automation:s.automation,
    history:s.events.map(x => ({id:x.id,status:x.status,code:x.code,route:x.route,intentAt:x.intentAt,outcome:x.outcome}))
  }, null, 2);
  $("preview").textContent = notice(e?.id || example) + (e ? "" : "\n（预览占位编号；实际编号由扩展生成）");
}
async function act(action, args={}) {
  if (busy) return;
  busy = true; $("arm").disabled = true;
  try {
    const ref = $("project").value;
    if(action!=="status" && !ref)throw Error("SELECT_PROJECT");
    const response = await chrome.runtime.sendMessage({action,...args,...(ref?{project_ref:ref}:{})});
    if (!response?.ok) throw new Error(response?.code || "MESSAGE_RESPONSE_UNKNOWN");
    $("project").replaceChildren(new Option("选择已授权本地项目", ""));
    for(const p of response.projects || [])$("project").add(new Option(p.root+" — "+p.project_ref+(p.available===false?"（失效；历史保留）":""),p.project_ref));
    $("project").value=response.selected || ref;
    if(response.state)render(response.state);
  } catch (error) {
    const code = /^[A-Z_]{1,80}$/.test(error?.message || "") ? error.message : "MESSAGE_API_UNAVAILABLE_OR_UNKNOWN";
    $("status").textContent = code + "：不自动重试。重新打开查看持久状态；尝试过的事件禁止重发。";
  } finally {
    busy = false; $("armed").checked = false; $("arm").disabled = true;
  }
}
$("armed").addEventListener("change", () => { $("arm").disabled = busy || !$("armed").checked; });
for (const action of ["bind","inspect","retry","unbind"])
  $(action).addEventListener("click", () => act(action));
$("cancel").addEventListener("click", () => act("cancel", {id:cancelId}));
$("arm").addEventListener("click", () => {
  if ($("armed").checked) act("arm", {delayMs:Number($("delay").value)});
});
$("confirm").addEventListener("click", () => act("confirm", {id:$("marker").value.trim()}));
$("enable").addEventListener("click",()=> {if($("automatic").checked)act("enable",{delayMs:Number($("delay").value)});});
for(const action of ["disable","verify"])$(action).addEventListener("click",()=>act(action));
$("close_delivery").addEventListener("click",()=>act("close_delivery",{id:$("work-marker").value.trim()}));
$("project").addEventListener("change", () => act("status"));
act("status");
