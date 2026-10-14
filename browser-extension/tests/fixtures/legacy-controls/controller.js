import {PROJECT, LIMIT, KEY, ALARM, route, notice, validState} from "./policy.js";

// The promise chain serializes one live worker only. All authoritative records
// live in storage; a dead worker's intent is never inferred to be unsent.
export class Controller {
  constructor(io) { this.io = io; this.chain = Promise.resolve(); }
  run(action, arg) {
    const job = this.chain.then(() => this.dispatch(action, arg));
    this.chain = job.catch(() => {});
    return job;
  }
  async load() {
    const boot = await this.io.boot();
    let s = await this.io.read(KEY);
    if (s === undefined) {
      s = {schema:1, boot, revision:0, binding:null, events:[]};
      await this.save(s);
    }
    if (!validState(s)) throw new Error("STATE_INVALID_NO_RESET");
    if (s.boot !== boot) {
      s.boot = boot; s.binding = null;
      for (const e of s.events) if (["queued","paused"].includes(e.status)) {
        e.status = "paused"; e.code = "BROWSER_RESTART_REBIND";
      }
      await this.save(s);
      await this.io.clearAlarm(ALARM);
    }
    return s;
  }
  async save(s) {
    s.revision++;
    await this.io.write(KEY, s); // Failure/ambiguous acknowledgement stops caller.
  }
  async target(binding) {
    if (!binding) throw new Error("REBIND_REQUIRED");
    const tab = await this.io.tab(binding.tabId);
    if (tab.incognito || route(tab.url) !== binding.route) throw new Error("TARGET_CHANGED_REBIND");
  }
  latest(s) { return s.events.at(-1); }
  async pause(s, e, code) {
    e.status = "paused"; e.code = code;
    if (code.includes("REBIND")) s.binding = null;
    await this.save(s);
    return s;
  }
  async invalidate(s, code) {
    s.binding = null;
    const e = this.latest(s);
    if (e && ["queued","paused"].includes(e.status)) { e.status = "paused"; e.code = code; }
    await this.save(s); await this.io.clearAlarm(ALARM);
    return {...s, inspection:code};
  }
  async dispatch(action, arg = {}) {
    let s = await this.load();
    if (action === "status") return s;
    if (action === "startup") {
      s.binding = null;
      for (const e of s.events) if (["queued","paused"].includes(e.status)) {
        e.status = "paused"; e.code = "BROWSER_RESTART_REBIND";
      }
      await this.save(s); await this.io.clearAlarm(ALARM); return s;
    }
    if (action === "bind") {
      await this.invalidate(s, "BIND_REQUESTED_EXPLICIT_RETRY");
      const tab = await this.io.selectedTab(); // ONLY explicit Bind uses active tab.
      const canonical = route(tab?.url);
      if (!canonical || tab.incognito || !Number.isInteger(tab.id)) throw new Error("INELIGIBLE_CHAT");
      const generation = this.io.uuid();
      const binding = {tabId:tab.id, route:canonical, generation, project:PROJECT};
      const response = await this.io.page(binding, {op:"bind"});
      if (!response.ok) throw new Error(response.code);
      binding.documentId = response.documentId;
      binding.documentToken = response.documentToken;
      await this.target(binding);
      s.binding = binding;
      const e = this.latest(s);
      if (e && ["queued","paused"].includes(e.status)) {
        e.status = "paused"; e.code = "EXPLICIT_RETRY_REQUIRED";
      }
      await this.save(s); await this.io.clearAlarm(ALARM); return s;
    }
    if (action === "unbind" || action === "cancel") {
      const e = this.latest(s);
      if (e && ["queued","paused"].includes(e.status)) {
        e.status = "cancelled"; e.code = "OPERATOR_CANCELLED_BEFORE_ATTEMPT";
      }
      if (action === "unbind") s.binding = null;
      await this.save(s); await this.io.clearAlarm(ALARM); return s;
    }
    if (action === "inspect") {
      let check;
      try { await this.target(s.binding); check = await this.io.page(s.binding, {op:"prepare"}); }
      catch { return this.invalidate(s, "INSPECTION_ACCESS_UNKNOWN_REBIND"); }
      if (!check.ok && check.code.includes("REBIND")) return this.invalidate(s, check.code);
      return {...s, inspection:check.ok ? "READY_FOR_EXPLICIT_ARM" : check.code};
    }
    if (action === "confirm") {
      const e = this.latest(s);
      if (!e || e.status !== "attempted_unknown" || arg.id !== e.id) throw new Error("CONFIRM_EXACT_MARKER_REQUIRED");
      e.status = "operator_confirmed"; e.code = "OPERATOR_REPORTED_MARKER_RECEIPT";
      await this.save(s); return s; // Human assertion, never transcript scraping.
    }
    if (action === "arm") {
      if (![0,60000].includes(arg.delayMs)) throw new Error("INVALID_DELAY");
      if (s.events.some(e => ["queued","paused","attempted_unknown"].includes(e.status))) throw new Error("ACTIVE_OR_UNCERTAIN_EVENT_EXISTS");
      if (s.events.length >= LIMIT) throw new Error("HISTORY_FULL_NO_EVICTION");
      try { await this.target(s.binding); }
      catch { return this.invalidate(s, "TARGET_CHANGED_REBIND"); }
      const id = "test-" + this.io.uuid();
      notice(id); // Enforce local fixed-ID grammar, no caller-provided prompt.
      const e = {id, route:s.binding.route, generation:s.binding.generation,
        status:"queued", code:"EXPLICITLY_ARMED", createdAt:this.io.now(), dueAt:this.io.now()+arg.delayMs};
      s.events.push(e);
      await this.save(s);
      if (arg.delayMs) {
        try { await this.io.alarm(ALARM, e.dueAt); }
        catch { return this.pause(s, e, "ALARM_UNAVAILABLE_EXPLICIT_RETRY"); }
        return s;
      }
      return this.attempt(s, e);
    }
    if (action === "retry") {
      const e = this.latest(s);
      if (!e || !["queued","paused"].includes(e.status)) throw new Error("NOT_SAFE_TO_RETRY");
      await this.target(s.binding);
      if (e.route !== s.binding.route) throw new Error("EVENT_CHAT_MISMATCH");
      await this.io.clearAlarm(ALARM);
      e.generation = s.binding.generation; e.status = "queued"; e.code = "EXPLICIT_RETRY";
      await this.save(s); return this.attempt(s, e);
    }
    if (action === "alarm") {
      const e = this.latest(s);
      if (!e || e.status !== "queued") return s;
      if (this.io.now() < e.dueAt) return s;
      return this.attempt(s, e);
    }
    throw new Error("UNKNOWN_ACTION");
  }
  async attempt(s, e) {
    const binding = s.binding;
    if (!binding || e.generation !== binding.generation || e.route !== binding.route)
      return this.pause(s, e, "REBIND_REQUIRED");
    let prepared;
    try {
      await this.target(binding);
      prepared = await this.io.page(binding, {op:"prepare"});
    } catch { return this.pause(s, e, "PREPARE_API_UNAVAILABLE_REBIND"); }
    if (!prepared.ok) return this.pause(s, e, prepared.code);
    // No stale async observation can authorize a later commit.
    const current = await this.load();
    if (current.revision !== s.revision || current.boot !== s.boot ||
        current.binding?.generation !== binding.generation)
      throw new Error("STALE_STATE_NO_ATTEMPT");
    try { await this.target(binding); }
    catch { return this.pause(s, e, "TARGET_CHANGED_REBIND"); }
    e.status = "attempted_unknown"; e.code = "INTENT_SAVED_OUTCOME_UNKNOWN";
    e.intentAt = this.io.now();
    await this.save(s); // MUST be acknowledged before any fill/input/click.
    let result;
    try {
      result = await this.io.page(binding, {op:"commit", eventId:e.id, lease:prepared.lease});
    } catch {
      // A rejected/timed-out injection might still have mutated the page.
      s.binding = null; e.code = "COMMIT_API_UNKNOWN_REBIND";
      await this.save(s); return s;
    }
    if (result.ok && result.stage === "blocked_before_mutation") {
      // A definitive local no-mutation response allows ONLY explicit retry.
      e.status = "paused"; e.code = result.code;
      if (result.code.includes("REBIND")) s.binding = null;
    } else {
      e.code = result.code || "COMMIT_OUTCOME_UNKNOWN";
      if (e.code.includes("REBIND")) s.binding = null;
      // Click, changed prefill, crash or incomplete response never authorizes retry.
    }
    await this.save(s);
    return s;
  }
}
