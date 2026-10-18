import {Controller} from './controller.js';
import {KEY, ALARM, commitOutcome, route} from './policy.js';
import {POLL, validCompletion, completionId, noticeItem, mergedNotice} from './completion-policy.js';

const waiting = e => ['queued','waiting'].includes(e.status);
const attributed = e => typeof e.route==='string' && !!e.route && route(e.route)===e.route;
export const pending = e => waiting(e) && !['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode'].some(k=>Object.hasOwn(e,k));
const neverAttempted = e => pending(e) && attributed(e);
const validId = id => typeof id==='string' && /^(?:work|batch)-[0-9a-f]{16}$/.test(id);
const validEpoch = epoch => typeof epoch==='string' && /^[0-9a-f]{32}$/.test(epoch);
// One serialized controller owns synthetic and real events. A saved intent is never retried.
export class Automation extends Controller {
  async load(options) {
    const s=await super.load(options);
    if(s.automation && this.normalizeQueue(s.automation))await super.save(s);
    return s;
  }
  normalizeQueue(a) {
    if(typeof a.enabled!=='boolean' || !a.route || route(a.route)!==a.route || !Array.isArray(a.deliveries) ||
      !validEpoch(a.epoch) ||
      !Number.isSafeInteger(a.cursor) || a.cursor<0 ||
      ![0,60000].includes(a.delayMs) ||
      (a.consumed!==undefined && (!Array.isArray(a.consumed) ||
        a.consumed.some(id=>!validId(id)) || new Set(a.consumed).size!==a.consumed.length)) ||
      a.deliveries.some(e=>!e || e.project_ref!==this.project || !validId(completionId(e)) ||
        !['queued','waiting','attempted_unknown','received','handled','closed_before_send','unavailable'].includes(e.status) ||
        pending(e) && (!validEpoch(e.epoch) || !validCompletion(e,this.project))))
      throw Error('AUTOMATION_STATE_INVALID_NO_RESET');
    const before=JSON.stringify(a), consumed=new Set(a.consumed || []), seen=new Set();
    for(const e of a.deliveries) {
      const id=completionId(e);
      // Multiple raw identities cannot become safe merely by resetting epochs.
      if(seen.has(id) || !pending(e))consumed.add(id);
      seen.add(id);
      if(!pending(e)) {
        // Discarded history's links are not live topology. Suppress every known
        // group identity even if its old owner/child pointers disagree.
        if(validId(e.mergedInto))consumed.add(e.mergedInto);
        if(Array.isArray(e.merge))for(const item of e.merge)if(validId(item?.id))consumed.add(item.id);
      }
    }
    a.deliveries=a.deliveries.filter(e=>pending(e) && !consumed.has(completionId(e)));
    a.consumed=[...consumed];
    if(['DELIVERY_HISTORY_FULL','DELIVERY_UNATTRIBUTED_UNKNOWN'].includes(a.error) ||
      a.error==='PENDING_QUEUE_FULL' && !a.deliveries.length)a.error=null;
    return before!==JSON.stringify(a);
  }
  async saveQueue(s) {
    if(s.automation)this.normalizeQueue(s.automation);
    await super.save(s);
  }
  async dispatch(action,arg={}) {
    if(action==='arm') {const current=await this.load();if(current.automation?.enabled)throw Error('AUTOMATION_ACTIVE_OR_UNKNOWN');}
    if(!['enable','disable','tick','draft_choice'].includes(action)) {
      const oldBinding=['bind','unbind'].includes(action)?(await this.load()).binding:null;
      const s=await super.dispatch(action,arg);
      if(action==='unbind' && s.automation) {s.automation.enabled=false;await this.saveQueue(s);}
      if(oldBinding)await this.dismissDraft(oldBinding);
      return s;
    }
    let s=await this.load(action==='enable'?{deferLifecycle:true}:undefined);
    if(action==='enable') {
      if(![0,60000].includes(arg.delayMs)) throw Error('INVALID_DELAY');
      const original=JSON.stringify(s);
      const selected=await this.io.selectedTab();
      const canonical=route(selected?.url);
      if(!canonical || selected.incognito || !Number.isInteger(selected.id))throw Error('INELIGIBLE_CHAT');
      // ProjectControllers pins this selection before acquiring both route locks.
      if(arg.recipient && (arg.recipient.tabId!==selected.id || arg.recipient.route!==canonical))
        throw Error('RECIPIENT_SELECTION_CHANGED');
      const previous=s.automation, oldBinding=s.binding;
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
        cursor:previous?previous.cursor:feed.latest,delayMs:arg.delayMs,deliveries:previous?.deliveries || [],consumed:previous?.consumed || [],error:null};
      await this.saveQueue(s); // One coherent publication; never retry/roll back an unknown write.
      if(oldBinding && oldBinding.route!==binding.route)await this.dismissDraft(oldBinding);
      await this.io.clearAlarm(ALARM);await this.io.pollAlarm(POLL);await this.io.reportStatus(s).catch(()=>{});return s;
    }
    const a=s.automation;
    if(!a) throw Error('AUTOMATION_NOT_ENABLED');
    if(action==='disable') {a.enabled=false;await this.saveQueue(s);await this.dismissDraft(s.binding);await this.io.clearAlarm(POLL);await this.io.reportStatus(s).catch(()=>{});return s;}
    if(action==='draft_choice') {
      const b=s.binding, source=arg.source;
      if(!a.enabled || !b || b.route!==a.route || !source || source.tabId!==b.tabId ||
        source.documentId!==b.documentId || source.url!==b.route)throw Error('DRAFT_CHOICE_SOURCE_CHANGED');
      const candidates=a.deliveries.filter(e=>e.route===a.route && neverAttempted(e) && e.dueAt<=this.io.now());
      if(!candidates.length)throw Error('DRAFT_CHOICE_STALE');
      if(await this.deliver(s,candidates,arg)!==true)throw Error('DRAFT_CHOICE_UNCONFIRMED_NO_RETRY');
      return s;
    }
    if(!a.enabled)return s;
    try {
      const feed=await this.io.feed({after:a.cursor,epoch:a.epoch});
      if(!this.validFeed(feed))throw Error('FEED_INVALID');
      if(feed.epoch!==a.epoch) {
        // A new epoch resets sequence progress, not proof that unsent Work is
        // gone. Recheck its identity/report against the new producer before use.
        for(const e of a.deliveries)e.epoch=feed.epoch;
        a.epoch=feed.epoch;a.cursor=0;
        await this.saveQueue(s);await this.dismissDraft(s.binding);return s;
      }
      if(feed.cursor<a.cursor)throw Error('FEED_CURSOR_REGRESSION');
      // Epoch changes never authorize another notification for a retained identity.
      const fresh=feed.events.filter(e=>!a.consumed.includes(completionId(e)) && !a.deliveries.some(d=>completionId(d)===completionId(e)));
      if(fresh.some(e=>e.sequence<=a.cursor))throw Error('FEED_EVENT_REPLAY');
      // Only live, never-attempted workload occupies this resource bound.
      const full=a.deliveries.length+fresh.length>128;
      if(!full)for(const e of fresh)a.deliveries.push({...e,epoch:feed.epoch,status:'queued',code:'REPORT_READY',
        route:a.route,createdAt:this.io.now(),dueAt:this.io.now()+a.delayMs});
      if(!full)a.cursor=feed.cursor;
      a.error=full?'PENDING_QUEUE_FULL':feed.blocked?'REPORT_READ_TEMPORARY':null;
      a.lastPoll=this.io.now();await this.saveQueue(s);
      const candidates=a.deliveries.filter(e=>e.route===a.route && neverAttempted(e) && e.dueAt<=this.io.now());
      if(candidates.length) {await this.ensureBinding(s);await this.deliver(s,candidates);}
    } catch(error) {
      a.error=/^[A-Z_]{1,80}$/.test(error?.message||'')?error.message:'BRIDGE_OR_PAGE_UNAVAILABLE';
      await this.saveQueue(s);
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
  async dismissDraft(binding) {
    if(binding)try {
      await this.target(binding);
      const r=await this.io.page(binding,{op:'draft_dismiss'});
      return r?.ok===true && r.documentId===binding.documentId && Object.keys(r).sort().join(',')==='documentId,ok';
    }catch { /* An uncertain dismissal cannot authorize choice recovery. */ }
    return false;
  }
  async choiceTarget(binding) {
    await this.target(binding);
    const tabs=await this.io.exactTabs(binding.route);
    if(tabs.length!==1 || tabs[0].id!==binding.tabId || tabs[0].incognito)
      throw Error('TARGET_NOT_UNIQUE_OR_OPEN');
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
    await this.target(binding);s.binding=binding;await this.saveQueue(s);
  }
  async refreshForSend(s,e) {
    const currentEpoch=s.automation.epoch;
    const check=await this.io.feed({epoch:currentEpoch,check:completionId(e)});
    if(!this.validFeed(check))throw Error('FEED_INVALID');
    if(check.epoch!==currentEpoch) {
      e.status='waiting';e.code='PRODUCER_EPOCH_CHANGED_WAIT_NEXT_POLL';return false;
    }
    const readable=check.events.find(x=>completionId(x)===completionId(e));
    if(!readable) {
      const gone=check.check?.work_ref===completionId(e) && check.check.state==='unavailable' && check.check.code==='WORK_IDENTITY_LOST';
      e.status=gone?'unavailable':'waiting';e.code=gone?'WORK_IDENTITY_LOST':'REPORT_READ_TEMPORARY';return false;
    }
    if(e.batch_ref && (readable.batch_ref!==e.batch_ref || readable.requested!==e.requested ||
      JSON.stringify(readable.members.map(m=>m.work_ref))!==JSON.stringify(e.members.map(m=>m.work_ref)))) {
      e.status='unavailable';e.code='BATCH_MEMBERSHIP_CHANGED';return false;
    }
    if(e.batch_ref ? e.members.some((m,i)=>m.report_status==='readable' &&
      readable.members[i].report_status==='readable' && readable.members[i].report_sha256!==m.report_sha256) :
      readable.report_sha256!==e.report_sha256) {
      e.status='unavailable';e.code='REPORT_VERSION_CHANGED';return false;
    }
    if(e.batch_ref)e.members=readable.members;
    e.epoch=currentEpoch;
    return true;
  }
  async deliver(s,candidates,choice=null) {
    const b=s.binding;
    if(!b || b.route!==s.automation.route || candidates.some(e=>e.route!==b.route))throw Error('DELIVERY_ROUTE_MISMATCH');
    if(candidates.some(e=>!neverAttempted(e)))throw Error('DELIVERY_ALREADY_ATTEMPTED');
    if(candidates.some(e=>s.automation.deliveries.some(x=>completionId(x)===completionId(e) &&
      (x.epoch!==e.epoch || x.route!==e.route))))throw Error('DELIVERY_ID_AMBIGUOUS');
    let selected=[];
    for(const e of candidates) {
      if(await this.refreshForSend(s,e))selected.push(e);
    }
    if(!selected.length){await this.saveQueue(s);return;}
    if(!selected[0].merge && selected.length>1) {
      while(selected.length>1) {
        try {mergedNotice(selected.map(noticeItem));break;}
        catch(error) {if(error?.message!=='MERGED_NOTICE_TOO_LONG')throw error;selected.pop();}
      }
    }
    const owner=selected[0], merged=selected.length>1;
    const packet={eventId:completionId(owner),
      ...(merged?{merge:selected.map(noticeItem)}:{reportSha:owner.report_sha256,
        ...(owner.batch_ref?{batch:{batch_ref:owner.batch_ref,project_ref:owner.project_ref,
          requested:owner.requested,not_submitted:owner.not_submitted,members:owner.members}}:{})}),
      noticeVersion:owner.noticeVersion ?? this.io.noticeVersion ?? (merged?3:2)};
    await this.target(b);
    if(choice)await this.choiceTarget(b);
    const ready=await this.io.page(b,choice?{...packet,op:'draft_prepare',token:choice.token}:{op:'prepare'});
    if(!ready.ok){
      let code=ready.code;
      if(!choice && code==='DRAFT_PRESENT') {
        // Detecting a draft is not proof that its page-local offer was shown.
        // An unsuccessful offer remains unattempted and can be rechecked by the
        // normal poll; never hide its refusal behind a stale DRAFT_PRESENT.
        let offer;
        try {offer=await this.io.page(b,{...packet,op:'draft_offer'});} catch { /* No draft mutation is requested. */ }
        code=offer?.documentId===b.documentId && offer.ok===true && offer.code==='DRAFT_CHOICE_PENDING'?
          'DRAFT_CHOICE_PENDING':offer?.ok===false && /^[A-Z_]{1,80}$/.test(offer.code || '')?
            offer.code:'DRAFT_CHOICE_UNCONFIRMED';
      }
      for(const e of selected){e.status='waiting';e.code=code;}await this.saveQueue(s);
      // No intent/commit was issued. Only a positively refused, exact-document
      // read-only preparation permits retirement after the waiting save ACK.
      if(choice && ready.ok===false && ready.documentId===b.documentId &&
        Object.keys(ready).sort().join(',')==='code,documentId,ok' &&
        (['DRAFT_CHOICE_STALE','DRAFT_CHANGED'].includes(ready.code) ||
          commitOutcome({...ready,ok:true,stage:'blocked_before_mutation'},b.documentId)==='blocked_before_mutation'))
        await this.dismissDraft(b);
      return;
    }
    const current=await this.load();
    if(current.revision!==s.revision || current.binding?.generation!==b.generation || !current.automation.enabled)
      throw Error('STALE_STATE_NO_ATTEMPT');
    await this.target(b);
    const observedTab=await this.io.tab(b.tabId);
    if(observedTab.url!==b.route || observedTab.incognito)throw Error('TARGET_CHANGED_REBIND');
    if(merged && !owner.merge) {
      owner.merge=selected.map(noticeItem);
      for(const e of selected.slice(1))e.mergedInto=completionId(owner);
    }
    for(const e of selected) {
      // Freeze this page request locally; only its identities persist at intent.
      if(e.noticeVersion===undefined && e.intentAt===undefined)e.noticeVersion=this.io.noticeVersion || (merged?3:2);
      e.status='attempted_unknown';e.outcome='unknown';e.code=choice?'DRAFT_CHOICE_OUTCOME_UNKNOWN':'INTENT_SAVED_OUTCOME_UNKNOWN';e.intentAt=this.io.now();
    }
    await this.saveQueue(s);
    let r;
    try {
      if(choice)await this.choiceTarget(b);
      r=await this.io.page(b,{op:choice?'draft_commit':'commit',...(choice?{token:choice.token}:{}),eventId:completionId(owner),
        ...(merged?{merge:owner.merge}:{reportSha:owner.report_sha256,
          ...(owner.batch_ref?{batch:{batch_ref:owner.batch_ref,project_ref:owner.project_ref,
            requested:owner.requested,not_submitted:owner.not_submitted,members:owner.members}}:{})}),
        noticeVersion:(owner.noticeVersion===undefined?1:owner.noticeVersion),lease:ready.lease});
    }catch {return choice?false:undefined;} // An uncertain invocation is already suppressed.
    // The consumed identities were acknowledged before entering the page.
    // No terminal history write or backend acknowledgement follows the click.
    // Draft-only refusals emitted before mutation by the adapter use the same
    // exact envelope as the existing Send guard responses.
    const blockedDraft=choice && r?.ok===true && r.documentId===b.documentId &&
      Object.keys(r).sort().join(',')==='code,documentId,ok,stage' && r.stage==='blocked_before_mutation' &&
      ['DRAFT_CHOICE_STALE','DRAFT_CHANGED'].includes(r.code);
    if(blockedDraft || commitOutcome(r,b.documentId)==='blocked_before_mutation') {
      // Only an exact no-mutation result can restore genuinely unfinished work.
      // Lost/invalid ACKs, rollbacks and all ambiguous effects stay suppressed.
      // Retire the clicked token before publishing a recoverable choice. No
      // reoffer or mutation happens here, including when this save has no ACK.
      if(choice && !await this.dismissDraft(b))return false;
      const ids=new Set(selected.map(completionId));
      s.automation.consumed=s.automation.consumed.filter(id=>!ids.has(id));
      for(const e of selected) {
        for(const key of ['intentAt','outcome','pageAtPrepare','merge','mergedInto'])delete e[key];
        if(e.noticeVersion===3)delete e.noticeVersion;
        e.status='waiting';e.code=r.code;s.automation.deliveries.push(e);
      }
      await this.saveQueue(s);
    }
    if(choice)return r?.ok===true && Object.keys(r).sort().join(',')==='code,documentId,ok,stage' &&
      r.documentId===b.documentId && r.stage==='handled' && r.code==='DRAFT_NOTIFICATION_HANDLED';
  }
}
