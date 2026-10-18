const $ = id => document.getElementById(id);
let busy = false;
let cancelId;
let retryable = false;
let confirmed;
// Only known pre-publication refusals prove this operation did not set a receiver.
// Other failures can follow a durable write, including an unacknowledged enable.
const refusals=new Set(['SELECT_PROJECT','INVALID_DELAY','INELIGIBLE_CHAT','INVALID_MESSAGE',
  'RECIPIENT_SELECTION_CHANGED','RECIPIENT_SWITCH_REAL_UNKNOWN','RECIPIENT_SWITCH_SYNTHETIC_UNKNOWN',
  'RECIPIENT_SWITCH_REAL_FROZEN','PENDING_OTHER_CHAT_DISABLE_AND_RESOLVE','TARGET_NOT_UNIQUE_OR_OPEN',
  'PROJECT_UNAVAILABLE_HISTORY_RETAINED','LEGACY_EXPLICIT_REBIND_REQUIRED','STALE_STATE_NO_ATTEMPT']);
async function bounded(operation, ms, code) {
  let timer;
  try {
    return await Promise.race([operation,new Promise((_,reject)=>{
      timer=setTimeout(()=>reject(Error(code)),ms);
    })]);
  } finally {clearTimeout(timer);}
}
function hint(code) {
  if (!code) return "";
  if (code === "RECIPIENT_SWITCH_REAL_UNKNOWN" || code === "RECIPIENT_SWITCH_SYNTHETIC_UNKNOWN" || /PENDING_OTHER_CHAT/.test(code))
    return "本次切换未完成；旧提醒不会因此迁移或重发，请重新读取持久状态。";
  if (code === "RECIPIENT_SWITCH_REAL_FROZEN") return "待处理通知缺少可核对的原 Chat 归属，不能安全迁移；本次切换未完成，请重新读取状态，不要清除去重数据或重发。";
  if (code === "RECIPIENT_SELECTION_CHANGED") return "当前标签或 Chat 已变化；未确认切换，请重新核对接收 Chat。";
  if (/BUSY|RECENT_EDIT|IME_ACTIVE/.test(code)) return "页面正在回答或编辑，通知会等待。";
  if (/ATTACHMENT|UPLOAD/.test(code)) return "页面含附件或上传尚未完成，通知会等待；不会替你清理。";
  if (/DRAFT/.test(code)) return "草稿正在变化，通知仍在等待；请结束编辑后再查看接收 Chat。";
  if (code === "PENDING_QUEUE_FULL") return "待处理提醒已达上限；等待或处理接收 Chat 中的现有提醒后继续接收。";
  if (code === "SELECT_PROJECT") return "请先选择本地项目。";
  if (/TARGET_NOT_UNIQUE/.test(code)) return "请只保留一个接收 Chat 的普通标签页。";
  if (/INELIGIBLE_CHAT|REBIND|TARGET_CHANGED/.test(code)) return "请打开准确的普通 Chat，再明确绑定；不会重发已尝试的通知。";
  if (/FEED|CONNECTION|OFFLINE/.test(code)) return "请检查本机 Bridge 连接，再重新打开查看状态。";
  if (/UNAVAILABLE_HISTORY|SELECT_PROJECT|PROJECT_UNAVAILABLE/.test(code)) return "项目暂不可用，请检查 Bridge 登记；待处理通知仍保留。";
  return "操作未确认，请展开诊断核对；不要重复发送。";
}
const unfinished = e => e && ['queued','waiting'].includes(e.status) &&
  !['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode'].some(k=>Object.hasOwn(e,k));
function waitingHint(a) {
  if(!a?.enabled)return '';
  const rows=(a.deliveries || []).filter(e=>unfinished(e) && e.status==='waiting' && e.route===a.route);
  const failed=rows.find(e=>['DRAFT_CHOICE_UNCONFIRMED','DRAFT_CHOICE_UNAVAILABLE'].includes(e.code));
  if(failed)return '接收 Chat 中的选择提示尚未确认显示，通知仍在等待；扩展会继续检查。';
  if(rows.some(e=>e.code==='DRAFT_CHOICE_PENDING'))return '请在接收 Chat 中选择“追加到输入框末尾”或“忽略”；不会自动发送草稿。';
  if(rows.some(e=>e.code==='DRAFT_PRESENT'))return '接收 Chat 中已有草稿，通知仍在等待；不会替换或发送草稿。';
  return rows.length?hint(rows[0].code):'';
}
function render(s, selectedTab) {
  const a=s.automation, deliveries=a?.deliveries || [], events=s.events || [];
  const destination=a?.route || s.binding?.route;
  $("destination").textContent=!destination?"接收 Chat：尚未绑定":
    !selectedTab?"接收 Chat：已保存（当前标签未核对）":
    selectedTab.url===destination?"接收 Chat：当前 Chat":"接收 Chat：另一个已绑定 Chat";
  $("automatic-status").textContent=a?.enabled?"自动通知已启用":"自动通知已停用";
  $("feedback").textContent=a?.error?hint(a.error):waitingHint(a);
  const e=events.at(-1);
  cancelId=['queued','paused','attempted_unknown'].includes(e?.status)?e.id:undefined;
  retryable=['queued','paused'].includes(e?.status);
  $("delay").value=String(a?.delayMs ?? 0);
  const lines=[];
  if(a?.error)lines.push('等待 / 错误码：'+a.error);
  if(s.inspection)lines.push('检查：'+s.inspection);
  for(const item of [...deliveries.filter(unfinished),...events.filter(e=>['queued','paused'].includes(e.status))])lines.push(
    [item.batch_ref || item.work_ref || item.id,item.status,item.code].filter(Boolean).join(' · '));
  if(s.slotDiagnostic) {
    const d=s.slotDiagnostic;
    lines.push('附件槽：仅当前结构，不代表失败时快照；容器数 '+d.bodyCount+(d.bodiesTruncated?'（截断）':''));
    for(const b of d.bodies)for(const slot of b.slots)
      lines.push('槽 '+slot.tag+'；子节点 '+slot.childCount+'；显示 '+slot.display+' / '+slot.visibility+(slot.childrenTruncated?'（截断）':''));
  }
  $("status").textContent=lines.join('\n') || '暂无通知记录。';
}
function controls() {
  $("project").disabled=busy;
  for(const id of ["enable","disable"])$(id).disabled=busy || !$("project").value;
  $("retry").disabled=busy || !$("project").value || !retryable;
  $("cancel").disabled=busy || !$("project").value || !cancelId;
}
function unselected() {
  cancelId=undefined;retryable=false;
  $("destination").textContent=$("project").value?'接收 Chat：当前项目尚未读取状态':'接收 Chat：尚未选择项目';
  $("automatic-status").textContent=$("project").value?'当前项目尚未读取状态。':'请选择本地项目读取状态。';
  $("status").textContent='';$("feedback").textContent='';
}
async function act(action, args={}) {
  if (busy) return;
  const ref=$("project").value;
  if(action!=="status" && !ref) {
    $("feedback").textContent='请选择本地项目。';controls();return;
  }
  const previous=confirmed?.ref===ref?confirmed:undefined;
  if(!previous)unselected();
  busy=true;controls();
  $("status").textContent='读取 / 操作中…'+(previous?'\n'+previous.diagnostics:'');
  let refused=false,selectOnlyProject;
  try {
    // Longer than the normal catalog/feed/bind path. This bounds UI waiting only:
    // the worker may still finish; never cancel, roll back or retry its operation.
    const response=await bounded(chrome.runtime.sendMessage({action,...args,...(ref?{project_ref:ref}:{})}),
      60000,'MESSAGE_RESPONSE_TIMEOUT_UNKNOWN');
    if(!response?.ok) {
      refused=refusals.has(response?.code);
      throw Error(response?.code || "MESSAGE_RESPONSE_UNKNOWN");
    }
    let selectedTab;
    if(ref && response.state)try {
      selectedTab=(await bounded(chrome.tabs?.query({active:true,currentWindow:true}),500,'TAB_PRESENTATION_TIMEOUT'))?.[0];
    }catch { /* Presentation only; render the acknowledged saved state without a tab comparison. */ }
    // Do not show a late result under another project selection.
    if($("project").value!==ref)return;
    if(ref && (!response.state || response.selected && response.selected!==ref))throw Error('MESSAGE_RESPONSE_UNKNOWN');
    $("project").replaceChildren(new Option("选择本地项目", ""));
    for(const p of response.projects || [])$("project").add(new Option(p.project_ref+' — '+p.root+(p.available===false?'（暂不可用）':''),p.project_ref));
    $("project").value=ref;
    if(ref) {
      render(response.state,selectedTab);
      confirmed={ref,destination:$("destination").textContent,automaticStatus:$("automatic-status").textContent,
        diagnostics:$("status").textContent};
    }
    else {
      unselected();
      const available=(response.projects || []).filter(p=>p.available===true);
      if(available.length===1)selectOnlyProject=available[0].project_ref;
      else $("feedback").textContent=available.length?'请选择本地项目。':
        '未读取到可用项目；请检查本机 Bridge 连接和项目登记后重新打开查看。';
    }
  } catch(error) {
    if($("project").value!==ref)return;
    const code=/^[A-Z_]{1,80}$/.test(error?.message || "")?error.message:"MESSAGE_API_UNAVAILABLE_OR_UNKNOWN";
    if(refused) {
      $("destination").textContent=previous?'接收 Chat（上次确认）：'+previous.destination.replace(/^接收 Chat：/,''):
        '接收 Chat：尚未读取到已确认状态';
      $("automatic-status").textContent=(previous?'上次确认：'+previous.automaticStatus+'；':'')+'本次操作未完成';
      $("feedback").textContent=hint(code);
    } else {
      $("destination").textContent='接收 Chat：本次无法确认，请重新读取持久状态';
      $("automatic-status").textContent=action==='status'?'状态读取未完成':'本次操作结果未知';
      $("feedback").textContent='请重新选择项目或重新打开弹窗读取持久状态；不自动重试，也不要重复发送。';
    }
    $("status").textContent=code+'：不自动重试。'+(previous?'\n上次确认的诊断：\n'+previous.diagnostics:'');
  } finally {
    busy=false;
    $("automatic").checked=false;
    if($("project").value!==ref)unselected();
    controls();
  }
  if(selectOnlyProject) {
    $("project").value=selectOnlyProject;
    await act('status'); // One read for the only available project; never enable/bind/send.
  }
}
for(const action of ["bind","inspect","retry","unbind"])$(action).addEventListener("click",()=>act(action));
$("cancel").addEventListener("click",()=>act("cancel",{id:cancelId}));
$("enable").addEventListener("click",()=>{
  if(!$("project").value || $("automatic").checked)act("enable",{delayMs:Number($("delay").value)});
  else $("feedback").textContent='请先勾选自动发送授权。';
});
for(const action of ["disable"])$(action).addEventListener("click",()=>act(action));
$("project").addEventListener("change",()=>{
  if(confirmed?.ref!==$("project").value) {confirmed=undefined;unselected();}
  $("automatic").checked=false;controls();act("status");
});
act("status");
