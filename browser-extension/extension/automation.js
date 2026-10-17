import {Controller} from './controller.js';
import {KEY, ALARM, notice, commitOutcome, route} from './policy.js';
import {POLL, validCompletion, completionId, completionMessage, noticeItem, mergedNotice} from './completion-policy.js';

const waiting = e => ['queued','waiting'].includes(e.status);
const attributed = e => typeof e.route==='string' && !!e.route && route(e.route)===e.route;
const neverAttempted = e => waiting(e) && attributed(e) &&
  !['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode'].some(k=>Object.hasOwn(e,k));
const memberFor = (a,e,id) => a.deliveries.find(x=>
  x.epoch===e.epoch && x.route===e.route && completionId(x)===id);
const groupMembers = (a,e) => e.merge?e.merge.map(item=>memberFor(a,e,item.id)):[e];
function requireAttributedUnknown(s) {
  if([...s.events,...(s.automation?.deliveries || [])].some(e=>e.status==='attempted_unknown' && !attributed(e)))
    throw Error('DELIVERY_UNATTRIBUTED_UNKNOWN');
}

// One serialized controller owns synthetic and real events. A saved intent is never retried.
export class Automation extends Controller {
  async load(options) {
    const s=await super.load(options), a=s.automation;
    if(a && (typeof a.enabled!=='boolean' || route(a.route)!==a.route || !Array.isArray(a.deliveries) ||
      a.deliveries.length>128 || !Number.isSafeInteger(a.cursor) || a.cursor<0 ||
      ![0,60000].includes(a.delayMs) || new Set(a.deliveries.map(e=>e.epoch+completionId(e))).size!==a.deliveries.length ||
      a.deliveries.some(e=>!validCompletion(e,this.project) || !['queued','waiting','attempted_unknown','received','closed_before_send','unavailable'].includes(e.status))))
      throw Error('AUTOMATION_STATE_INVALID_NO_RESET');
    if(a?.deliveries.some(e=>e.merge && e.merge.some((item,i)=>{
      const member=a.deliveries.find(x=>completionId(x)===item.id && x.epoch===e.epoch);
      return !member || member.route!==e.route || member.noticeVersion!==e.noticeVersion ||
        (i===0 ? member!==e : member.mergedInto!==completionId(e)) ||
        JSON.stringify(noticeItem(member).workRefs)!==JSON.stringify(item.workRefs) ||
        member.status!==e.status;
    }) || e.mergedInto && !a.deliveries.some(x=>x.merge?.some(y=>y.id===completionId(e)) &&
      completionId(x)===e.mergedInto && x.epoch===e.epoch)))
      throw Error('AUTOMATION_GROUP_INVALID_NO_RESET');
    return s;
  }
  async dispatch(action,arg={}) {
    if(action==='arm') {const current=await this.load();if(current.automation?.enabled || current.automation?.deliveries.some(e=>e.status==='attempted_unknown'))throw Error('AUTOMATION_ACTIVE_OR_UNKNOWN');}
    if(!['enable','disable','tick','verify','close_delivery'].includes(action)) {
      const s=await super.dispatch(action,arg);
      if(action==='unbind' && s.automation) {s.automation.enabled=false;await this.save(s);}
      return s;
    }
    let s=await this.load(action==='enable'?{deferLifecycle:true}:undefined);
    if(action==='enable') {
      if(![0,60000].includes(arg.delayMs)) throw Error('INVALID_DELAY');
      requireAttributedUnknown(s);
      const original=JSON.stringify(s);
      const selected=await this.io.selectedTab();
      const canonical=route(selected?.url);
      if(!canonical || selected.incognito || !Number.isInteger(selected.id))throw Error('INELIGIBLE_CHAT');
      // ProjectControllers pins this selection before acquiring both route locks.
      if(arg.recipient && (arg.recipient.tabId!==selected.id || arg.recipient.route!==canonical))
        throw Error('RECIPIENT_SELECTION_CHANGED');
      const previous=s.automation;
      // Keep attempted/frozen rows pinned to their original Chat. Only clean,
      // attributable real backlog follows the explicitly selected future receiver.
      const pending=(previous?.deliveries || []).filter(waiting);
      if(pending.some(e=>!attributed(e)))throw Error('RECIPIENT_SWITCH_REAL_FROZEN');
      const moving=pending.filter(e=>e.route!==canonical && neverAttempted(e));
      let feed;
      if(!previous) {feed=await this.io.feed();if(!this.validFeed(feed))throw Error('FEED_INVALID');}
      const binding={tabId:selected.id,route:canonical,generation:this.io.uuid(),project:this.project};
      const validateRecipient=async()=>{
        const current=await this.io.selectedTab();
        if(current?.id!==selected.id || current.incognito || route(current.url)!==canonical)
          throw Error('RECIPIENT_SELECTION_CHANGED');
        await this.target(binding);
        const tabs=await this.io.exactTabs(canonical);
        if(tabs.length!==1 || tabs[0].id!==selected.id || tabs[0].incognito)throw Error('TARGET_NOT_UNIQUE_OR_OPEN');
      };
      await validateRecipient();
      const response=await this.io.page(binding,{op:'bind'});
      if(!response?.ok)throw Error(response?.code || 'BIND_RESULT_UNKNOWN');
      if(typeof response.documentId!=='string' || !response.documentId ||
        typeof response.documentToken!=='string' || !response.documentToken)throw Error('BIND_RESULT_UNKNOWN');
      binding.documentId=response.documentId;binding.documentToken=response.documentToken;
      await validateRecipient();
      const current=await this.io.read(KEY);
      if(current===undefined?s.revision!==0:JSON.stringify(current)!==original)throw Error('STALE_STATE_NO_ATTEMPT');
      const boot=await this.io.boot();
      await validateRecipient();
      // Stage the former load/bind lifecycle effects in this same publication.
      // Synthetic identities, routes and attempted/settled evidence stay intact.
      if(s.boot!==boot)for(const e of s.events)if(['queued','paused'].includes(e.status)) {
        e.status='paused';e.code='BROWSER_RESTART_REBIND';
      }
      const latest=this.latest(s);
      if(latest && ['queued','paused'].includes(latest.status)) {
        latest.status='paused';latest.code='EXPLICIT_RETRY_REQUIRED';
      }
      s.boot=boot;
      s.binding=binding;
      for(const e of moving)e.route=canonical;
      // Preserve polling position even across recipient/epoch changes. The next
      // normal tick reconciles the epoch and consumes published-but-unpolled Work.
      s.automation={...previous,enabled:true,route:canonical,epoch:previous?previous.epoch:feed.epoch,
        cursor:previous?previous.cursor:feed.latest,delayMs:arg.delayMs,deliveries:previous?.deliveries || [],error:null};
      await this.save(s); // One coherent publication; never retry/roll back an unknown write.
      await this.io.clearAlarm(ALARM);await this.io.pollAlarm(POLL);await this.io.reportStatus(s).catch(()=>{});return s;
    }
    const a=s.automation;
    if(!a) throw Error('AUTOMATION_NOT_ENABLED');
    if(action==='disable') {a.enabled=false;await this.save(s);await this.io.clearAlarm(POLL);await this.io.reportStatus(s).catch(()=>{});return s;}
    if(action==='close_delivery') {
      const matches=a.deliveries.filter(e=>completionId(e)===arg.id);
      if(matches.length>1)throw Error('DELIVERY_ID_AMBIGUOUS');
      const e=matches[0];
      if(!e || e.status!=='attempted_unknown' || e.outcome!=='preclick_stop') throw Error('CLOSE_REQUIRES_PRECLICK_EVIDENCE');
      const owner=e.mergedInto?memberFor(a,e,e.mergedInto):e;
      if(!owner)throw Error('AUTOMATION_GROUP_INVALID_NO_RESET');
      const group=groupMembers(a,owner);
      if(group.some(x=>x?.status!=='attempted_unknown'||x.outcome!=='preclick_stop'))throw Error('CLOSE_REQUIRES_PRECLICK_EVIDENCE');
      for(const x of group)x.status='closed_before_send';
      await this.save(s);return s;
    }
    if(action==='verify') {await this.verify(s);return s;}
    if(!a.enabled)return s;
    try {
      // A lost recipient is uncertainty about every Chat, not evidence of another route.
      requireAttributedUnknown(s);
      const feed=await this.io.feed({after:a.cursor,epoch:a.epoch});
      if(!this.validFeed(feed))throw Error('FEED_INVALID');
      if(feed.epoch!==a.epoch) {
        for(const e of a.deliveries)if(neverAttempted(e)){e.status='unavailable';e.code='BRIDGE_RESTART_REPORT_UNAVAILABLE';}
        a.epoch=feed.epoch;a.cursor=0;
        await this.save(s);return s;
      }
      if(feed.cursor<a.cursor)throw Error('FEED_CURSOR_REGRESSION');
      // Epoch changes never authorize another notification for a retained identity.
      const fresh=feed.events.filter(e=>!a.deliveries.some(d=>completionId(d)===completionId(e)));
      if(fresh.some(e=>e.sequence<=a.cursor))throw Error('FEED_EVENT_REPLAY');
      // Completed diagnostic rows can expire; the monotonic cursor remains authoritative.
      while(a.deliveries.length+fresh.length>128) {
        const i=a.deliveries.findIndex(e=>['received','closed_before_send','unavailable'].includes(e.status) && !e.mergedInto &&
          // An unsent copy still needs this evidence for the duplicate-ID guard.
          groupMembers(a,e).every(x=>x && x.status===e.status &&
            !a.deliveries.some(other=>waiting(other) && completionId(other)===completionId(x))));
        if(i<0)throw Error('DELIVERY_HISTORY_FULL');
        const evicted=a.deliveries[i],ids=new Set(groupMembers(a,evicted).map(completionId));
        a.deliveries=a.deliveries.filter(x=>x.epoch!==evicted.epoch || x.route!==evicted.route || !ids.has(completionId(x)));
      }
      for(const e of fresh)a.deliveries.push({...e,epoch:feed.epoch,status:'queued',code:'REPORT_READY',
        route:a.route,createdAt:this.io.now(),dueAt:this.io.now()+a.delayMs});
      a.cursor=feed.cursor;a.error=feed.blocked?'REPORT_READ_TEMPORARY':null;a.lastPoll=this.io.now();await this.save(s);
      await this.ensureBinding(s);
      await this.verify(s);
      // Old-route evidence remains unresolved, but cannot freeze another Chat.
      if([...s.events,...a.deliveries].some(e=>e.route===a.route && e.status==='attempted_unknown'))return s;
      const candidates=a.deliveries.filter(e=>e.route===a.route && neverAttempted(e) && e.dueAt<=this.io.now());
      if(candidates.length)await this.deliver(s,candidates);
    } catch(error) {
      a.error=/^[A-Z_]{1,80}$/.test(error?.message||'')?error.message:'BRIDGE_OR_PAGE_UNAVAILABLE';
      await this.save(s);
    } finally {await this.io.reportStatus(s).catch(()=>{});}
    return s;
  }
  validFeed(f) {
    return f && /^[0-9a-f]{32}$/.test(f.epoch) && Number.isSafeInteger(f.cursor) && f.cursor>=0 &&
      (f.reset===true || Number.isSafeInteger(f.latest) && f.latest>=f.cursor) &&
      Array.isArray(f.events) && f.events.length<=16 && f.events.every(e=>validCompletion(e,this.project)) &&
      new Set(f.events.map(completionId)).size===f.events.length &&
      f.events.every((e,i)=>e.sequence<=f.cursor && (!i || e.sequence>f.events[i-1].sequence));
  }
  async ensureBinding(s) {
    const a=s.automation;
    // The persisted user selection is the full route, never a project label or chat UUID.
    const tabs=await this.io.exactTabs(a.route);
    if(tabs.length!==1 || tabs[0].incognito)throw Error('TARGET_NOT_UNIQUE_OR_OPEN');
    if(s.binding?.route===a.route && s.binding.tabId===tabs[0].id) {
      try {
        const view=await this.io.page(s.binding,{op:'prepare'});
        if(view.ok || !view.code.includes('REBIND'))return;
      }catch { /* A full navigation loses the document; obtain a fresh generation below. */ }
    }
    const binding={project:this.project,route:a.route,tabId:tabs[0].id,generation:this.io.uuid()};
    const r=await this.io.page(binding,{op:'bind'});
    if(!r.ok)throw Error(r.code);
    binding.documentId=r.documentId;binding.documentToken=r.documentToken;
    await this.target(binding);s.binding=binding;await this.save(s);
  }
  async verify(s) {
    requireAttributedUnknown(s);
    if(!s.binding)return;
    const a=s.automation;
    for(const e of [...s.events,...a.deliveries]) {
      if(e.status!=='attempted_unknown')continue;
      if(e.mergedInto)continue; // One physical message, owned by the first row.
      const real=Object.hasOwn(e,'work_ref') || Object.hasOwn(e,'batch_ref');
      if(e.route!==s.binding.route)continue;
      const members=real?groupMembers(a,e):[e];
      if(members.some(x=>!x || x.status!=='attempted_unknown'))throw Error('AUTOMATION_GROUP_INVALID_NO_RESET');
      // The visible receipt has no epoch discriminator. Do not reuse same-Chat evidence.
      if(real && members.some(member=>a.deliveries.some(x=>x!==member &&
        x.route===member.route && completionId(x)===completionId(member))))throw Error('DELIVERY_ID_AMBIGUOUS');
      const id=real?completionId(e):e.id,message=real?completionMessage(e):notice(id);
      const r=await this.io.receipt(s.binding,{id,message});
      if(r.ok && r.scope==='chat-user-message-v1' && !r.tooMany && !r.draft && r.notices===1 && (real || r.replies===1)) {
        // Legacy confirmation records DOM evidence, never an invented human assertion.
        for(const member of members) {
          member.status=real?'received':'receipt_confirmed';member.receiptAt=this.io.now();
          member.receipt={scope:r.scope,notices:r.notices,replies:r.replies,turnKeys:r.turnKeys,visibility:r.visibility,focused:r.focused};
          member.receiptCode='EXACT_USER_MESSAGE_OBSERVED';
        }
        await this.save(s);
      }
    }
  }
  async refreshForSend(s,e) {
    const check=await this.io.feed({epoch:e.epoch,check:completionId(e)});
    if(!this.validFeed(check))throw Error('FEED_INVALID');
    if(check.epoch!==e.epoch) {
      e.status='unavailable';e.code='BRIDGE_RESTART_REPORT_UNAVAILABLE';return false;
    }
    const readable=check.events.find(x=>completionId(x)===completionId(e));
    if(!readable) {
      const gone=check.check?.work_ref===completionId(e) && check.check.state==='unavailable' && check.check.code==='WORK_IDENTITY_LOST';
      e.status=gone?'unavailable':'waiting';e.code=gone?'WORK_IDENTITY_LOST':'REPORT_READ_TEMPORARY';return false;
    }
    if(e.batch_ref && (readable.batch_ref!==e.batch_ref || readable.requested!==e.requested ||
      JSON.stringify(readable.members.map(m=>m.work_ref))!==JSON.stringify(e.members.map(m=>m.work_ref))))
      throw Error('BATCH_MEMBERSHIP_CHANGED');
    if(e.batch_ref ? e.members.some((m,i)=>m.report_status==='readable' &&
      readable.members[i].report_status==='readable' && readable.members[i].report_sha256!==m.report_sha256) :
      readable.report_sha256!==e.report_sha256) {
      e.status='unavailable';e.code='REPORT_VERSION_CHANGED';return false;
    }
    if(e.batch_ref)e.members=readable.members;
    return true;
  }
  async deliver(s,candidates) {
    requireAttributedUnknown(s);
    const b=s.binding;
    if(!b || b.route!==s.automation.route || candidates.some(e=>e.route!==b.route))throw Error('DELIVERY_ROUTE_MISMATCH');
    if(candidates.some(e=>!neverAttempted(e)))throw Error('DELIVERY_ALREADY_ATTEMPTED');
    if(candidates.some(e=>s.automation.deliveries.some(x=>completionId(x)===completionId(e) &&
      (x.epoch!==e.epoch || x.route!==e.route))))throw Error('DELIVERY_ID_AMBIGUOUS');
    let selected=[];
    for(const e of candidates) {
      if(await this.refreshForSend(s,e))selected.push(e);
    }
    if(!selected.length){await this.save(s);return;}
    if(!selected[0].merge && selected.length>1) {
      while(selected.length>1) {
        try {mergedNotice(selected.map(noticeItem));break;}
        catch(error) {if(error?.message!=='MERGED_NOTICE_TOO_LONG')throw error;selected.pop();}
      }
    }
    await this.target(b);
    const ready=await this.io.page(b,{op:'prepare'});
    if(!ready.ok){for(const e of selected){e.status='waiting';e.code=ready.code;}await this.save(s);return;}
    const current=await this.load();
    requireAttributedUnknown(current);
    if(current.revision!==s.revision || current.binding?.generation!==b.generation || !current.automation.enabled)
      throw Error('STALE_STATE_NO_ATTEMPT');
    await this.target(b);
    const observedTab=await this.io.tab(b.tabId);
    if(observedTab.url!==b.route || observedTab.incognito)throw Error('TARGET_CHANGED_REBIND');
    const owner=selected[0], merged=selected.length>1;
    if(merged && !owner.merge) {
      owner.merge=selected.map(noticeItem);
      for(const e of selected.slice(1))e.mergedInto=completionId(owner);
    }
    for(const e of selected) {
      e.pageAtPrepare={visibility:ready.visibility,focused:ready.focused,tabActive:observedTab.active ?? null,observedAt:this.io.now()};
      // Pin the exact grouped recipient and format in the same durable intent.
      if(e.noticeVersion===undefined && e.intentAt===undefined)e.noticeVersion=this.io.noticeVersion || (merged?3:2);
      e.status='attempted_unknown';e.outcome='unknown';e.code='INTENT_SAVED_OUTCOME_UNKNOWN';e.intentAt=this.io.now();
    }
    await this.save(s);
    try {
      const r=await this.io.page(b,{op:'commit',eventId:completionId(owner),
        ...(merged?{merge:owner.merge}:{reportSha:owner.report_sha256,
          ...(owner.batch_ref?{batch:{batch_ref:owner.batch_ref,project_ref:owner.project_ref,
            requested:owner.requested,not_submitted:owner.not_submitted,members:owner.members}}:{})}),
        noticeVersion:(owner.noticeVersion===undefined?1:owner.noticeVersion),lease:ready.lease});
      const outcome=commitOutcome(r,b.documentId),code=/^[A-Z_]{1,80}$/.test(r?.code||'')?r.code:'COMMIT_OUTCOME_UNKNOWN';
      for(const e of selected) {
        e.outcome=outcome;e.code=code;
        if(['blocked_before_mutation','rolled_back_before_click'].includes(outcome))e.status='waiting';
      }
    }catch {for(const e of selected)e.code='COMMIT_API_UNKNOWN_NO_RETRY';}
    await this.save(s);
    // Receipt is observed on a later wakeup. No retry, even if this worker disappears now.
  }
}
