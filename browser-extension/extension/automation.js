import {Controller} from './controller.js';
import {KEY, ALARM, commitOutcome, route} from './policy.js';
import {POLL, validCompletion, completionId, noticeItem, mergedNotice, normalizeNotificationLanguage} from './completion-policy.js';

const waiting = e => ['queued','waiting'].includes(e.status);
const attributed = e => typeof e.route==='string' && !!e.route && route(e.route)===e.route;
export const pending = e => waiting(e) && !['intentAt','outcome','pageAtPrepare','merge','mergedInto','receipt','receiptAt','receiptCode'].some(k=>Object.hasOwn(e,k));
const neverAttempted = e => pending(e) && attributed(e);
const validId = id => typeof id==='string' && /^(?:work|batch)-[0-9a-f]{16}$/.test(id);
const validEpoch = epoch => typeof epoch==='string' && /^[0-9a-f]{32}$/.test(epoch);
const choiceId = id => typeof id==='string' && /^[0-9a-f-]{36}$/.test(id);
export function draftChoiceReply(a,id) {
  const last=a.lastChoice;
  return {ok:true,offerId:id,outcome:last?.id===id?last.outcome:'pending',
    code:last?.id===id?last.code:'DRAFT_CHOICE_PENDING',dismissed:last?.id===id&&last.dismissed===true};
}
const packetFor = (events,noticeVersion,language='zh') => {
  const owner=events[0];
  return {eventId:completionId(owner),noticeVersion,language:normalizeNotificationLanguage(language),
    ...(events.length>1?{merge:events.map(noticeItem)}:
    {reportSha:owner.report_sha256,...(owner.batch_ref?{batch:{batch_ref:owner.batch_ref,project_ref:owner.project_ref,
      requested:owner.requested,not_submitted:owner.not_submitted,members:owner.members}}:{})})};
};
// One serialized controller owns synthetic and real events. A saved intent is never retried.
export class Automation extends Controller {
  async language() {
    try { return normalizeNotificationLanguage(await this.io.notificationLanguage?.()); }
    catch { return 'zh'; }
  }
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
    const scope=this.io.scopeId || this.project;
    const validView=v=>v===null || v && v.project===this.project && Number.isInteger(v.tabId) &&
      route(v.route)===v.route && choiceId(v.generation) && choiceId(v.token) &&
      typeof v.documentId==='string' && !!v.documentId && typeof v.documentToken==='string' && !!v.documentToken;
    const offer=a.offer, last=a.lastChoice;
    if(offer && (!choiceId(offer.id) || offer.scope!==scope || offer.route!==a.route ||
      ![1,2,3,4].includes(offer.noticeVersion) || offer.language!==undefined && !['zh','en'].includes(offer.language) ||
      !Array.isArray(offer.events) || offer.events.length>128 ||
      offer.events.some(e=>!validCompletion(e,this.project)) || new Set(offer.events.map(completionId)).size!==offer.events.length ||
      !validView(offer.view) || offer.view && offer.view.route!==offer.route) ||
      last && (!choiceId(last.id) || last.scope!==scope || !last.route || route(last.route)!==last.route || !validView(last.view) || !last.view ||
        last.view.route!==last.route || !Array.isArray(last.ids) || last.ids.length>128 ||
        last.ids.some(id=>!validId(id)) || new Set(last.ids).size!==last.ids.length ||
        !['append','ignore'].includes(last.choice) || !['ignored','unknown'].includes(last.outcome) ||
        typeof last.dismissed!=='boolean' || !/^[A-Z_]{1,80}$/.test(last.code || '')))
      throw Error('DRAFT_STATE_INVALID_NO_RESET');

    const before=JSON.stringify(a), consumed=new Set(a.consumed || []), seen=new Set();
    for(const e of a.deliveries) {
      const id=completionId(e);
      // Multiple raw identities cannot become safe merely by resetting epochs.
      if(seen.has(id) || !pending(e))consumed.add(id);
      seen.add(id);
      if(!pending(e)) {
        if(e.intentAt!==undefined && validCompletion(e,this.project))for(const work of noticeItem(e).workRefs)consumed.add(work);
        // Discarded history's links are not live topology. Suppress every known
        // group identity even if its old owner/child pointers disagree.
        if(validId(e.mergedInto))consumed.add(e.mergedInto);
        if(Array.isArray(e.merge))for(const item of e.merge)if(validId(item?.id))consumed.add(item.id);
      }
    }
    for(const e of a.deliveries)if(pending(e) && noticeItem(e).workRefs.every(id=>consumed.has(id)))consumed.add(completionId(e));
    a.deliveries=a.deliveries.filter(e=>pending(e) && !consumed.has(completionId(e)));
    a.consumed=[...consumed];
    if(last && last.ids.some(id=>!consumed.has(id)))throw Error('DRAFT_STATE_INVALID_NO_RESET');
    if(offer)offer.events=[]; // Legacy frozen packets are no longer the prompt's identity.
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
      if(s.automation.offer) {
        if(previous.route!==canonical)s.automation.offer=null; // Explicit receiver switch only; clean rows follow it.
        else s.automation.offer.view=null;
      }
      await this.saveQueue(s); // One coherent publication; never retry/roll back an unknown write.
      if(oldBinding && oldBinding.route!==binding.route)await this.dismissDraft(oldBinding);
      await this.io.clearAlarm(ALARM);await this.io.pollAlarm(POLL);await this.io.reportStatus(s).catch(()=>{});return s;
    }
    const a=s.automation;
    if(!a) throw Error('AUTOMATION_NOT_ENABLED');
    if(action==='disable') {a.enabled=false;await this.saveQueue(s);await this.dismissDraft(s.binding);await this.io.clearAlarm(POLL);await this.io.reportStatus(s).catch(()=>{});return s;}
    if(action==='draft_choice') {
      return this.chooseDraft(s,arg);
    }
    if(!a.enabled)return s;
    await this.reconcileDraft(s); // Clear a lost result's old view before feed/rebind/new offers can fail.
    try {
      await this.pollFeed(s);
      await this.presentPending(s,arg.deferAutomatic);
    } catch(error) {
      a.error=/^[A-Z_]{1,80}$/.test(error?.message||'')?error.message:'BRIDGE_OR_PAGE_UNAVAILABLE';
      await this.saveQueue(s);
      // A catalog/feed outage cannot expand or erase an already frozen choice.
      if(a.offer)try {await this.presentPending(s,arg.deferAutomatic);}catch { /* Retain the same group for a later view. */ }
    } finally {await this.io.reportStatus(s).catch(()=>{});}
    return s;
  }
  async pollFeed(s,all=false,boundary=null) {
    const a=s.automation;let watermark=boundary?.latest;
    for(let page=0;page<(all?9:1);page++) {
      const feed=await this.io.feed({after:a.cursor,epoch:a.epoch});
      if(!this.validFeed(feed) || all && !Number.isSafeInteger(feed.latest))throw Error('FEED_INVALID');
      if(feed.epoch!==a.epoch) {
        for(const e of a.deliveries)e.epoch=feed.epoch;
        a.epoch=feed.epoch;a.cursor=0;await this.saveQueue(s);
        throw Error('PRODUCER_EPOCH_CHANGED_WAIT_NEXT_POLL');
      }
      if(boundary && feed.epoch!==boundary.epoch)throw Error('PRODUCER_EPOCH_CHANGED_WAIT_NEXT_POLL');
      if(feed.cursor<a.cursor)throw Error('FEED_CURSOR_REGRESSION');
      watermark ??= feed.latest;
      const fresh=feed.events.filter(e=>(!all || e.sequence<=watermark) &&
        !a.consumed.includes(completionId(e)) && !a.deliveries.some(d=>completionId(d)===completionId(e)));
      if(fresh.some(e=>e.sequence<=a.cursor))throw Error('FEED_EVENT_REPLAY');
      if(a.deliveries.length+fresh.length>128) {
        a.error='PENDING_QUEUE_FULL';await this.saveQueue(s);
        if(all)throw Error('PENDING_QUEUE_FULL');
        return;
      }
      for(const e of fresh)a.deliveries.push({...e,epoch:feed.epoch,status:'queued',code:'REPORT_READY',
        route:a.route,createdAt:this.io.now(),dueAt:this.io.now()+a.delayMs});
      const previous=a.cursor;
      a.cursor=all?Math.max(previous,Math.min(feed.cursor,watermark)):feed.cursor;
      a.error=feed.blocked?'REPORT_READ_TEMPORARY':null;a.lastPoll=this.io.now();
      await this.saveQueue(s);
      if(feed.blocked && all)throw Error('REPORT_READ_TEMPORARY');
      // A short project page is exhausted even when other projects own later sequences.
      // latest is only a fixed upper bound, never a progress target.
      if(!all || a.cursor>=watermark || feed.events.length<16 || feed.events.some(e=>e.sequence>watermark))return {epoch:a.epoch,latest:watermark};
      if(a.cursor<=previous)throw Error('REPORT_READ_TEMPORARY');
    }
    throw Error('FEED_READ_INCOMPLETE'); // No partial decision after the bounded page budget.
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
  async presentPending(s,deferAutomatic=false) {
    const a=s.automation;
    const candidates=a.deliveries.filter(e=>e.route===a.route && neverAttempted(e) && e.dueAt<=this.io.now());
    if(a.offer || candidates.length && !deferAutomatic) {
      await this.ensureBinding(s);
      if(a.offer)await this.showOffer(s);
      else await this.deliver(s,candidates);
    }
  }
  async reconcileDraft(s) {
    const a=s.automation,last=a.lastChoice;
    if(!last)return;
    // Address the exact saved document/generation/token, not a new recipient.
    // This only settles an existing view; it never rebinds or repeats an effect.
    const {token,...binding}=last.view;
    try {await this.io.page(binding,{op:'draft_result',token,...draftChoiceReply(a,last.id)});}catch { /* No replay. */ }
  }
  async showOffer(s) {
    const a=s.automation,offer=a.offer,b=s.binding;
    const language=normalizeNotificationLanguage(offer.language);
    const r=await this.io.page(b,{op:'draft_offer',offerId:offer.id,noticeVersion:offer.noticeVersion,language});
    const code=r?.ok===true && r.documentId===b.documentId && r.code==='DRAFT_CHOICE_PENDING' && choiceId(r.token)?
      'DRAFT_CHOICE_PENDING':r?.ok===false && /^[A-Z_]{1,80}$/.test(r.code || '')?r.code:'DRAFT_CHOICE_UNCONFIRMED';
    for(const e of a.deliveries)if(e.route===a.route)e.code=code;
    if(code!=='DRAFT_CHOICE_PENDING')throw Error(code);
    const view={...b,token:r.token};
    if(JSON.stringify(view)!==JSON.stringify(offer.view)) {offer.view=view;await this.saveQueue(s);}
    // A lost request before intent may leave both page buttons waiting. Only
    // the worker's still-pending durable record can release that wait.
    await this.io.page(b,{op:'draft_result',offerId:offer.id,token:r.token,outcome:'pending',code:'DRAFT_CHOICE_PENDING',dismissed:false});
  }
  async chooseDraft(s,arg) {
    const a=s.automation,source=arg.source;
    // A sender context URL can lag a same-document route change. Authenticate
    // this view by tab/document/token; choiceTarget and draft_prepare check its current route.
    const matches=view=>view && source && arg.token===view.token && source.tabId===view.tabId &&
      source.documentId===view.documentId;
    if(!choiceId(arg.offerId) || !['append','ignore'].includes(arg.choice))throw Error('DRAFT_CHOICE_STALE');
    if(a.lastChoice?.id===arg.offerId && matches(a.lastChoice.view)) {
      await this.reconcileDraft(s);return s; // Receipt lookup only, never another effect.
    }
    const offer=a.offer,b=s.binding;
    if(!a.enabled || !offer || offer.id!==arg.offerId || !matches(offer.view) || !b ||
      JSON.stringify({...b,token:arg.token})!==JSON.stringify(offer.view))throw Error('DRAFT_CHOICE_SOURCE_CHANGED');
    const language=normalizeNotificationLanguage(offer.language);
    await this.choiceTarget(b);
    const rows=[{controller:this,state:s},...(arg.peers || [])];
    const publish=arg.publish || (async()=>this.saveQueue(s));
    const selected=[];let boundary;
    try {
      // The first response fixes ONE finite observation boundary for this click
      // across projects. It is an upper bound, not a global catch-up requirement.
      for(const row of rows) {
        const c=row.controller,current=row.state;
        const known=new Set(current.automation.deliveries.filter(neverAttempted).map(completionId));
        const observed=await c.pollFeed(current,true,boundary);
        boundary ??= observed;
        row.selected=[];
        for(const e of current.automation.deliveries.filter(e=>e.route===a.route && (e.sequence<=boundary.latest || known.has(completionId(e))) && neverAttempted(e))) {
          if(await c.refreshForSend(current,e))row.selected.push(e);
          else if(pending(e))throw Error('REPORT_READ_TEMPORARY');
        }
        selected.push(...row.selected);
      }
    } catch {return s;} // No intent/effect; a later explicit choice can collect again.
    if(!selected.length)throw Error('DRAFT_REPORT_UNVERIFIED');
    if(selected.length>128)throw Error('PENDING_QUEUE_FULL');
    const scoped=rows.filter(row=>row.selected.length).length>1 || selected[0].project_ref!==this.project;
    const packet=scoped?{eventId:completionId(selected[0]),noticeVersion:4,language,
      merge:selected.map(e=>({...noticeItem(e),project_ref:e.project_ref}))}:
      packetFor(selected,this.io.noticeVersion || (selected.length>1?3:2),language);
    if(packet.merge)mergedNotice(packet.merge,language);
    Object.assign(packet,{offerId:offer.id,token:arg.token});
    // Publish refresh changes BEFORE comparing against persisted state. Never
    // mistake our own identity/version refresh for a concurrent writer.
    await publish(rows);
    const ready=await this.io.page(b,{...packet,op:'draft_prepare'});
    if(ready?.ok!==true || Object.keys(ready).sort().join(',')!=='documentId,focused,lease,ok,visibility' ||
      ready.documentId!==b.documentId || !choiceId(ready.lease) || typeof ready.visibility!=='string' ||
      ready.focused!==null && typeof ready.focused!=='boolean')return s;
    for(const row of rows)
      if(JSON.stringify(await row.controller.io.read(KEY))!==JSON.stringify(row.state))throw Error('STALE_STATE_NO_ATTEMPT');
    await this.choiceTarget(b);
    const before=rows.map(row=>structuredClone(row.state.automation));
    a.lastChoice={id:offer.id,scope:offer.scope,route:offer.route,ids:rows[0].selected.map(completionId),
      view:offer.view,choice:arg.choice,outcome:arg.choice==='ignore'?'ignored':'unknown',
      code:arg.choice==='ignore'?'DRAFT_IGNORED':'DRAFT_APPEND_OUTCOME_UNKNOWN',dismissed:true};
    for(const row of rows) {
      const queue=row.state.automation;
      for(const e of row.selected)queue.consumed.push(completionId(e),...noticeItem(e).workRefs);
      queue.consumed=[...new Set(queue.consumed)];queue.offer=null;
    }
    await publish(rows); // ONE atomic multi-project intent before the ONE page effect.
    if(arg.choice==='ignore') {await this.reconcileDraft(s);return s;}
    let result;
    try {result=await this.io.page(b,{...packet,op:'draft_commit',lease:ready.lease});}catch { /* Persisted unknown: never replay. */ }
    if(commitOutcome(result,b.documentId)==='blocked_before_mutation' ||
      result?.ok===true && result.documentId===b.documentId && result.stage==='blocked_before_mutation' &&
      result.code==='DRAFT_CHOICE_STALE' && Object.keys(result).sort().join(',')==='code,documentId,ok,stage') {
      // Restore only with exact zero-effect proof, atomically across all projects.
      rows.forEach((row,i)=>{row.state.automation=before[i];});
      await publish(rows);
    }
    await this.reconcileDraft(s);
    if(s.automation.offer)await this.showOffer(s);
    return s;
  }
  async ensureBinding(s) {
    const a=s.automation;
    // The persisted user selection is the full route, never a project label or chat UUID.
    const tabs=await this.io.exactTabs(a.route);
    if(tabs.length!==1 || tabs[0].incognito)throw Error('TARGET_NOT_UNIQUE_OR_OPEN');
    if(s.binding?.route===a.route && s.binding.tabId===tabs[0].id) {
      try {
        const view=await this.io.page(s.binding,{op:'draft_probe'});
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
  async deliver(s,candidates) {
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
    const language=await this.language();
    if(!selected[0].merge && selected.length>1) {
      while(selected.length>1) {
        try {mergedNotice(selected.map(noticeItem),language);break;}
        catch(error) {if(error?.message!=='MERGED_NOTICE_TOO_LONG')throw error;selected.pop();}
      }
    }
    const owner=selected[0], merged=selected.length>1;
    const packet=packetFor(selected,owner.noticeVersion ?? this.io.noticeVersion ?? (merged?3:2),language);
    await this.target(b);
    const ready=await this.io.page(b,{op:'prepare'});
    if(!ready.ok) {
      if(ready.code==='DRAFT_PRESENT') {
        for(const e of selected){e.status='waiting';e.code='DRAFT_CHOICE_PENDING';}
        s.automation.offer={id:this.io.uuid(),scope:this.io.scopeId || this.project,route:b.route,
          noticeVersion:packet.noticeVersion,language,events:[],view:null};
        await this.saveQueue(s); // Freeze before publishing any page button.
        await this.showOffer(s);
      } else {
        for(const e of selected){e.status='waiting';e.code=ready.code;}await this.saveQueue(s);
      }
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
    const consumedBefore=[...s.automation.consumed];
    for(const e of selected) {
      // Freeze this page request locally; only its identities persist at intent.
      if(e.noticeVersion===undefined && e.intentAt===undefined)e.noticeVersion=this.io.noticeVersion || (merged?3:2);
      e.status='attempted_unknown';e.outcome='unknown';e.code='INTENT_SAVED_OUTCOME_UNKNOWN';e.intentAt=this.io.now();
    }
    await this.saveQueue(s);
    let r;
    try {
      r=await this.io.page(b,{op:'commit',eventId:completionId(owner),
        ...(merged?{merge:owner.merge}:{reportSha:owner.report_sha256,
          ...(owner.batch_ref?{batch:{batch_ref:owner.batch_ref,project_ref:owner.project_ref,
            requested:owner.requested,not_submitted:owner.not_submitted,members:owner.members}}:{})}),
        noticeVersion:(owner.noticeVersion===undefined?1:owner.noticeVersion),language,lease:ready.lease});
    }catch {return;} // An uncertain invocation is already suppressed.
    // Only automatic Send's exact no-mutation proof may restore unfinished rows.
    if(commitOutcome(r,b.documentId)==='blocked_before_mutation') {
      s.automation.consumed=consumedBefore;
      for(const e of selected) {
        for(const key of ['intentAt','outcome','pageAtPrepare','merge','mergedInto'])delete e[key];
        if(e.noticeVersion===3)delete e.noticeVersion;
        e.status='waiting';e.code=r.code;s.automation.deliveries.push(e);
      }
      await this.saveQueue(s);
    }
  }
}
