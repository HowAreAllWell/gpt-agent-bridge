// Serialized into the ISOLATED world by chrome.scripting. No closure dependencies.
// Narrow observed ChatGPT DOM contract; unrecognized changes stop before Send.
export async function domOperation(request) {
  const project = request.project || 'gpt-agent-bridge';
  if(typeof project!=='string' || !/^[A-Za-z0-9_.-]{1,80}$/.test(project))return {ok:false,code:'INVALID_PROJECT'};
  const SLOT = project==='gpt-agent-bridge' ? '__bridgeSyntheticNoticeV1' : '__bridgeNoticeProject:'+project;
  const COMPOSER_SELECTOR = 'div[contenteditable="true"][role="textbox"][data-composer-markdown]';
  const fail = code => ({ok:false, code});
  const canonical = value => {
    try {
      const u = new URL(value);
      return u.origin === "https://chatgpt.com" && !u.username && !u.password && u.href === u.origin + u.pathname &&
        /^\/(?:g\/g-p-[0-9a-f]{32}-[a-z]+(?:-[a-z]+)*\/)?c\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(u.pathname) ?
        u.origin + u.pathname : null;
    } catch { return null; }
  };
  const visible = el => {
    const css = getComputedStyle(el);
    return el.getClientRects().length > 0 && css.display !== "none" && css.visibility !== "hidden";
  };
  const all = (root, selector) => [...root.querySelectorAll(selector)];
  const BODY_SELECTOR = "div[data-composer-body]";
  const FOOTER_SELECTOR = "div[data-composer-footer-responsive]";
  // These English labels are the supplied control contract, not locale guesses.
  const ADD_SELECTOR = 'button[type="button"][data-composer-navigation-target="add-context"][aria-expanded="false"][data-state="closed"]';
  const REASON_SELECTOR = 'button[type="button"][data-composer-navigation-target="reasoning"][data-codex-intelligence-trigger="true"][aria-haspopup="menu"][aria-expanded="false"][data-state="closed"]';
  const DICTATE_SELECTOR = 'button[type="button"][aria-label="Dictate"][aria-busy="false"]';
  const VOICE_SELECTOR = 'button[type="button"][aria-label="Start Voice"][data-state="closed"]';
  const SEND_SELECTOR = 'button[type="submit"][aria-label="Send"]';
  function structure() {
    if (navigator.onLine !== true) return fail("OFFLINE");
    if (all(document, 'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]').some(visible))
      return fail("DIALOG_OR_CHALLENGE");
    if (all(document, 'iframe, [role="alert"]').some(visible)) return fail("VISIBLE_FRAME_OR_ALERT");
    if (all(document, 'button[data-testid="stop-button"], button[type="button"][aria-label="Stop"]').some(visible))
      return fail("BUSY_STOP_PRESENT");
    // Observed Project Chat combines the user and assistant in one turn. During
    // thinking/tool waits its last turn has only "You said:"; a completed turn
    // exposes the assistant heading and final action bar. An absent Stop alone
    // is not completion evidence during a transient render.
    const conversations=all(document,'div[data-thread-find-target="conversation"][data-chatgpt-conversation-selection-target="true"]');
    if(conversations.length!==1 || !visible(conversations[0]))return fail("TURN_STRUCTURE_UNKNOWN");
    const turns=all(conversations[0],'[data-turn-key]');
    if(turns.length) {
      const last=turns.at(-1);
      if(!all(last,'h4.sr-only').some(h=>h.textContent==='ChatGPT said:') ||
        !all(last,'button[aria-label="Read aloud"]').some(visible) ||
        !all(last,'button[aria-label="More actions"]').some(visible))
        return fail("BUSY_TURN_UNSETTLED");
    }
    const editors = all(document, COMPOSER_SELECTOR);
    if (editors.length !== 1 || !visible(editors[0])) return fail("COMPOSER_UNKNOWN_OR_AMBIGUOUS");
    const editor = editors[0], bodies = all(document, "[data-composer-body]");
    if (bodies.length !== 1 || bodies[0].tagName !== "DIV" || !visible(bodies[0]) || editor.closest(BODY_SELECTOR) !== bodies[0])
      return fail("COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS");
    const body = bodies[0], footers = all(body, "[data-composer-footer-responsive]");
    if (footers.length !== 1 || footers[0].tagName !== "DIV" || !visible(footers[0]) || editor.closest(FOOTER_SELECTOR) !== footers[0])
      return fail("COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS");
    const footer = footers[0], owner = body.closest("form");
    if (editor.closest("form") !== owner || footer.closest("form") !== owner ||
        all(body, "form").length || owner && all(owner, COMPOSER_SELECTOR).length !== 1)
      return fail("FORM_OWNER_MISMATCH");
    if (body.getAttribute("aria-busy") === "true" || owner?.getAttribute("aria-busy") === "true" ||
        all(body, '[aria-busy="true"], [role="progressbar"], [data-testid="upload-progress"]').some(visible))
      return fail("BUSY_OR_UPLOAD");
    if (all(body, '[aria-expanded="true"], [data-state="open"]').length)
      return fail("OPEN_COMPOSER_CONTROL");
    const slots = all(body, "[data-composer-attachments]");
    if (slots.length !== 1 || slots[0].tagName !== "DIV" || slots[0].childNodes.length)
      return fail("ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY");
    if (all(body, 'input[type="file"]').some(el => el.files?.length) ||
        all(body, '[data-testid="attachment"], img, video, audio, canvas').some(visible))
      return fail("ATTACHMENT");
    const selectors = [ADD_SELECTOR, REASON_SELECTOR, DICTATE_SELECTOR];
    const auxiliary = selectors.map(s => all(footer, s));
    if (auxiliary.some(nodes => nodes.length !== 1))
      return fail("AUXILIARY_CONTROL_UNKNOWN_OR_AMBIGUOUS");
    const controls = auxiliary.map(nodes => nodes[0]);
    const voices = all(footer, VOICE_SELECTOR), sends = all(footer, SEND_SELECTOR);
    if (voices.length + sends.length !== 1) return fail("PRIMARY_UNKNOWN_OR_AMBIGUOUS");
    const primary = (voices[0] || sends[0]), kind = voices.length ? "voice" : "send";
    const known = [...controls, primary], buttons = all(body, "button");
    // Optional observed layout control, never a Send candidate. Recheck on every guard;
    // it may appear after our prefill and is deliberately not part of the lease identity.
    const layout = all(body, "[data-composer-expand-toggle]");
    if (body.getAttribute("data-composer-expand-toggle") !== null || layout.length > 1 || layout.some(el =>
        el.tagName !== "BUTTON" || el.getAttribute("type") !== "button" ||
        el.getAttribute("aria-label") !== "Expand" || el.getAttribute("data-composer-expand-toggle") !== "" ||
        ["role", "aria-expanded", "aria-haspopup", "aria-disabled", "aria-busy", "data-state",
          "data-composer-navigation-target", "data-codex-intelligence-trigger"].some(name => el.getAttribute(name) !== null) ||
        el.disabled || !visible(el) || known.includes(el) || el.closest(BODY_SELECTOR) !== body ||
        el.closest(FOOTER_SELECTOR) || el.closest(COMPOSER_SELECTOR) || el.closest("[data-composer-attachments]") ||
        all(el, "button, [data-composer-footer-responsive], [data-composer-markdown], [data-composer-attachments]").length))
      return fail("UNKNOWN_COMPOSER_CONTROL");
    // Four functional footer controls, plus at most the strictly recognized layout button.
    if (new Set(known).size !== 4 || buttons.length !== 4 + layout.length ||
        buttons.some(el => !known.includes(el) && !layout.includes(el)) ||
        known.some(el => el.closest(FOOTER_SELECTOR) !== footer || !visible(el)))
      return fail("UNKNOWN_COMPOSER_CONTROL");
    if ([...known, ...layout].some(el => el.form !== owner || el.closest("form") !== owner ||
        el.getAttribute("form") !== null && el.form === null))
      return fail("FORM_OWNER_MISMATCH");
    if (known.some(el => el.disabled || el.getAttribute("aria-disabled") === "true"))
      return fail("COMPOSER_CONTROL_DISABLED");
    if (known.some(el => el.getAttribute("aria-expanded") !== null && el.getAttribute("aria-expanded") !== "false" ||
        el.getAttribute("data-state") !== null && el.getAttribute("data-state") !== "closed"))
      return fail("OPEN_COMPOSER_CONTROL");
    if (primary.getAttribute("data-composer-navigation-target") !== null ||
        primary.getAttribute("data-codex-intelligence-trigger") !== null ||
        kind === "send" && (primary.getAttribute("data-state") !== null ||
          primary.getAttribute("aria-expanded") !== null || primary.getAttribute("aria-haspopup") !== null))
      return fail("PRIMARY_STATE_MISMATCH");
    if (all(body, 'input:not([type="file"]), textarea, select, a[href], [role="button"]').length ||
        all(body, 'input[type="file"]').some(visible) ||
        all(body, '[contenteditable="true"]').some(el => el !== editor))
      return fail("UNKNOWN_COMPOSER_CONTROL");
    function extra(node) {
      if (node === editor || known.includes(node) || layout.includes(node) ||
          node.nodeType === 1 && node.tagName === "INPUT" && node.getAttribute("type") === "file") return false;
      if (node.nodeType === 3) return /\S/.test(node.nodeValue || "");
      return [...node.childNodes].some(extra);
    }
    if (extra(body)) return fail("UNKNOWN_COMPOSER_CONTENT");
    return {ok:true, editor, body, footer, owner, attachments:slots[0], controls, primary, kind};
  }
  const sameScope = (view, lease) => view.editor === lease.editor && view.body === lease.body &&
    view.footer === lease.footer && view.owner === lease.owner && view.attachments === lease.attachments &&
    view.controls.every((node, i) => node === lease.controls[i]);
  const preReject = code => request.op === "commit" ? {ok:true, stage:"blocked_before_mutation", code} : fail(code);
  if (!canonical(location.href) || canonical(location.href) !== request.route) return preReject("ROUTE_CHANGED_REBIND");
  if (!window.navigation?.addEventListener) return preReject("NAVIGATION_GUARD_UNAVAILABLE");
  let state = window[SLOT];
  if (!state) {
    state = {generation:null, revision:0, lastEdit:Date.now(), composing:false, navigated:false, ownEvent:null};
    window[SLOT] = state;
    const edited = event => {
      if (!event.target?.closest?.(COMPOSER_SELECTOR) || event === state.ownEvent) return;
      state.revision++; state.lastEdit = Date.now();
      if (event.type === "compositionstart" || event.type === "compositionupdate" || event.isComposing) state.composing = true;
      if (event.type === "compositionend") state.composing = false;
    };
    for (const name of ["beforeinput","input","keydown","paste","drop","compositionstart","compositionupdate","compositionend"])
      document.addEventListener(name, edited, true);
    const moved = () => { state.navigated = true; state.revision++; };
    window.navigation.addEventListener("navigate", moved);
    window.addEventListener("popstate", moved);
    window.addEventListener("hashchange", moved);
  }
  if (request.op === "bind") {
    // Explicit destination/document selection is not permission to fill or Send.
    // Old conversations may lack the latest turn/composer layout until rendered.
    // prepare/commit still require every structure(), draft, IME and lease guard.
    state.generation = request.generation;
    state.documentToken = crypto.randomUUID();
    state.lease = null; state.navigated = false;
    // A fresh bind waits for a quiet period; never infer earlier typing was absent.
    state.lastEdit = Date.now();
    return {ok:true, documentToken:state.documentToken};
  }
  const sameBinding = () => state.generation === request.generation &&
    state.documentToken === request.documentToken && window[SLOT] === state;
  if (state.navigated || !sameBinding()) return preReject("STALE_BINDING_REBIND");
  function guard(expectedText = "") {
    if (state.navigated || canonical(location.href) !== request.route) return fail("ROUTE_CHANGED_REBIND");
    if (state.composing) return fail("IME_ACTIVE");
    if (Date.now() - state.lastEdit < 2000) return fail("RECENT_EDIT");
    const v = structure();
    if (!v.ok) return v;
    if (v.editor.textContent !== expectedText) return fail(expectedText ? "OWNED_TEXT_CHANGED_LEFT_IN_PLACE" : "DRAFT_PRESENT");
    if (!expectedText && all(v.editor, "*").some(el => !["P","BR"].includes(el.tagName)))
      return fail("COMPOSER_CONTENT_UNKNOWN");
    if (v.kind !== (expectedText ? "send" : "voice"))
      return fail(expectedText ? "SEND_NOT_READY_PREFILL_LEFT_IN_PLACE" : "EMPTY_PRIMARY_NOT_VOICE");
    return v;
  }
  if (request.op === "prepare") {
    const v = guard();
    if (!v.ok) return v;
    const token = crypto.randomUUID();
    state.lease = {token, expires:Date.now()+3000, revision:state.revision,
      editor:v.editor, body:v.body, footer:v.footer, owner:v.owner, attachments:v.attachments,
      controls:v.controls, primary:v.primary};
    return {ok:true, lease:token, visibility:document.visibilityState || "unknown",
      focused:typeof document.hasFocus === "function" ? document.hasFocus() : null};
  }
  if (request.op !== "commit") return fail("UNKNOWN_OPERATION");
  const lease = state.lease;
  state.lease = null; // One-use even for a blocked commit.
  const blocked = code => ({ok:true, stage:"blocked_before_mutation", code});
  const noticeVersion=(request.noticeVersion===undefined?1:request.noticeVersion);
  if(![1,2,3,4].includes(noticeVersion))return blocked("INVALID_NOTICE_VERSION");
  if(noticeVersion!==4 && project!=='gpt-agent-bridge')return blocked('INVALID_NOTICE_VERSION');
  function mergedNotice(items) {
    const work=/^work-[0-9a-f]{16}$/;
    if(!Array.isArray(items) || items.length<2 || items.length>128 ||
      new Set(items.map(x=>x?.id)).size!==items.length || items[0]?.id!==request.eventId)
      throw Error('INVALID_MERGED_NOTICE');
    const parts=items.map(x=>{
      if(!x || Object.keys(x).sort().join(',')!=='id,workRefs' ||
        !Array.isArray(x.workRefs) || !x.workRefs.length || x.workRefs.length>528 ||
        x.workRefs.some(w=>!work.test(w)) || new Set(x.workRefs).size!==x.workRefs.length ||
        !(/^batch-[0-9a-f]{16}$/.test(x.id) || work.test(x.id)&&x.workRefs.length===1&&x.workRefs[0]===x.id))
        throw Error('INVALID_MERGED_NOTICE');
      return x.id+'（'+x.workRefs.join('、')+'）';
    });
    const text='Agent 已结束：'+parts.join('、')+'。';
    if(text.length>160000)throw Error('MERGED_NOTICE_TOO_LONG');
    return text;
  }
  let mergedMessage;
  if(noticeVersion===3 || noticeVersion===4 && request.merge) {
    try {mergedMessage=mergedNotice(request.merge);} catch {return blocked('INVALID_MERGED_NOTICE');}
    if(request.batch || request.reportSha!==undefined)return blocked('INVALID_MERGED_NOTICE');
  } else if(request.merge!==undefined)return blocked('INVALID_MERGED_NOTICE');
  // Fixed batch metadata only; no caller-supplied free-form prompt.
  function batchNotice(e, version) {
    const work=/^work-[0-9a-f]{16}$/,sha=/^[0-9a-f]{64}$/;
    if(!e || !/^batch-[0-9a-f]{16}$/.test(e.batch_ref) || e.project_ref!==project ||
      !Number.isInteger(e.requested) || e.requested<1 || e.requested>528 ||
      !Array.isArray(e.members) || !e.members.length || e.members.length>e.requested ||
      e.not_submitted!==e.requested-e.members.length || new Set(e.members.map(m=>m?.work_ref)).size!==e.members.length)
      throw Error('INVALID_BATCH_COMPLETION');
    for(const m of e.members) {
      if(!m || !work.test(m.work_ref) ||
        !['agent_turn_settled','needs_attention','continuity_lost','expired'].includes(m.state) ||
        !['result_ready','attention_required','unavailable'].includes(m.result_class) ||
        !['readable','missing','invalid','unknown','unavailable'].includes(m.classification_report_status) ||
        !['readable','missing','invalid','unavailable'].includes(m.report_status) ||
        (m.report_status==='readable'?!sha.test(m.report_sha256):m.report_sha256!==undefined) ||
        (m.state==='expired'?(m.result_class!=='unavailable'||m.report_status!=='unavailable'):
          (m.result_class==='unavailable'||m.report_status==='unavailable')) ||
        (m.result_class==='result_ready' && (m.state!=='agent_turn_settled'||m.classification_report_status!=='readable'||m.report_status!=='readable')))
        throw Error('INVALID_BATCH_COMPLETION');
    }
    if(version===2 || version===4)return '本批 Agent 已结束（'+e.batch_ref+'）：'+e.members.map(m=>m.work_ref).join('、')+'。';
    const text='【Bridge 派工批次已收束】project_ref=gpt-agent-bridge；batch_ref='+e.batch_ref+
      '；本次条目='+e.requested+'；保留Work='+e.members.length+'；未派出='+e.not_submitted+'。 '+
      e.members.map(m=>'work_ref='+m.work_ref+'；终态='+m.state+'；最终分类='+m.result_class+
        '；分类时报告='+m.classification_report_status+'；当前报告='+m.report_status+
        (m.report_status==='readable'?'；SHA256='+m.report_sha256:'')).join(' ')+
      ' 请用 work_report 按原 work_ref 读取可读报告，异常或缺报告按状态核查，再依据原授权判断与继续。全批收束不表示全批成功；不授予新任务或循环派工权限；过期项不重派。';
    if(text.length>160000)throw Error('BATCH_NOTICE_TOO_LONG');
    return text;
  }
  let batchMessage;
  if(request.batch) {
    try {
      if(request.batch.batch_ref!==request.eventId)throw Error();
      batchMessage=batchNotice(request.batch,noticeVersion);
    }catch {return blocked("INVALID_BATCH_COMPLETION");}
  }
  const completion = /^work-[0-9a-f]{16}$/.test(request.eventId) && /^[0-9a-f]{64}$/.test(request.reportSha || "");
  if (!mergedMessage && !batchMessage && !completion && !/^test-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(request.eventId))
    return blocked("INVALID_EVENT_ID");
  if (!lease || lease.token !== request.lease || Date.now() > lease.expires || lease.revision !== state.revision)
    return blocked("STALE_PAGE_OBSERVATION");
  let view = guard();
  if (!view.ok) return blocked(view.code);
  if (!sameScope(view, lease) || view.primary !== lease.primary)
    return blocked("COMPOSER_REPLACED");
  if (!sameBinding()) return blocked("STALE_BINDING_REBIND");
  if (Date.now() > lease.expires || state.revision !== lease.revision)
    return blocked("STALE_PAGE_OBSERVATION");
  const message = (noticeVersion===4?'project_ref='+project+'；':'') + (mergedMessage || batchMessage || (completion ? ([2,4].includes(noticeVersion) ? "Agent 已结束："+request.eventId+"。" :
    "【Bridge 报告可取】project_ref=gpt-agent-bridge；work_ref=" + request.eventId +
    "；报告 SHA256=" + request.reportSha + "。请用 work_report 读取对应报告，再依据原授权判断与继续。此通知只表示报告可读，不表示任务成功；不授予新任务或循环派工权限。") :
    "【Bridge 扩展测试通知；不是实际任务完成】通知编号：" + request.eventId +
    "。这是用户授权的浏览器通知测试；仅回复该编号以确认收到，不派工、不修改文件。"));
  // Busy-turn guards return before structure() reaches the composer. A rollback
  // needs independent evidence that the captured nodes still own the live editor.
  const currentOwnedEditor = expectedText => {
    const unique=(root,selector,node)=>{
      const found=all(root,selector);return found.length===1 && found[0]===node;
    };
    return sameBinding() && !state.navigated && canonical(location.href)===request.route &&
      state.revision===lease.revision && !state.composing &&
      lease.editor.ownerDocument===document && document.contains(lease.editor) &&
      [lease.editor,lease.body,lease.footer].every(visible) &&
      unique(document,COMPOSER_SELECTOR,lease.editor) &&
      unique(document,'[data-composer-body]',lease.body) &&
      lease.editor.closest(BODY_SELECTOR)===lease.body &&
      unique(lease.body,'[data-composer-footer-responsive]',lease.footer) &&
      lease.editor.closest(FOOTER_SELECTOR)===lease.footer &&
      lease.body.closest('form')===lease.owner && lease.editor.closest('form')===lease.owner &&
      lease.footer.closest('form')===lease.owner &&
      unique(lease.body,'[data-composer-attachments]',lease.attachments) &&
      [ADD_SELECTOR,REASON_SELECTOR,DICTATE_SELECTOR].every((selector,i)=>unique(lease.footer,selector,lease.controls[i])) &&
      lease.editor.textContent===expectedText;
  };
  // Capture locally observable submissions throughout insertion/render/rollback.
  // A click may already have reached the host even while its old draft remains.
  // Such evidence is an unknown send, never a closable pre-click stop.
  let submissionInterference=false;
  const submissionEvents=['click','submit','keydown'];
  const onSubmission=event=>{
    if(event.type==='submit' || event.type==='keydown' && event.key==='Enter') {
      submissionInterference=true;return;
    }
    if(event.type!=='click')return;
    try {
      const path=event.composedPath?.();
      if(!Array.isArray(path) || !path.includes(event.target) || !path.includes(window) ||
        path.some(node=>node?.closest?.('button[type="submit"], input[type="submit"], input[type="image"], button[aria-label="Send"]')))
        submissionInterference=true;
    } catch {submissionInterference=true;}
  };
  const submissionUnknown=()=>({ok:true,stage:'after_mutation',code:'SUBMISSION_INTERFERENCE_OUTCOME_UNKNOWN'});
  if(typeof window.addEventListener!=='function' || typeof window.removeEventListener!=='function')
    return blocked('SUBMISSION_GUARD_UNAVAILABLE');
  try {
    for(const name of submissionEvents)window.addEventListener(name,onSubmission,true);
  } catch {
    for(const name of submissionEvents)window.removeEventListener(name,onSubmission,true);
    return blocked('SUBMISSION_GUARD_UNAVAILABLE');
  }
  try {
    // No await between this guard and insertion. Never replace/clear any draft.
    const inserted=document.createTextNode(message);
    view.editor.appendChild(inserted);
    state.ownEvent = new InputEvent("input", {bubbles:true, inputType:"insertText", data:message});
    try { view.editor.dispatchEvent(state.ownEvent); }
    finally { state.ownEvent = null; }
    await new Promise(resolve => setTimeout(resolve, 50)); // One bounded render opportunity, not polling.
    if(submissionInterference)return submissionUnknown();
    // An injection may survive a replacement binding across a worker lifetime seam.
    if (!sameBinding())
      return {ok:true, stage:"after_mutation", code:"STALE_BINDING_REBIND_PREFILL_LEFT_IN_PLACE"};
    view = guard(message);
    if (!view.ok) {
      // Only a newly observed active turn may release an owned prefill. A changed
      // node, route, binding, edit revision or uncertain cleanup keeps old unknown
      // semantics and leaves all text in place. External submission evidence also
      // prevents withdrawal; not calling our own click is insufficient by itself.
      if(['BUSY_STOP_PRESENT','BUSY_TURN_UNSETTLED'].includes(view.code) &&
        !submissionInterference && currentOwnedEditor(message) && inserted.parentNode===lease.editor) {
        lease.editor.removeChild(inserted);
        state.ownEvent=new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward',data:null});
        try {lease.editor.dispatchEvent(state.ownEvent);} finally {state.ownEvent=null;}
        await new Promise(resolve=>setTimeout(resolve,50));
        if(submissionInterference)return submissionUnknown();
        if(currentOwnedEditor('') && inserted.parentNode===null)
          return {ok:true,stage:'rolled_back_before_click',code:'BUSY_AFTER_PREFILL_ROLLED_BACK'};
      }
      return {ok:true, stage:"after_mutation", code:view.code};
    }
    if (Date.now() > lease.expires || state.revision !== lease.revision || !sameScope(view, lease))
      return {ok:true, stage:"after_mutation", code:"STALE_AFTER_PREFILL_LEFT_IN_PLACE"};
    // Only the captured empty voice -> fully recognized Send change is permitted.
    // Send may reuse the voice node or replace it; its post-render identity is then fixed.
    const send = view.primary;
    const finalView = guard(message);
    if (!finalView.ok) return {ok:true, stage:"after_mutation", code:finalView.code};
    if (!sameScope(finalView, lease) || finalView.primary !== send ||
        Date.now() > lease.expires || state.revision !== lease.revision ||
        canonical(location.href) !== request.route || state.navigated || state.composing ||
        finalView.editor.textContent !== message)
      return {ok:true, stage:"after_mutation", code:"INTERFERENCE_PREFILL_LEFT_IN_PLACE"};
    if (!sameBinding())
      return {ok:true, stage:"after_mutation", code:"STALE_BINDING_REBIND_PREFILL_LEFT_IN_PLACE"};
    if(submissionInterference)return submissionUnknown();
    send.click();
    return {ok:true, stage:"clicked", code:"CLICK_ATTEMPTED_RECEIPT_UNKNOWN"};
  } finally {
    for(const name of submissionEvents)window.removeEventListener(name,onSubmission,true);
  }
}
