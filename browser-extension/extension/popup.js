import {notice} from "./policy.js";
const $ = id => document.getElementById(id);
const example = "test-00000000-0000-0000-0000-000000000000";
let busy = false;
let cancelId;
function hint(code) {
  if (!code) return "";
  if (/BUSY|RECENT_EDIT|IME_ACTIVE/.test(code)) return "页面正在回答或编辑，通知会等待。";
  if (/DRAFT|ATTACHMENT|UPLOAD/.test(code)) return "请完成或移走草稿、附件；通知不会替你清理。";
  if (code === "SELECT_PROJECT") return "请先选择本地项目。";
  if (/TARGET_NOT_UNIQUE/.test(code)) return "请只保留一个接收 Chat 的普通标签页。";
  if (/PENDING_OTHER_CHAT/.test(code)) return "原 Chat 尚有未结束通知；请先停用并在诊断中核对。";
  if (/INELIGIBLE_CHAT|REBIND|TARGET_CHANGED/.test(code)) return "请打开准确的普通 Chat，再明确绑定；旧历史会保留。";
  if (/FEED|CONNECTION|OFFLINE/.test(code)) return "请检查本机 Bridge 连接，再重新打开查看状态。";
  if (/UNAVAILABLE_HISTORY|SELECT_PROJECT|PROJECT_UNAVAILABLE/.test(code)) return "项目暂不可用，请检查 Bridge 登记；历史仍保留。";
  return "操作未确认，请展开诊断核对；不要重复发送。";
}
function render(s, selectedTab) {
  const a=s.automation, deliveries=a?.deliveries || [], events=s.events || [];
  const destination=a?.route || s.binding?.route;
  $("destination").textContent=!destination?"接收 Chat：尚未绑定":
    !selectedTab?"接收 Chat：已保存（当前标签未核对）":
    selectedTab.url===destination?"接收 Chat：当前 Chat":"接收 Chat：另一个已绑定 Chat";
  $("automatic-status").textContent=a?.enabled?"自动通知已启用":"自动通知已停用";
  const unknown=[...deliveries,...events].filter(e=>e.status==='attempted_unknown').length;
  $("feedback").textContent=unknown?"有结果未知的通知；请展开诊断核对收件，不重发。":hint(a?.error);
  const e=events.at(-1);cancelId=e?.id;
  $("delay").value=String(a?.delayMs ?? 0);
  const lines=[];
  if(a?.error)lines.push('等待 / 错误码：'+a.error);
  if(s.inspection)lines.push('检查：'+s.inspection);
  for(const item of [...deliveries,...events])lines.push(
    [item.batch_ref || item.work_ref || item.id,item.status,item.code,item.outcome,
      item.receipt?'收件匹配数：'+item.receipt.notices:''].filter(Boolean).join(' · '));
  if(s.slotDiagnostic) {
    const d=s.slotDiagnostic;
    lines.push('附件槽：仅当前结构，不代表失败时快照；容器数 '+d.bodyCount+(d.bodiesTruncated?'（截断）':''));
    for(const b of d.bodies)for(const slot of b.slots)
      lines.push('槽 '+slot.tag+'；子节点 '+slot.childCount+'；显示 '+slot.display+' / '+slot.visibility+(slot.childrenTruncated?'（截断）':''));
  }
  $("status").textContent=lines.join('\n') || '暂无通知记录。';
  $("preview").textContent=notice(e?.id || example)+(e?'':'\n（占位编号；实际编号由扩展生成）');
}
async function act(action, args={}) {
  if (busy) return;
  const ref=$("project").value;
  busy=true;$("project").disabled=true;$("arm").disabled=true;
  $("automatic-status").textContent='读取 / 操作中…';
  $("destination").textContent='接收 Chat：待核对';$("feedback").textContent='';
  $("status").textContent='';cancelId=undefined;
  try {
    if(action!=="status" && !ref)throw Error("SELECT_PROJECT");
    const response=await chrome.runtime.sendMessage({action,...args,...(ref?{project_ref:ref}:{})});
    if(!response?.ok)throw Error(response?.code || "MESSAGE_RESPONSE_UNKNOWN");
    let selectedTab;
    try {selectedTab=(await chrome.tabs?.query({active:true,currentWindow:true}))?.[0];}catch { /* Presentation only; no binding fallback. */ }
    // Do not show a late result under another project selection.
    if($("project").value!==ref)return;
    $("project").replaceChildren(new Option("选择本地项目", ""));
    for(const p of response.projects || [])$("project").add(new Option(p.project_ref+' — '+p.root+(p.available===false?'（暂不可用）':''),p.project_ref));
    $("project").value=response.selected || ref;
    if(response.state)render(response.state,selectedTab);
    else {
      $("destination").textContent='接收 Chat：尚未选择项目';
      $("automatic-status").textContent='请选择本地项目查看状态。';
    }
  } catch(error) {
    const code=/^[A-Z_]{1,80}$/.test(error?.message || "")?error.message:"MESSAGE_API_UNAVAILABLE_OR_UNKNOWN";
    $("automatic-status").textContent='状态未确认';$("feedback").textContent=hint(code);
    $("status").textContent=code+'：不自动重试。重新打开查看持久状态；尝试过的事件禁止重发。';
  } finally {
    busy=false;$("project").disabled=false;$("armed").checked=false;$("arm").disabled=true;
    $("automatic").checked=false;
  }
}
$("armed").addEventListener("change",()=>{$("arm").disabled=busy || !$("armed").checked;});
for(const action of ["bind","inspect","retry","unbind"])$(action).addEventListener("click",()=>act(action));
$("cancel").addEventListener("click",()=>act("cancel",{id:cancelId}));
$("arm").addEventListener("click",()=>{if($("armed").checked)act("arm",{delayMs:Number($("delay").value)});});
$("confirm").addEventListener("click",()=>act("confirm",{id:$("marker").value.trim()}));
$("enable").addEventListener("click",()=>{
  if($("automatic").checked)act("enable",{delayMs:Number($("delay").value)});
  else $("feedback").textContent='请先勾选自动发送授权。';
});
for(const action of ["disable","verify"])$(action).addEventListener("click",()=>act(action));
$("close_delivery").addEventListener("click",()=>act("close_delivery",{id:$("work-marker").value.trim()}));
$("project").addEventListener("change",()=>act("status"));
act("status");
