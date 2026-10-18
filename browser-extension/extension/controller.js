import {validSlotSnapshot} from "./slot-diagnostic.js";
import {PROJECT, LIMIT, KEY, ALARM, route, notice, validState, commitOutcome, preclickEvidence} from "./policy.js";

// The promise chain serializes one live worker only. All authoritative records
// live in storage; a dead worker's intent is never inferred to be unsent.
export class Controller {
  constructor(io) { this.io = io; this.project = io.project || PROJECT; this.chain = Promise.resolve(); }
  run(action, arg) {
    const job = this.chain.then(() => this.dispatch(action, arg));
    this.chain = job.catch(() => {});
    return job;
  }
  async load({deferLifecycle=false} = {}) {
    const boot = await this.io.boot();
    let s = await this.io.read(KEY);
    if (s === undefined) {
      s = {schema:1, boot, revision:0, binding:null, events:[]};
      if (!deferLifecycle) await this.save(s);
    }
    if (!validState(s) || s.binding && s.binding.project!==this.project) throw new Error("STATE_INVALID_NO_RESET");
    // Explicit automation enable publishes boot/binding/recipient together, or
    // leaves the prior record untouched if recipient validation fails.
    if (s.boot !== boot && !deferLifecycle) {
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
  async inspectSlot(s, e) {
    const refused = inspection => ({...s, inspection});
    if (!validState(s) || s.events.filter(x => x.status === "attempted_unknown").length !== 1 ||
        this.latest(s) !== e || e.status !== "attempted_unknown" ||
        e.code !== "ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY")
      return refused("SLOT_DIAGNOSTIC_EVENT_UNAVAILABLE_NO_RETRY");
    try {
      const selected = await this.io.selectedTab();
      if (!selected || selected.incognito || !Number.isInteger(selected.id) || route(selected.url) !== e.route)
        return refused("SLOT_DIAGNOSTIC_TARGET_MISMATCH_NO_RETRY");
      const target = {tabId:selected.id, route:e.route};
      await this.target(target);
      const result = await this.io.slotDiagnostic(target);
      await this.target(target);
      const after = await this.io.selectedTab();
      if (!after || after.id !== selected.id || after.incognito || route(after.url) !== e.route)
        return refused("SLOT_DIAGNOSTIC_TARGET_CHANGED_NO_RETRY");
      const current = await this.io.read(KEY);
      if (!validState(current) || JSON.stringify(current) !== JSON.stringify(s))
        return refused("SLOT_DIAGNOSTIC_STATE_CHANGED_NO_RETRY");
      if (!result || result.ok !== true || !validSlotSnapshot(result.snapshot))
        return refused("SLOT_DIAGNOSTIC_RESULT_UNAVAILABLE_NO_RETRY");
      return {...s, inspection:"SLOT_DIAGNOSTIC_CURRENT_ONLY_UNKNOWN_NO_RETRY", slotDiagnostic:result.snapshot};
    } catch {
      return refused("SLOT_DIAGNOSTIC_ACCESS_OR_RESULT_UNAVAILABLE_NO_RETRY");
    }
  }
  async dispatch(action, arg = {}) {
    // Unknown-event Inspect is read-only even after onInstalled/startup/boot loss.
    // Do not call load()/boot(), initialize storage, restore binding or clear alarms here.
    if (action === "inspect") {
      const existing = await this.io.read(KEY);
      if (existing !== undefined && !validState(existing)) throw new Error("STATE_INVALID_NO_RESET");
      if (existing?.events.some(e => e.status === "attempted_unknown"))
        return this.inspectSlot(existing, this.latest(existing));
    }

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
      const tab = await this.io.selectedTab(); // Send binding is still selected ONLY by explicit Bind.
      const canonical = route(tab?.url);
      if (!canonical || tab.incognito || !Number.isInteger(tab.id)) throw new Error("INELIGIBLE_CHAT");
      const generation = this.io.uuid();
      const binding = {tabId:tab.id, route:canonical, generation, project:this.project};
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
      if (action === "cancel") {
        if (!e || arg.id !== e.id) throw new Error("CANCEL_EVENT_CHANGED_REFRESH_STATUS");
        if (e.status === "attempted_unknown") {
          const evidence = preclickEvidence(e);
          if (!evidence) throw new Error("CANCEL_REQUIRES_PRECLICK_EVIDENCE");
          e.status = "closed_before_send"; e.outcome = evidence;
          // Preserve id/route/code/intent/timestamps. This is not receipt or retry permission.
          await this.save(s); return s;
        }
        if (e.status === "closed_before_send") return s;
      }
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
    if (action === "arm") {
      if (![0,60000].includes(arg.delayMs)) throw new Error("INVALID_DELAY");
      if (s.events.some(e => ["queued","paused","attempted_unknown"].includes(e.status))) throw new Error("ACTIVE_OR_UNCERTAIN_EVENT_EXISTS");
      if (s.events.length >= LIMIT) throw new Error("HISTORY_FULL_NO_EVICTION");
      try { await this.target(s.binding); }
      catch { return this.invalidate(s, "TARGET_CHANGED_REBIND"); }
      if (this.latest(s)?.status === "closed_before_send") {
        // Closure does not clear prefill. A separately armed successor must first
        // pass the existing empty-draft/binding guards before allocating a new ID.
        let ready;
        try { ready = await this.io.page(s.binding, {op:"prepare"}); }
        catch { return this.invalidate(s, "PREPARE_API_UNAVAILABLE_REBIND"); }
        const current = await this.load();
        if (current.revision !== s.revision || current.boot !== s.boot ||
            current.binding?.generation !== s.binding.generation) throw new Error("STALE_STATE_NO_ATTEMPT");
        if (ready?.ok !== true || typeof ready.lease !== "string" || !ready.lease || ready.documentId !== s.binding.documentId)
          return {...s, inspection:typeof ready?.code === "string" && /^[A-Z_]{1,80}$/.test(ready.code) ?
            ready.code : "PREPARE_RESULT_UNKNOWN_NO_NEW_EVENT"};
        await this.target(s.binding);
      }
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
    e.outcome = "unknown"; // Saved before injection; missing/bad results cannot use legacy evidence.
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
    e.outcome = commitOutcome(result, binding.documentId);
    if (e.outcome === "blocked_before_mutation") {
      // A definitive local no-mutation response allows ONLY explicit retry.
      e.status = "paused"; e.code = result.code;
      if (result.code.includes("REBIND")) s.binding = null;
    } else if (e.outcome === "clicked") {
      e.status = "handled"; e.code = "SEND_CLICK_INVOKED";
    } else {
      e.code = e.outcome === "unknown" && result?.stage === "clicked" ? "COMMIT_OUTCOME_UNKNOWN" :
        typeof result?.code === "string" && /^[A-Z_]{1,80}$/.test(result.code) ? result.code : "COMMIT_OUTCOME_UNKNOWN";
      if (e.code.includes("REBIND")) s.binding = null;
      // Even a proved pre-click stop remains attempted until explicit, ID-pinned Cancel.
    }
    await this.save(s);
    return s;
  }
}
