export const PROJECT = "gpt-agent-bridge";
export const LIMIT = 16;
export const KEY = "bridgeSyntheticV1";
export const ALARM = "bridge-synthetic-once";
export const ID = /^test-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function route(value) {
  try {
    const u = new URL(value);
    if (u.origin !== "https://chatgpt.com" || u.username || u.password || u.href !== u.origin + u.pathname ||
        !/^\/(?:g\/g-p-[0-9a-f]{32}-[a-z]+(?:-[a-z]+)*\/)?c\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(u.pathname)) return null;
    return u.origin + u.pathname;
  } catch { return null; }
}
export function notice(id) {
  if (!ID.test(id)) throw new Error("INVALID_EVENT_ID");
  return "【Bridge 扩展测试通知；不是实际任务完成】通知编号：" + id +
    "。这是用户授权的浏览器通知测试；仅回复该编号以确认收到，不派工、不修改文件。";
}

// Exact codes produced by the reviewed adapter's guards, never a prefix heuristic.
const GUARD_CODES = ["OFFLINE","DIALOG_OR_CHALLENGE","VISIBLE_FRAME_OR_ALERT","BUSY_STOP_PRESENT",
  "TURN_STRUCTURE_UNKNOWN","BUSY_TURN_UNSETTLED",
  "COMPOSER_UNKNOWN_OR_AMBIGUOUS","COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS","COMPOSER_FOOTER_UNKNOWN_OR_AMBIGUOUS",
  "FORM_OWNER_MISMATCH","BUSY_OR_UPLOAD","OPEN_COMPOSER_CONTROL","ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY",
  "ATTACHMENT","AUXILIARY_CONTROL_UNKNOWN_OR_AMBIGUOUS","PRIMARY_UNKNOWN_OR_AMBIGUOUS",
  "UNKNOWN_COMPOSER_CONTROL","COMPOSER_CONTROL_DISABLED","PRIMARY_STATE_MISMATCH","UNKNOWN_COMPOSER_CONTENT",
  "ROUTE_CHANGED_REBIND","IME_ACTIVE","RECENT_EDIT"];
const PRECLICK_CODES = [...GUARD_CODES,"OWNED_TEXT_CHANGED_LEFT_IN_PLACE","SEND_NOT_READY_PREFILL_LEFT_IN_PLACE",
  "STALE_BINDING_REBIND_PREFILL_LEFT_IN_PLACE","STALE_AFTER_PREFILL_LEFT_IN_PLACE","INTERFERENCE_PREFILL_LEFT_IN_PLACE"];
const BEFORE_CODES = [...GUARD_CODES,"NAVIGATION_GUARD_UNAVAILABLE","SUBMISSION_GUARD_UNAVAILABLE","STALE_BINDING_REBIND","DRAFT_PRESENT",
  "COMPOSER_CONTENT_UNKNOWN","EMPTY_PRIMARY_NOT_VOICE","INVALID_EVENT_ID","STALE_PAGE_OBSERVATION","COMPOSER_REPLACED"];
export function commitOutcome(r, documentId) {
  if (!r || typeof r !== "object" || Array.isArray(r) ||
      Object.keys(r).sort().join(",") !== "code,documentId,ok,stage" || r.ok !== true ||
      typeof documentId !== "string" || !documentId || r.documentId !== documentId) return "unknown";
  if (r.stage === "after_mutation" && PRECLICK_CODES.includes(r.code)) return "preclick_stop";
  if (r.stage === "rolled_back_before_click" && r.code === "BUSY_AFTER_PREFILL_ROLLED_BACK") return "rolled_back_before_click";
  if (r.stage === "blocked_before_mutation" && BEFORE_CODES.includes(r.code)) return "blocked_before_mutation";
  if (r.stage === "clicked" && r.code === "CLICK_ATTEMPTED_RECEIPT_UNKNOWN") return "clicked";
  return "unknown";
}
const ATTEMPT_FIELDS = ["id","route","generation","status","code","createdAt","dueAt","intentAt"];
function exactAttempt(e, withOutcome) {
  const fields = withOutcome ? [...ATTEMPT_FIELDS,"outcome"] : ATTEMPT_FIELDS;
  return e && Object.keys(e).length === fields.length && fields.every(k => Object.hasOwn(e,k)) &&
    ID.test(e.id) && route(e.route) === e.route && typeof e.generation === "string" && e.generation.length > 0 &&
    [e.createdAt,e.dueAt,e.intentAt].every(t => Number.isSafeInteger(t) && t >= 0) &&
    e.dueAt >= e.createdAt && e.intentAt >= e.createdAt;
}
export function preclickEvidence(e) {
  if (!e || e.status !== "attempted_unknown") return null;
  if (Object.hasOwn(e,"outcome"))
    return exactAttempt(e,true) && e.outcome === "preclick_stop" && PRECLICK_CODES.includes(e.code) ? "preclick_stop" : null;
  // Reviewed v2 producer: this exact legacy code + saved intent could only survive
  // as attempted_unknown after a guard return BEFORE send.click(). No migration.
  return exactAttempt(e,false) && e.code === "ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY" ? "legacy_attachment_stop" : null;
}
function validClosed(e) {
  return exactAttempt(e,true) && (e.outcome === "preclick_stop" && PRECLICK_CODES.includes(e.code) ||
    e.outcome === "legacy_attachment_stop" && e.code === "ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY");
}
export function validState(s) {
  return s && s.schema === 1 && typeof s.boot === "string" && Number.isSafeInteger(s.revision) &&
    Array.isArray(s.events) && s.events.length <= LIMIT &&
    new Set(s.events.map(e => e.id)).size === s.events.length &&
    s.events.every(e => ID.test(e.id) && route(e.route) === e.route &&
      (["queued","paused","cancelled","attempted_unknown","operator_confirmed","receipt_confirmed"].includes(e.status) ||
        e.status === "closed_before_send" && validClosed(e))) &&
    (!s.binding || (route(s.binding.route) === s.binding.route && Number.isInteger(s.binding.tabId) &&
      typeof s.binding.generation === "string" && typeof s.binding.documentId === "string" &&
      typeof s.binding.documentToken === "string"));
}
