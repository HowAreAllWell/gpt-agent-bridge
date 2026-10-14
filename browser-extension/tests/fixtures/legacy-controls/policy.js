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
export function validState(s) {
  return s && s.schema === 1 && typeof s.boot === "string" && Number.isSafeInteger(s.revision) &&
    Array.isArray(s.events) && s.events.length <= LIMIT &&
    new Set(s.events.map(e => e.id)).size === s.events.length &&
    s.events.every(e => ID.test(e.id) && route(e.route) === e.route &&
      ["queued","paused","cancelled","attempted_unknown","operator_confirmed"].includes(e.status)) &&
    (!s.binding || (route(s.binding.route) === s.binding.route && Number.isInteger(s.binding.tabId) &&
      typeof s.binding.generation === "string" && typeof s.binding.documentId === "string" &&
      typeof s.binding.documentToken === "string"));
}
