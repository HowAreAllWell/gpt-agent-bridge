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
  const BODY_SELECTOR = "[data-composer-body]";
  const FOOTER_SELECTOR = "[data-composer-footer-responsive]";
  // Empty readiness requires a known idle Voice. After our own prefill the
  // user-confirmed Send contract is the unique owned native submit button.
  const VOICE_SELECTOR = 'button[type="button"][aria-label="Start Voice"],button[type="button"][aria-label="开始语音"]';
  const SEND_SELECTOR = 'button[type="submit"]';
  function nativeSubmitter(control) {
    if(!control)return false;
    const type=(control.getAttribute('type') || '').toLowerCase();
    if(control.tagName==='BUTTON')return type==='submit' || !!control.form && !['button','reset'].includes(type);
    return control.tagName==='INPUT' && ['submit','image'].includes(type);
  }
  function submitters(view) {
    return all(document,'button, input').filter(nativeSubmitter).filter(control=>
      visible(control) &&
      (view.body.contains(control) || view.owner && control.form===view.owner));
  }
  function structure(choice = false) {
    if (!choice && navigator.onLine !== true) return fail("OFFLINE");
    if (all(document, 'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]').some(visible))
      return fail("DIALOG_OR_CHALLENGE");
    if (!choice && all(document, 'button[data-testid="stop-button"], button[type="button"][aria-label="Stop"], button[type="button"][aria-label="停止"]').some(visible))
      return fail("BUSY_STOP_PRESENT");
    const editors = all(document, COMPOSER_SELECTOR).filter(visible);
    if (editors.length !== 1) return fail("COMPOSER_UNKNOWN_OR_AMBIGUOUS");
    const editor=editors[0], body=editor.closest(BODY_SELECTOR);
    if (!body || !visible(body) || body.parentElement?.closest(BODY_SELECTOR) || all(body,BODY_SELECTOR).length)
      return fail("COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS");
    const outsideEditor=node=>!editor.contains(node);
    const footers=all(body,FOOTER_SELECTOR).filter(outsideEditor).filter(visible);
    if (footers.length!==1 || footers[0].closest(BODY_SELECTOR)!==body)
      return fail("COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS");
    const footer=footers[0], owner=body.closest('form');
    if (editor.closest('form')!==owner || footer.closest('form')!==owner || all(body,'form').some(outsideEditor))
      return fail("FORM_OWNER_MISMATCH");
    if (all(body,'iframe, [role="alert"]').filter(outsideEditor).some(visible))return fail("VISIBLE_FRAME_OR_ALERT");
    if (!choice && (body.getAttribute('aria-busy')==='true' || owner?.getAttribute('aria-busy')==='true' ||
      all(owner || body,'[aria-busy="true"], [role="progressbar"], [data-testid="upload-progress"]').filter(outsideEditor)
        .filter(el=>!owner || el.closest('form')===owner).some(visible)))
      return fail("COMPOSER_NOT_READY");
    if (!choice && all(body,'[aria-expanded="true"], [data-state="open"]').filter(outsideEditor).some(visible))
      return fail("OPEN_COMPOSER_CONTROL");
    const slots=all(body,'[data-composer-attachments]').filter(outsideEditor);
    if (slots.length!==1 || slots[0].tagName!=='DIV')
      return fail("ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY");
    // Native form ownership includes controls outside the composer subtree.
    const documentFiles=all(document,'input[type="file"]');
    const fileInputs=documentFiles.filter(el=>body.contains(el) || owner && el.form===owner && el.files?.length);
    const unownedSelection=documentFiles.some(el=>!body.contains(el) && el.form===null && el.files?.length);
    const attachmentNodes=[slots[0],...all(body,'[data-testid="attachment"], img, video, audio, canvas')
      .filter(outsideEditor).filter(visible).filter(el=>el!==slots[0] &&
        (el.getAttribute('data-testid')==='attachment' || !el.closest('button[type="button"]')))];
    const hasAttachments=!!slots[0].childNodes.length || attachmentNodes.length>1 || fileInputs.some(el=>el.files?.length);
    if (all(body,'input:not([type="file"]), textarea, select').filter(outsideEditor).some(visible) ||
      !choice && all(body,'input[type="file"]').some(visible) ||
      all(body,'[contenteditable="true"]').filter(outsideEditor).some(visible))
      return fail("UNKNOWN_COMPOSER_CONTROL");
    return {ok:true,editor,body,footer,owner,attachments:slots[0],hasAttachments,unownedSelection,attachmentNodes,fileInputs};
  }
  function primaryView(view, filled) {
    const sends=all(view.body,SEND_SELECTOR).filter(el=>!view.editor.contains(el)).filter(visible);
    const voices=all(view.body,VOICE_SELECTOR).filter(el=>!view.editor.contains(el)).filter(visible);
    // A Voice may become another Send after prefill. Prove a single recognized
    // primary before intent, not merely a single currently rendered Send.
    if (sends.length+voices.length!==1 || filled && sends.length!==1)
      return fail(filled?'SEND_NOT_READY_PREFILL_LEFT_IN_PLACE':'PRIMARY_UNKNOWN_OR_AMBIGUOUS');
    if(!filled && voices.length!==1)return fail('EMPTY_PRIMARY_NOT_VOICE');
    // Count implicit/default buttons and input submit/image controls too,
    // including controls outside the composer associated with this native form.
    const native=submitters(view);
    if(filled ? native.length!==1 || native[0]!==sends[0] : native.length!==0)
      return fail(filled?'SEND_NOT_READY_PREFILL_LEFT_IN_PLACE':'PRIMARY_UNKNOWN_OR_AMBIGUOUS');
    const primary=sends[0] || voices[0];
    if(primary.parentElement?.closest('button'))return fail('UNKNOWN_COMPOSER_CONTROL');
    if (primary.closest(BODY_SELECTOR)!==view.body || primary.closest('[data-composer-footer-responsive]')!==view.footer ||
      primary.form!==view.owner || primary.closest('form')!==view.owner ||
      primary.getAttribute('form')!==null && primary.form===null)return fail('FORM_OWNER_MISMATCH');
    if (primary.disabled || primary.getAttribute('aria-disabled')==='true')return fail('COMPOSER_CONTROL_DISABLED');
    if (primary.getAttribute('data-composer-navigation-target')!==null ||
      primary.getAttribute('data-codex-intelligence-trigger')!==null)return fail('PRIMARY_STATE_MISMATCH');
    return {...view,primary};
  }
  const sameScope = (view, lease) => view.editor === lease.editor && view.body === lease.body &&
    view.footer === lease.footer && view.owner === lease.owner && view.attachments === lease.attachments;
  const preReject = code => ['commit','draft_commit'].includes(request.op) ? {ok:true,stage:'blocked_before_mutation',code} : fail(code);
  if (!canonical(location.href) || canonical(location.href) !== request.route) return preReject("ROUTE_CHANGED_REBIND");
  if (!window.navigation?.addEventListener) return preReject("NAVIGATION_GUARD_UNAVAILABLE");
  let state = window[SLOT];
  if (!state) {
    state = {generation:null, revision:0, composing:false, navigated:false, ownEvent:null};
    window[SLOT] = state;
    const edited = event => {
      if (!event.target?.closest?.(COMPOSER_SELECTOR) || event === state.ownEvent) return;
      state.revision++;
      if (event.type === "compositionstart" || event.type === "compositionupdate" || event.isComposing) state.composing = true;
      if (event.type === "compositionend") state.composing = false;
    };
    for (const name of ["beforeinput","input","keydown","paste","drop","compositionstart","compositionupdate","compositionend"])
      document.addEventListener(name, edited, true);
    const moved = () => { state.navigated = true; state.revision++; state.retireChoice?.(); };
    window.navigation.addEventListener("navigate", moved);
    window.addEventListener("popstate", moved);
    window.addEventListener("hashchange", moved);
  }
  // Also initialize when a prior adapter already bound this same document.
  if(!Object.hasOwn(state,'submissions') || typeof state.submissionObserver!=='function') {
    if(!Object.hasOwn(state,'submissions'))state.submissions=0;
    // A choice may wait for the worker's durable intent ACK. An observed user
    // submission in that interval must not append into the next message.
    const submitted = event => {
      if(event.type==='keydown') {
        if(event.target?.closest?.(COMPOSER_SELECTOR) && event.key==='Enter' && !event.shiftKey && !event.isComposing && !state.composing)state.submissions++;
        return;
      }
      // Observe submission threats even while other readiness checks fail.
      // Observation only invalidates a choice; mutation still needs every guard.
      const editors=all(document,COMPOSER_SELECTOR).filter(visible);
      if(editors.length!==1)return;
      const editor=editors[0],body=editor.closest(BODY_SELECTOR);
      if(!body)return;
      const view={editor,body,owner:body.closest('form')};
      const control=event.target?.closest?.('button, input');
      if(event.type==='submit' ? view.owner && event.target===view.owner : submitters(view).includes(control))
        state.submissions++;
    };
    document.addEventListener('click',submitted,true);
    document.addEventListener('submit',submitted,true);
    document.addEventListener('keydown',submitted,true);
    state.submissionObserver=submitted; // Page-local only; retain any prior counter.
  }
  if (request.op === "bind") {
    // Explicit destination/document selection is not permission to fill or Send.
    // Old conversations may lack the latest turn/composer layout until rendered.
    // prepare/commit still require every structure(), draft, IME and lease guard.
    state.retireChoice?.();
    state.generation = request.generation;
    state.documentToken = crypto.randomUUID();
    state.lease = null; state.navigated = false;
    return {ok:true, documentToken:state.documentToken};
  }
  const sameBinding = () => state.generation === request.generation &&
    state.documentToken === request.documentToken && window[SLOT] === state;
  if (state.navigated || !sameBinding()) return preReject("STALE_BINDING_REBIND");
  function guard(expectedText = "") {
    if (state.navigated || canonical(location.href) !== request.route) return fail("ROUTE_CHANGED_REBIND");
    let v = structure(true);
    if (!v.ok) return v;
    const rich=all(v.editor,'*').some(el=>!['P','BR'].includes(el.tagName));
    // Draft presence wins over busy/IME. A shown choice never becomes auto-Send.
    if(!expectedText && (v.hasAttachments || v.unownedSelection || v.editor.textContent || rich))return fail('DRAFT_PRESENT');
    if(!expectedText && state.draftOffer?.host.isConnected)return fail('DRAFT_CHOICE_PENDING');
    v=structure();if(!v.ok)return v;
    if(expectedText && state.composing)return fail('IME_ACTIVE');
    if(v.hasAttachments)return fail(v.attachments.childNodes.length?'ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY':'ATTACHMENT');
    if(v.editor.textContent!==expectedText)return fail('OWNED_TEXT_CHANGED_LEFT_IN_PLACE');
    if(state.composing)return fail('IME_ACTIVE');
    if(v.unownedSelection)return fail('ATTACHMENT');
    return primaryView(v,!!expectedText);
  }
  if (request.op === "draft_dismiss") {
    // Explicit worker retirement/disable revokes queued page leases too. A
    // timed-out script may arrive later; passive polling must not be its fence.
    state.lease=null;state.revision++;state.retireChoice?.();return {ok:true};
  }
  if(request.op==='draft_probe')return {ok:true};
  if(request.op==='draft_result') {
    const offer=state.draftOffer;
    if(offer?.id===request.offerId && offer.token===request.token)offer.settle?.({ok:true,...request});
    return {ok:true};
  }
  if (request.op === "prepare") {
    const v = guard();
    if(v.ok)state.retireChoice?.();
    if (!v.ok) return v;
    const token = crypto.randomUUID();
    state.lease = {token, expires:Date.now()+3000, revision:state.revision,
      editor:v.editor, body:v.body, footer:v.footer, owner:v.owner, attachments:v.attachments,
      primary:v.primary};
    return {ok:true, lease:token, visibility:document.visibilityState || "unknown",
      focused:typeof document.hasFocus === "function" ? document.hasFocus() : null};
  }
  if (!["commit","draft_offer","draft_prepare","draft_commit"].includes(request.op)) return fail("UNKNOWN_OPERATION");
  const lease = state.lease;
  if(request.op==='commit')state.lease = null; // One-use even for a blocked commit.
  const blocked = preReject;
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
  if(request.op!=='draft_offer' && (noticeVersion===3 || noticeVersion===4 && request.merge)) {
    try {mergedMessage=mergedNotice(request.merge);} catch {return blocked('INVALID_MERGED_NOTICE');}
    if(request.batch || request.reportSha!==undefined)return blocked('INVALID_MERGED_NOTICE');
  } else if(request.op!=='draft_offer' && request.merge!==undefined)return blocked('INVALID_MERGED_NOTICE');
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
  if (request.op!=='draft_offer' && !mergedMessage && !batchMessage && !completion && !/^test-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(request.eventId))
    return blocked("INVALID_EVENT_ID");
  const message = (noticeVersion===4?'project_ref='+project+'；':'') + (mergedMessage || batchMessage || (completion ? ([2,4].includes(noticeVersion) ? "Agent 已结束："+request.eventId+"。" :
    "【Bridge 报告可取】project_ref=gpt-agent-bridge；work_ref=" + request.eventId +
    "；报告 SHA256=" + request.reportSha + "。请用 work_report 读取对应报告，再依据原授权判断与继续。此通知只表示报告可读，不表示任务成功；不授予新任务或循环派工权限。") :
    "【Bridge 扩展测试通知；不是实际任务完成】通知编号：" + request.eventId +
    "。这是用户授权的浏览器通知测试；无需回复，不派工、不修改文件。"));

  // Choices live only in this extension's ISOLATED world, never in page attributes.
  // No draft text leaves the page or enters durable records.
  const BANNER = '__bridgeDraftChoiceV1';
  const retireChoice = () => {
    const offer=state.draftOffer;
    offer?.host.remove();
    if(window[BANNER]===offer)delete window[BANNER];
    state.draftOffer=null;state.choiceLease=null;
  };
  state.retireChoice=retireChoice;
  function draftView() {
    if(!sameBinding() || state.navigated || canonical(location.href)!==request.route)return fail('STALE_BINDING_REBIND');
    const v=structure(true);
    if(!v.ok)return v;
    // The same prompt remains after editing, uploading or clearing the draft.
    return v;
  }
  const packet = () => JSON.stringify([request.eventId,request.noticeVersion,request.reportSha,request.batch,request.merge]);
  if(request.op==='draft_offer') {
    if(typeof request.offerId!=='string' || !/^[0-9a-f-]{36}$/.test(request.offerId))return fail('DRAFT_CHOICE_STALE');
    const old=state.draftOffer;
    if(old?.host.isConnected && old.id===request.offerId && old.generation===state.generation)
      return {ok:true,code:'DRAFT_CHOICE_PENDING',token:old.token};
    const view=draftView();
    if(!view.ok)return view;
    if(typeof document.createElement!=='function' || typeof chrome==='undefined' || !chrome.runtime?.sendMessage)
      return fail('DRAFT_CHOICE_UNAVAILABLE');

    if(old?.host.isConnected)return fail('DRAFT_CHOICE_UNCONFIRMED');
    if(window[BANNER] && !window[BANNER].host.isConnected)window[BANNER].retire();
    if(window[BANNER] && window[BANNER]!==old)return fail('DRAFT_CHOICE_OTHER_PROJECT');
    retireChoice();
    const host=document.createElement('div');
    if(typeof host.attachShadow!=='function')return fail('DRAFT_CHOICE_UNAVAILABLE');
    const shadow=host.attachShadow({mode:'closed'});
    const panel=document.createElement('div');panel.setAttribute('role','group');panel.setAttribute('aria-label','Bridge 完成提醒');
    panel.style.cssText='padding:10px;margin:8px 0;border:1px solid #888;border-radius:8px;background:#fff;color:#111;font:14px system-ui;';
    const label=document.createElement('span');label.textContent='Bridge：工作已结束，当前输入框已有草稿。 ';
    panel.appendChild(label);shadow.appendChild(panel);
    const offer={id:request.offerId,host,generation:state.generation,token:crypto.randomUUID(),
      clicked:false,attempted:false,inFlight:false,buttons:[],retire:retireChoice};
    const uncertain=()=>{
      if(state.draftOffer!==offer)return;
      offer.inFlight=false; // A pending/result reconciliation releases or retires this same view.
    };
    offer.settle=result=>{
      if(state.draftOffer!==offer || !result?.ok || result.offerId!==offer.id)return uncertain();
      if(result.outcome==='ignored' || result.dismissed===true ||
        result.outcome==='unknown') {retireChoice();return;}
      if(result.outcome==='pending' && !offer.attempted) {
        offer.inFlight=false;offer.clicked=false;state.choiceLease=null;
        for(const button of offer.buttons)button.disabled=false;
        label.textContent='Bridge：工作已结束，当前输入框已有草稿。 ';
      } else uncertain();
    };
    state.draftOffer=offer;window[BANNER]=offer;
    for(const [choice,text] of [['append','追加到输入框末尾（另起一行）'],['ignore','忽略']]) {
      const button=document.createElement('button');button.setAttribute('type','button');button.textContent=text;
      button.style.cssText='margin:4px;padding:6px;border:1px solid #777;border-radius:4px;background:#fff;color:#111;';
      // Showing the prompt and pointing at it do not move the caret or interrupt IME.
      button.addEventListener('pointerdown',e=>{if(e.isTrusted)e.preventDefault();});
      button.addEventListener('click',e=>{
        if(!e.isTrusted || e.target!==button || button.disabled || state.draftOffer!==offer ||
          offer.inFlight || offer.clicked || offer.attempted || !host.isConnected)return;
        e.preventDefault();e.stopPropagation();
        if(!sameBinding() || state.navigated || canonical(location.href)!==request.route){retireChoice();return;}
        if(choice==='append') {
          if(state.composing){label.textContent='Bridge：请完成当前输入法组合，再追加。 ';return;}
          if(!draftView().ok)return;
        }
        offer.submissions=state.submissions;
        offer.clicked=true;offer.inFlight=true;offer.choice=choice;
        for(const item of offer.buttons)item.disabled=true;
        try {
          Promise.resolve(chrome.runtime.sendMessage({action:'draft_choice',project_ref:project,
            offerId:offer.id,token:offer.token,choice})).then(offer.settle,uncertain);
        } catch {uncertain();}
      });
      offer.buttons.push(button);panel.appendChild(button);
    }
    view.body.parentNode.insertBefore(host,view.body.nextSibling);
    return {ok:true,code:'DRAFT_CHOICE_PENDING',token:offer.token};
  }
  if(request.op==='draft_prepare') {
    const offer=state.draftOffer;
    if(!offer || !offer.clicked || offer.attempted || offer.id!==request.offerId || !['append','ignore'].includes(offer.choice) || offer.token!==request.token ||
      offer.generation!==state.generation || state.choiceLease)return fail('DRAFT_CHOICE_STALE');
    if(state.submissions!==offer.submissions)return fail('DRAFT_CHOICE_STALE');
    if(state.composing)return fail('IME_ACTIVE');
    const view=draftView();if(!view.ok)return view;
    if(offer.choice==='append' && (view.body.getAttribute('aria-busy')==='true' || view.owner?.getAttribute('aria-busy')==='true' || all(view.body,'[aria-busy="true"], [role="progressbar"], [data-testid="upload-progress"]').filter(el=>!view.editor.contains(el)).some(visible)))return fail('COMPOSER_NOT_READY');
    const token=crypto.randomUUID();
    state.choiceLease={token,offer,signature:packet()}; // One use; current draft is not a frozen snapshot.
    return {ok:true,lease:token,visibility:document.visibilityState || 'unknown',
      focused:typeof document.hasFocus==='function'?document.hasFocus():null};
  }
  if(request.op==='draft_commit') {
    const lease=state.choiceLease,offer=state.draftOffer;
    state.choiceLease=null;
    if(!lease || lease.offer!==offer || !offer?.clicked || offer.attempted || offer.id!==request.offerId || offer.token!==request.token ||
      lease.signature!==packet() || lease.token!==request.lease || offer.generation!==state.generation)
      return preReject('DRAFT_CHOICE_STALE');
    const choice=offer.choice;
    if(!['append','ignore'].includes(choice) || state.submissions!==offer.submissions)return preReject('DRAFT_CHOICE_STALE');
    if(state.composing)return preReject('IME_ACTIVE');
    const view=draftView();if(!view.ok)return preReject(view.code);
    if(choice==='ignore'){retireChoice();return {ok:true,stage:'handled',code:'DRAFT_NOTIFICATION_HANDLED'};}
    if((view.body.getAttribute('aria-busy')==='true' || view.owner?.getAttribute('aria-busy')==='true' || all(view.body,'[aria-busy="true"], [role="progressbar"], [data-testid="upload-progress"]').filter(el=>!view.editor.contains(el)).some(visible)))return preReject('COMPOSER_NOT_READY');
    // Durable intent is ACKed. Append only to the CURRENT bound editor; no
    // original draft/File snapshots, quiet timer, focus move or Send invocation.
    offer.attempted=true;retireChoice();
    const paragraph=document.createElement('p'),inserted=document.createTextNode(message);
    paragraph.appendChild(inserted);view.editor.appendChild(paragraph);
    state.ownEvent=new InputEvent('input',{bubbles:true,inputType:'insertText',data:'\n'+message});
    try {view.editor.dispatchEvent(state.ownEvent);} finally {state.ownEvent=null;}
    await new Promise(resolve=>setTimeout(resolve,50));
    const after=draftView();
    if(!after.ok || after.editor!==view.editor || paragraph.parentNode!==after.editor ||
      paragraph.childNodes.length!==1 || paragraph.childNodes[0]!==inserted || inserted.nodeValue!==message)
      return fail('DRAFT_APPEND_OUTCOME_UNKNOWN');
    return {ok:true,stage:'after_mutation',code:'DRAFT_APPEND_DOM_OBSERVED'};
  }

  if (!lease || lease.token !== request.lease || Date.now() > lease.expires || lease.revision !== state.revision)
    return blocked("STALE_PAGE_OBSERVATION");
  let view = guard();
  if (!view.ok) return blocked(view.code);
  if (!sameScope(view, lease) || view.primary !== lease.primary)
    return blocked("COMPOSER_REPLACED");
  if (!sameBinding()) return blocked("STALE_BINDING_REBIND");
  if (Date.now() > lease.expires || state.revision !== lease.revision)
    return blocked("STALE_PAGE_OBSERVATION");

  // Busy-turn guards return before structure() reaches the composer. A rollback
  // needs independent evidence that the captured nodes still own the live editor.
  const currentOwnedEditor = expectedText => {
    const editors=all(document,COMPOSER_SELECTOR).filter(visible);
    const footers=all(lease.body,FOOTER_SELECTOR).filter(el=>!lease.editor.contains(el)).filter(visible);
    const slots=all(lease.body,'[data-composer-attachments]').filter(el=>!lease.editor.contains(el));
    return sameBinding() && !state.navigated && canonical(location.href)===request.route &&
      state.revision===lease.revision && !state.composing &&
      lease.editor.ownerDocument===document && document.contains(lease.editor) &&
      [lease.editor,lease.body,lease.footer].every(visible) &&
      editors.length===1 && editors[0]===lease.editor &&
      lease.editor.closest(BODY_SELECTOR)===lease.body &&
      footers.length===1 && footers[0]===lease.footer && lease.footer.closest(BODY_SELECTOR)===lease.body &&
      lease.body.closest('form')===lease.owner && lease.editor.closest('form')===lease.owner &&
      lease.footer.closest('form')===lease.owner &&
      slots.length===1 && slots[0]===lease.attachments &&
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
      if(view.code==='BUSY_STOP_PRESENT' &&
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
    return {ok:true, stage:"clicked", code:"SEND_CLICK_INVOKED"};
  } finally {
    for(const name of submissionEvents)window.removeEventListener(name,onSubmission,true);
  }
}
