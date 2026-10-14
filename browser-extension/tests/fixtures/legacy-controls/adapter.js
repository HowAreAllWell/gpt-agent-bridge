// Serialized into the ISOLATED world by chrome.scripting. No closure dependencies.
// These selectors describe an UNVERIFIED, deliberately narrow ChatGPT DOM contract.
export async function domOperation(request) {
  const SLOT = "__bridgeSyntheticNoticeV1";
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
    if (all(document, 'button[data-testid="stop-button"]').some(visible)) return fail("BUSY_STOP_PRESENT");
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
    if (slots.length !== 1 || slots[0].tagName !== "DIV" || slots[0].getAttribute("hidden") === null ||
        visible(slots[0]) || slots[0].childNodes.length)
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
    // Reject role collisions, unknown/foreign buttons, hidden controls and foreign form owners.
    if (new Set(known).size !== 4 || buttons.length !== 4 ||
        buttons.some(el => !known.includes(el)) ||
        known.some(el => el.closest(FOOTER_SELECTOR) !== footer || !visible(el)))
      return fail("UNKNOWN_COMPOSER_CONTROL");
    if (known.some(el => el.form !== owner || el.closest("form") !== owner ||
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
      if (node === editor || known.includes(node) ||
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
  if (canonical(location.href) !== request.route) return preReject("ROUTE_CHANGED_REBIND");
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
    const view = structure();
    if (!view.ok) return view;
    if (view.editor.textContent === "" && view.kind !== "voice") return fail("EMPTY_PRIMARY_NOT_VOICE");
    state.generation = request.generation;
    state.documentToken = crypto.randomUUID();
    state.lease = null; state.navigated = false;
    // A fresh bind waits for a quiet period; never infer earlier typing was absent.
    state.lastEdit = Date.now();
    return {ok:true, documentToken:state.documentToken};
  }
  const sameBinding = () => state.generation === request.generation &&
    state.documentToken === request.documentToken;
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
    return {ok:true, lease:token};
  }
  if (request.op !== "commit") return fail("UNKNOWN_OPERATION");
  const lease = state.lease;
  state.lease = null; // One-use even for a blocked commit.
  const blocked = code => ({ok:true, stage:"blocked_before_mutation", code});
  if (!/^test-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(request.eventId))
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
  const message = "【Bridge 扩展测试通知；不是实际任务完成】通知编号：" + request.eventId +
    "。这是用户授权的浏览器通知测试；仅回复该编号以确认收到，不派工、不修改文件。";
  // No await between this guard and insertion. Never replace/clear any draft.
  view.editor.appendChild(document.createTextNode(message));
  state.ownEvent = new InputEvent("input", {bubbles:true, inputType:"insertText", data:message});
  try { view.editor.dispatchEvent(state.ownEvent); }
  finally { state.ownEvent = null; }
  await new Promise(resolve => setTimeout(resolve, 50)); // One bounded render opportunity, not polling.
  // An injection may survive a replacement binding across a worker lifetime seam.
  if (!sameBinding())
    return {ok:true, stage:"after_mutation", code:"STALE_BINDING_REBIND_PREFILL_LEFT_IN_PLACE"};
  view = guard(message);
  if (!view.ok) return {ok:true, stage:"after_mutation", code:view.code};
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
  send.click();
  return {ok:true, stage:"clicked", code:"CLICK_ATTEMPTED_RECEIPT_UNKNOWN"};
}
