const $ = id => document.getElementById(id);
const LANGUAGE_KEY = "bridgeNotificationLanguage";
const TEXT = {
  zh: {
    popupTitle: "Bridge 完成通知",
    heading: "Bridge 完成通知",
    languageLabel: "提醒语言 / Notification language",
    languageNote: "仅影响之后的新提醒；不会重发或迁移已有通知。",
    languageSaved: "提醒语言已保存。之后的新提醒将使用中文；已有通知不会重发。",
    languageSaveFailed: "提醒语言保存失败；仍使用中文。",
    projectLabel: "本地项目 ",
    selectProjectOption: "选择项目",
    selectLocalProjectOption: "选择本地项目",
    automaticLabel: "允许向当前 Chat 自动发送完成提醒；明确切换时，本项目确定从未尝试发送的积压提醒可跟随；已尝试或已冻结的提醒不再迁移或重放",
    enable: "设为接收 Chat 并启用",
    disable: "停用",
    diagnosticsSummary: "诊断与安全恢复",
    diagnosticsHelp: "操作仅作用于所选项目。本地调用发送后即结束，不核对后端送达；结果未知时也不重发。这里只显示当前待处理通知。",
    inspect: "检查页面，不填字、不发送",
    bind: "仅绑定诊断页面（不改自动接收 Chat）",
    unbind: "解除绑定并停用",
    delayLabel: "发送延迟",
    delay0: "不额外延迟",
    delay60000: "约 60 秒后尝试",
    legacySummary: "旧合成试验恢复",
    legacyHelp: "不建立新试验、不接真实工作。仅处理已有旧记录；结果未知时不重发，不清除记录。",
    retry: "仅重试未尝试的旧试验",
    cancel: "取消未尝试或结束已证实点击前中止的旧试验",
    unavailableSuffix: "（暂不可用）",
    destNoProject: "接收 Chat：尚未选择项目",
    destUnread: "接收 Chat：当前项目尚未读取状态",
    destNotBound: "接收 Chat：尚未绑定",
    destSaved: "接收 Chat：已保存（当前标签未核对）",
    destCurrent: "接收 Chat：当前 Chat",
    destOther: "接收 Chat：另一个已绑定 Chat",
    destLastConfirmed: "接收 Chat（上次确认）：",
    destNoConfirmed: "接收 Chat：尚未读取到已确认状态",
    destUnconfirmed: "接收 Chat：本次无法确认，请重新读取持久状态",
    autoEnabled: "自动通知已启用",
    autoDisabled: "自动通知已停用",
    statusUnread: "当前项目尚未读取状态。",
    statusSelectProject: "请选择本地项目读取状态。",
    lastConfirmedPrefix: "上次确认：",
    opNotCompleted: "本次操作未完成",
    opNotCompletedSuffix: "；本次操作未完成",
    statusReadNotCompleted: "状态读取未完成",
    operationResultUnknown: "本次操作结果未知",
    reopenToReadState: "请重新选择项目或重新打开弹窗读取持久状态；不自动重试，也不要重复发送。",
    noAutoRetry: "：不自动重试。",
    lastConfirmedDiagnostics: "\n上次确认的诊断：\n",
    readingOperating: "读取 / 操作中…",
    selectProject: "请选择本地项目。",
    consentRequired: "请先勾选自动发送授权。",
    noAvailableProjects: "未读取到可用项目；请检查本机 Bridge 连接和项目登记后重新打开查看。",
    statusEmpty: "暂无通知记录。",
    waitingErrorCode: "等待 / 错误码：",
    inspection: "检查：",
    attachmentSlots: "附件槽：仅当前结构，不代表失败时快照；容器数 ",
    truncated: "（截断）",
    slot: "槽 ",
    childNodes: "；子节点 ",
    display: "；显示 ",
    visibilitySep: " / ",
    hintSwitchUnknown: "本次切换未完成；旧提醒不会因此迁移或重发，请重新读取持久状态。",
    hintFrozen: "待处理通知缺少可核对的原 Chat 归属，不能安全迁移；本次切换未完成，请重新读取状态，不要清除去重数据或重发。",
    hintSelectionChanged: "当前标签或 Chat 已变化；未确认切换，请重新核对接收 Chat。",
    hintBusy: "页面正在回答或编辑，通知会等待。",
    hintAttachment: "页面含附件或上传尚未完成，通知会等待；不会替你清理。",
    hintDraft: "草稿正在变化，通知仍在等待；请结束编辑后再查看接收 Chat。",
    hintQueueFull: "待处理提醒已达上限；等待或处理接收 Chat 中的现有提醒后继续接收。",
    hintSelectProject: "请先选择本地项目。",
    hintTargetUnique: "请只保留一个接收 Chat 的普通标签页。",
    hintBind: "请打开准确的普通 Chat，再明确绑定；不会重发已尝试的通知。",
    hintConnection: "请检查本机 Bridge 连接，再重新打开查看状态。",
    hintUnavailable: "项目暂不可用，请检查 Bridge 登记；待处理通知仍保留。",
    hintUnknown: "操作未确认，请展开诊断核对；不要重复发送。",
    waitChoiceUnconfirmed: "接收 Chat 中的选择提示尚未确认显示，通知仍在等待；扩展会继续检查。",
    waitChoicePending: "请在接收 Chat 中选择“追加到输入框末尾”或“忽略”；不会自动发送草稿。",
    waitDraftPresent: "接收 Chat 中已有草稿，通知仍在等待；不会替换或发送草稿。"
  },
  en: {
    popupTitle: "Bridge completion notifications",
    heading: "Bridge completion notifications",
    languageLabel: "提醒语言 / Notification language",
    languageNote: "Applies to new reminders only; existing notifications are not resent or migrated.",
    languageSaved: "Reminder language saved. New reminders will use English; existing notifications are not resent.",
    languageSaveFailed: "Could not save the reminder language; it remains English.",
    projectLabel: "Local project ",
    selectProjectOption: "Select a project",
    selectLocalProjectOption: "Select a local project",
    automaticLabel: "Allow automatic sending of completion reminders to the current Chat; when explicitly switching, backlog reminders for this project that have definitely never been attempted may follow; reminders already attempted or frozen are not migrated or replayed",
    enable: "Set as receiving Chat and enable",
    disable: "Disable",
    diagnosticsSummary: "Diagnostics and safe recovery",
    diagnosticsHelp: "Actions apply only to the selected project. A local send call ends immediately and does not verify backend delivery; unknown outcomes are not resent. Only current pending notifications are shown here.",
    inspect: "Inspect page without typing or sending",
    bind: "Bind diagnostic page only (does not change the automatic receiving Chat)",
    unbind: "Unbind and disable",
    delayLabel: "Send delay",
    delay0: "No extra delay",
    delay60000: "Try after about 60 seconds",
    legacySummary: "Legacy synthetic test recovery",
    legacyHelp: "Creates no new tests and connects no real work. Only existing legacy records are handled; unknown outcomes are not resent, and records are not cleared.",
    retry: "Retry only unattempted legacy tests",
    cancel: "Cancel unattempted legacy tests, or close ones proven stopped before click",
    unavailableSuffix: " (temporarily unavailable)",
    destNoProject: "Receiving Chat: no project selected",
    destUnread: "Receiving Chat: status not read for this project",
    destNotBound: "Receiving Chat: not bound",
    destSaved: "Receiving Chat: saved (current tab not checked)",
    destCurrent: "Receiving Chat: current Chat",
    destOther: "Receiving Chat: another bound Chat",
    destLastConfirmed: "Receiving Chat (last confirmed): ",
    destNoConfirmed: "Receiving Chat: no confirmed status has been read",
    destUnconfirmed: "Receiving Chat: this operation could not be confirmed; re-read the persisted state",
    autoEnabled: "Automatic notifications enabled",
    autoDisabled: "Automatic notifications disabled",
    statusUnread: "Status has not been read for this project.",
    statusSelectProject: "Select a local project to read status.",
    lastConfirmedPrefix: "Last confirmed: ",
    opNotCompleted: "This operation did not complete",
    opNotCompletedSuffix: "; this operation did not complete",
    statusReadNotCompleted: "Status read did not complete",
    operationResultUnknown: "The result of this operation is unknown",
    reopenToReadState: "Select the project again or reopen the popup to read the persisted state; do not retry automatically or resend.",
    noAutoRetry: ": no automatic retry.",
    lastConfirmedDiagnostics: "\nLast confirmed diagnostics:\n",
    readingOperating: "Reading / operating…",
    selectProject: "Select a local project.",
    consentRequired: "Select the automatic-send authorization first.",
    noAvailableProjects: "No available projects were read. Check the local Bridge connection and project registration, then reopen this popup.",
    statusEmpty: "No notification records.",
    waitingErrorCode: "Waiting / error code: ",
    inspection: "Inspection: ",
    attachmentSlots: "Attachment slots: current structure only, not a failure-time snapshot; container count ",
    truncated: " (truncated)",
    slot: "Slot ",
    childNodes: "; child nodes ",
    display: "; display ",
    visibilitySep: " / ",
    hintSwitchUnknown: "This switch did not complete. Old reminders will not be migrated or resent because of it; reload the persisted state.",
    hintFrozen: "Pending notifications lack a verifiable original Chat binding and cannot be migrated safely. This switch did not complete; reload the state, and do not clear deduplication data or resend.",
    hintSelectionChanged: "The current tab or Chat has changed; the switch was not confirmed. Recheck the receiving Chat.",
    hintBusy: "The page is answering or being edited; the notification will wait.",
    hintAttachment: "The page has attachments or an unfinished upload; the notification will wait and will not clean them up for you.",
    hintDraft: "The draft is changing; the notification is still waiting. Finish editing, then check the receiving Chat.",
    hintQueueFull: "The pending reminder limit has been reached. Wait for or handle existing reminders in the receiving Chat before accepting more.",
    hintSelectProject: "Select a local project first.",
    hintTargetUnique: "Keep exactly one ordinary tab open for the receiving Chat.",
    hintBind: "Open the exact ordinary Chat and bind it explicitly; attempted notifications will not be resent.",
    hintConnection: "Check the local Bridge connection, then reopen this popup to view status.",
    hintUnavailable: "The project is temporarily unavailable. Check the Bridge registration; pending notifications are retained.",
    hintUnknown: "The operation was not confirmed. Expand diagnostics to check; do not resend.",
    waitChoiceUnconfirmed: "The choice prompt in the receiving Chat has not been confirmed visible; the notification is still waiting and the extension will keep checking.",
    waitChoicePending: "Choose “Append to the end of the input” or “Ignore” in the receiving Chat; drafts are never sent automatically.",
    waitDraftPresent: "The receiving Chat already contains a draft; the notification is still waiting and will not replace or send the draft."
  }
};
const STATIC_IDS = {
  "popup-title": "popupTitle",
  heading: "heading",
  "language-label": "languageLabel",
  "language-note": "languageNote",
  "project-label": "projectLabel",
  "automatic-label": "automaticLabel",
  enable: "enable",
  disable: "disable",
  "diagnostics-summary": "diagnosticsSummary",
  inspect: "inspect",
  bind: "bind",
  unbind: "unbind",
  "delay-label": "delayLabel",
  "delay-0": "delay0",
  "delay-60000": "delay60000",
  "legacy-summary": "legacySummary",
  retry: "retry",
  cancel: "cancel"
};
let language = "zh";
let languageTouched = false;
let languageSaving = false;
let shownState;
let shownTab;
let shownRef;
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
const t = key => TEXT[language][key];
const normalizeLanguage = value => value === "en" ? "en" : "zh";
const stripDestination = value => String(value || "").replace(/^(?:接收 Chat：|Receiving Chat: )/, "");
function applyStatic() {
  for(const [id,key] of Object.entries(STATIC_IDS)) {
    const element=$(id);
    if(element)element.textContent=t(key);
  }
  if(document.querySelectorAll)for(const element of document.querySelectorAll("[data-i18n]")) {
    const key=element.getAttribute?.("data-i18n");
    if(key && TEXT[language][key])element.textContent=t(key);
  }
  if(document.documentElement)document.documentElement.lang=language==="en"?"en":"zh-CN";
  const project=$("project");
  if(project?.options?.[0])project.options[0].textContent=t("selectProjectOption");
}
function applyLanguage(next) {
  language=normalizeLanguage(next);
  const select=$("language");
  if(select)select.value=language;
  applyStatic();
  if(shownState && shownRef && $("project").value===shownRef) {
    render(shownState,shownTab);
    if(confirmed)confirmed={...confirmed,destination:$("destination").textContent,
      automaticStatus:$("automatic-status").textContent,diagnostics:$("status").textContent};
  } else {
    $("destination").textContent=$("project").value?t("destUnread"):t("destNoProject");
    $("automatic-status").textContent=$("project").value?t("statusUnread"):t("statusSelectProject");
  }
}
async function loadLanguage() {
  try {
    const storage=typeof chrome!=="undefined"?chrome.storage?.local:undefined;
    if(!storage?.get)return;
    const stored=(await storage.get(LANGUAGE_KEY))?.[LANGUAGE_KEY];
    if(languageTouched)return;
    const next=normalizeLanguage(stored);
    if(next!==language)applyLanguage(next);
  } catch { /* Missing storage keeps the compatible Chinese default. */ }
}
async function chooseLanguage(next) {
  next=normalizeLanguage(next);
  const select=$("language");
  if(next===language) {if(select)select.value=language;return;}
  if(languageSaving) {if(select)select.value=language;return;}
  const previous=language;
  languageTouched=true;
  languageSaving=true;
  if(select)select.disabled=true;
  let saved=false;
  try {
    const storage=typeof chrome!=="undefined"?chrome.storage?.local:undefined;
    if(!storage?.set)throw Error("STORAGE_UNAVAILABLE");
    await storage.set({[LANGUAGE_KEY]:next});
    saved=true;
  } catch { /* Keep the previous language and report the failed save. */ }
  try {
    if(saved) {
      applyLanguage(next);
      $("language-status").textContent=t("languageSaved");
    } else {
      if(select)select.value=previous;
      applyLanguage(previous);
      $("language-status").textContent=t("languageSaveFailed");
    }
  } finally {
    languageSaving=false;
    if(select)select.disabled=false;
  }
}
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
    return t("hintSwitchUnknown");
  if (code === "RECIPIENT_SWITCH_REAL_FROZEN") return t("hintFrozen");
  if (code === "RECIPIENT_SELECTION_CHANGED") return t("hintSelectionChanged");
  if (/BUSY|RECENT_EDIT|IME_ACTIVE/.test(code)) return t("hintBusy");
  if (/ATTACHMENT|UPLOAD/.test(code)) return t("hintAttachment");
  if (/DRAFT/.test(code)) return t("hintDraft");
  if (code === "PENDING_QUEUE_FULL") return t("hintQueueFull");
  if (code === "SELECT_PROJECT") return t("hintSelectProject");
  if (/TARGET_NOT_UNIQUE/.test(code)) return t("hintTargetUnique");
  if (/INELIGIBLE_CHAT|REBIND|TARGET_CHANGED/.test(code)) return t("hintBind");
  if (/FEED|CONNECTION|OFFLINE/.test(code)) return t("hintConnection");
  if (/UNAVAILABLE_HISTORY|SELECT_PROJECT|PROJECT_UNAVAILABLE/.test(code)) return t("hintUnavailable");
  return t("hintUnknown");
}
const unfinished = e => e && ['queued','waiting'].includes(e.status) &&
  !['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode'].some(k=>Object.hasOwn(e,k));
function waitingHint(a) {
  if(!a?.enabled)return '';
  const rows=(a.deliveries || []).filter(e=>unfinished(e) && e.status==='waiting' && e.route===a.route);
  const failed=rows.find(e=>['DRAFT_CHOICE_UNCONFIRMED','DRAFT_CHOICE_UNAVAILABLE'].includes(e.code));
  if(failed)return t("waitChoiceUnconfirmed");
  if(rows.some(e=>e.code==='DRAFT_CHOICE_PENDING'))return t("waitChoicePending");
  if(rows.some(e=>e.code==='DRAFT_PRESENT'))return t("waitDraftPresent");
  return rows.length?hint(rows[0].code):'';
}
function render(s, selectedTab) {
  shownState=s;shownTab=selectedTab;shownRef=$("project").value;
  const a=s.automation, deliveries=a?.deliveries || [], events=s.events || [];
  const destination=a?.route || s.binding?.route;
  $("destination").textContent=!destination?t("destNotBound"):
    !selectedTab?t("destSaved"):
    selectedTab.url===destination?t("destCurrent"):t("destOther");
  $("automatic-status").textContent=a?.enabled?t("autoEnabled"):t("autoDisabled");
  $("feedback").textContent=a?.error?hint(a.error):waitingHint(a);
  const e=events.at(-1);
  cancelId=['queued','paused','attempted_unknown'].includes(e?.status)?e.id:undefined;
  retryable=['queued','paused'].includes(e?.status);
  $("delay").value=String(a?.delayMs ?? 0);
  const lines=[];
  if(a?.error)lines.push(t("waitingErrorCode")+a.error);
  if(s.inspection)lines.push(t("inspection")+s.inspection);
  for(const item of [...deliveries.filter(unfinished),...events.filter(e=>['queued','paused'].includes(e.status))])lines.push(
    [item.batch_ref || item.work_ref || item.id,item.status,item.code].filter(Boolean).join(' · '));
  if(s.slotDiagnostic) {
    const d=s.slotDiagnostic;
    lines.push(t("attachmentSlots")+d.bodyCount+(d.bodiesTruncated?t("truncated"):''));
    for(const b of d.bodies)for(const slot of b.slots)
      lines.push(t("slot")+slot.tag+t("childNodes")+slot.childCount+t("display")+slot.display+t("visibilitySep")+slot.visibility+(slot.childrenTruncated?t("truncated"):''));
  }
  $("status").textContent=lines.join('\n') || t("statusEmpty");
}
function controls() {
  $("project").disabled=busy;
  for(const id of ["enable","disable"])$(id).disabled=busy || !$("project").value;
  $("retry").disabled=busy || !$("project").value || !retryable;
  $("cancel").disabled=busy || !$("project").value || !cancelId;
}
function unselected() {
  shownState=undefined;shownTab=undefined;shownRef=undefined;
  cancelId=undefined;retryable=false;
  $("destination").textContent=$("project").value?t("destUnread"):t("destNoProject");
  $("automatic-status").textContent=$("project").value?t("statusUnread"):t("statusSelectProject");
  $("status").textContent='';$("feedback").textContent='';
}
async function act(action, args={}) {
  if (busy) return;
  const ref=$("project").value;
  if(action!=="status" && !ref) {
    $("feedback").textContent=t("selectProject");controls();return;
  }
  const previous=confirmed?.ref===ref?confirmed:undefined;
  if(!previous)unselected();
  busy=true;controls();
  $("status").textContent=t("readingOperating")+(previous?'\n'+previous.diagnostics:'');
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
    $("project").replaceChildren(new Option(t("selectLocalProjectOption"), ""));
    for(const p of response.projects || [])$("project").add(new Option(p.project_ref+' — '+p.root+(p.available===false?t("unavailableSuffix"):''),p.project_ref));
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
      else $("feedback").textContent=available.length?t("selectProject"):t("noAvailableProjects");
    }
  } catch(error) {
    if($("project").value!==ref)return;
    const code=/^[A-Z_]{1,80}$/.test(error?.message || "")?error.message:"MESSAGE_API_UNAVAILABLE_OR_UNKNOWN";
    if(refused) {
      $("destination").textContent=previous?t("destLastConfirmed")+stripDestination(previous.destination):
        t("destNoConfirmed");
      $("automatic-status").textContent=(previous?t("lastConfirmedPrefix")+previous.automaticStatus+t("opNotCompletedSuffix"):'')+t("opNotCompleted");
      $("feedback").textContent=hint(code);
    } else {
      $("destination").textContent=t("destUnconfirmed");
      $("automatic-status").textContent=action==='status'?t("statusReadNotCompleted"):t("operationResultUnknown");
      $("feedback").textContent=t("reopenToReadState");
    }
    $("status").textContent=code+t("noAutoRetry")+(previous?t("lastConfirmedDiagnostics")+previous.diagnostics:'');
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
  else $("feedback").textContent=t("consentRequired");
});
for(const action of ["disable"])$(action).addEventListener("click",()=>act(action));
$("project").addEventListener("change",()=>{
  if(confirmed?.ref!==$("project").value) {confirmed=undefined;unselected();}
  $("automatic").checked=false;controls();act("status");
});
$("language").addEventListener("change",()=>chooseLanguage($("language").value));
applyLanguage("zh");
loadLanguage();
act("status");
