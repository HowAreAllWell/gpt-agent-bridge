export const validProject = value => typeof value==='string' && /^[A-Za-z0-9_.-]{1,80}$/.test(value);
export const WORK = /^work-[0-9a-f]{16}$/;
export const SHA = /^[0-9a-f]{64}$/;
export const POLL = 'bridge-completion-poll';
export function completionId(e) {return e.batch_ref || e.work_ref;}
// Unversioned persisted intents predate the brief notice. Never reinterpret their text.
export function completionMessage(e) {
  const version=(e.noticeVersion===undefined?1:e.noticeVersion);
  if(version===4) {
    if(!validProject(e.project_ref))throw Error('INVALID_PROJECT');
    const body=e.merge?mergedNotice(e.merge):e.batch_ref?batchNotice(e,2):completionNotice(e.work_ref,e.report_sha256,2);
    return 'project_ref='+e.project_ref+'；'+body;
  }
  if(version===3)return mergedNotice(e.merge);
  return e.batch_ref?batchNotice(e,version):completionNotice(e.work_ref,e.report_sha256,version);
}
export function validCompletion(e, project='gpt-agent-bridge') {
  if(!validProject(project) || e?.project_ref!==project)return false;
  if(e?.noticeVersion!==4 && e?.intentAt!==undefined && project!=='gpt-agent-bridge')return false;
  if(e?.noticeVersion!==undefined && ![1,2,3,4].includes(e.noticeVersion))return false;
  if(e?.noticeVersion===3 || e?.noticeVersion===4 && (e.merge || e.mergedInto)) {
    if(!!e.merge===!!e.mergedInto)return false;
    if(e.merge) {
      try {mergedNotice(e.merge);} catch {return false;}
      if(e.merge[0].id!==completionId(e) ||
        JSON.stringify(e.merge[0].workRefs)!==JSON.stringify(e.batch_ref?e.members.map(m=>m.work_ref):[e.work_ref]))return false;
    } else if(!/^batch-[0-9a-f]{16}$|^work-[0-9a-f]{16}$/.test(e.mergedInto))return false;
  } else if(e?.merge!==undefined || e?.mergedInto!==undefined)return false;
  if(e?.batch_ref) {
    try {batchNotice(e);} catch {return false;}
    return Number.isSafeInteger(e.sequence) && e.sequence>0 && Number.isFinite(e.ready_at);
  }
  return e && WORK.test(e.work_ref) && e.project_ref === project && SHA.test(e.report_sha256) &&
    Number.isSafeInteger(e.sequence) && e.sequence > 0 && Number.isFinite(e.ready_at) &&
    e.result_class === 'result_ready' && e.report_status === 'readable';
}
// Only structured, fixed identifiers enter a merged notice. The first item is the
// durable intent owner; every other member keeps a pointer to that same intent.
export function noticeItem(e) {
  if(e.batch_ref) {batchNotice(e,2);return {id:e.batch_ref,workRefs:e.members.map(m=>m.work_ref)};}
  completionNotice(e.work_ref,e.report_sha256,2);
  return {id:e.work_ref,workRefs:[e.work_ref]};
}
export function mergedNotice(items) {
  if(!Array.isArray(items) || items.length<2 || items.length>128 ||
    new Set(items.map(x=>x?.id)).size!==items.length)throw Error('INVALID_MERGED_NOTICE');
  const parts=items.map(x=>{
    if(!x || Object.keys(x).sort().join(',')!=='id,workRefs' ||
      !Array.isArray(x.workRefs) || !x.workRefs.length || x.workRefs.length>528 ||
      x.workRefs.some(w=>!WORK.test(w)) || new Set(x.workRefs).size!==x.workRefs.length ||
      !(/^batch-[0-9a-f]{16}$/.test(x.id) || WORK.test(x.id)&&x.workRefs.length===1&&x.workRefs[0]===x.id))
      throw Error('INVALID_MERGED_NOTICE');
    return x.id+'（'+x.workRefs.join('、')+'）';
  });
  const message='Agent 已结束：'+parts.join('、')+'。';
  if(message.length>160000)throw Error('MERGED_NOTICE_TOO_LONG');
  return message;
}
export function completionNotice(workRef, sha, version=2) {
  if (!WORK.test(workRef) || !SHA.test(sha)) throw Error('INVALID_COMPLETION');
  if(![1,2].includes(version))throw Error('INVALID_NOTICE_VERSION');
  if(version===2)return 'Agent 已结束：'+workRef+'。';
  return '【Bridge 报告可取】project_ref=gpt-agent-bridge；work_ref=' + workRef + '；报告 SHA256=' + sha +
    '。请用 work_report 读取对应报告，再依据原授权判断与继续。此通知只表示报告可读，不表示任务成功；不授予新任务或循环派工权限。';
}

// The serialized adapter carries this same bounded formatter; real adapter regressions compare its output.
export function batchNotice(e, version=2) {
  const work=/^work-[0-9a-f]{16}$/,sha=/^[0-9a-f]{64}$/;
  if(!e || !/^batch-[0-9a-f]{16}$/.test(e.batch_ref) || !validProject(e.project_ref) ||
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
  if(![1,2].includes(version))throw Error('INVALID_NOTICE_VERSION');
  if(version===2)return '本批 Agent 已结束（'+e.batch_ref+'）：'+e.members.map(m=>m.work_ref).join('、')+'。';
  const text='【Bridge 派工批次已收束】project_ref=gpt-agent-bridge；batch_ref='+e.batch_ref+
    '；本次条目='+e.requested+'；保留Work='+e.members.length+'；未派出='+e.not_submitted+'。 '+
    e.members.map(m=>'work_ref='+m.work_ref+'；终态='+m.state+'；最终分类='+m.result_class+
      '；分类时报告='+m.classification_report_status+'；当前报告='+m.report_status+
      (m.report_status==='readable'?'；SHA256='+m.report_sha256:'')).join(' ')+
    ' 请用 work_report 按原 work_ref 读取可读报告，异常或缺报告按状态核查，再依据原授权判断与继续。全批收束不表示全批成功；不授予新任务或循环派工权限；过期项不重派。';
  if(text.length>160000)throw Error('BATCH_NOTICE_TOO_LONG');
  return text;
}
