import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {Automation, draftChoiceReply} from '../extension/automation.js';
import {Controller} from '../extension/controller.js';
import {completionId, completionMessage, mergedNotice, normalizeNotificationLanguage} from '../extension/completion-policy.js';
import {notice} from '../extension/policy.js';
import {ProjectControllers} from '../extension/projects.js';
import {harness, DOMEvent, CHAT, OTHER} from './harness.js';

const epoch='a'.repeat(32),sha='b'.repeat(64);
const id=(kind,n)=>kind+'-'+n.toString(16).padStart(16,'0');
const work=n=>({work_ref:id('work',n),project_ref:'gpt-agent-bridge',sequence:n,ready_at:5,report_sha256:sha,
  result_class:'result_ready',report_status:'readable'});
const batch=(n=1,count=2)=>({batch_ref:id('batch',n),project_ref:'gpt-agent-bridge',sequence:n,ready_at:5,
  requested:count,not_submitted:0,members:Array.from({length:count},(_,i)=>({
    work_ref:id('work',n*1000+i),state:'agent_turn_settled',result_class:'result_ready',
    classification_report_status:'readable',report_status:'readable',report_sha256:sha}))});
const settle=async()=>{for(let i=0;i<80;i++)await new Promise(r=>setImmediate(r));};
const noChinese=value=>assert(!/[\u4e00-\u9fff]/.test(value),value);

async function simpleSetup({language='zh',draft=''}={}) {
  const h=harness();let currentLanguage=language;const events=[];
  h.io.exactTabs=async route=>route===h.page.location.href?[{id:1,incognito:false}]:[];
  h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
  h.io.notificationLanguage=async()=>currentLanguage;
  h.io.feed=async q=>{
    const rows=events.filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)).slice(0,16);
    return {epoch,events:structuredClone(rows),cursor:Math.max(q?.after||0,...rows.map(e=>e.sequence),0),
      latest:Math.max(0,...events.map(e=>e.sequence))};
  };
  h.worker=new Automation(h.io);
  await h.worker.run('enable',{delayMs:0});h.page.clock.now+=2100;
  if(draft){h.page.editor.textContent=draft;h.page.renderSend();}
  h.page.onPageMessage=async m=>{
    const s=await h.worker.run('draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});
    return draftChoiceReply(s.automation,m.offerId);
  };
  Object.assign(h,{publish:(...items)=>events.push(...items),setLanguage:value=>{currentLanguage=value;},
    tick:()=>h.worker.run('tick'),wake:()=>{h.worker=new Automation(h.io);return h.worker.run('tick');}});
  return h;
}

test('formatters default to Chinese and produce complete English identifiers for every notice shape',()=>{
  const w=work(1),b=batch(1,2);
  const zhSingle='Agent 已结束：'+w.work_ref+'。';
  assert.equal(completionMessage({...w,noticeVersion:2}),zhSingle);
  assert.equal(completionMessage({...w,noticeVersion:2},'en'),'Agent finished: '+w.work_ref+'.');
  assert.equal(completionMessage({...w,noticeVersion:4},'en'),
    'project_ref=gpt-agent-bridge; Agent finished: '+w.work_ref+'.');
  assert.equal(completionMessage({...b,noticeVersion:2},'en'),
    'Agent batch finished ('+b.batch_ref+'): '+b.members.map(m=>m.work_ref).join(', ')+'.');
  assert.equal(completionMessage({...b,noticeVersion:2}),
    '本批 Agent 已结束（'+b.batch_ref+'）：'+b.members.map(m=>m.work_ref).join('、')+'。');
  assert.equal(normalizeNotificationLanguage('fr'),'zh');
  assert.equal(normalizeNotificationLanguage(undefined),'zh');
  assert.equal(normalizeNotificationLanguage('en'),'en');

  const verbose=completionMessage({...w,noticeVersion:1},'en');
  noChinese(verbose);
  for(const expected of ['[Bridge report available]','work_ref='+w.work_ref,'report SHA256='+sha,'work_report'])
    assert(verbose.includes(expected),expected);
  const verboseBatch=completionMessage({...b,noticeVersion:1},'en');
  noChinese(verboseBatch);
  for(const expected of ['[Bridge dispatch batch closed]','batch_ref='+b.batch_ref,'work_ref='+b.members[0].work_ref,
    'final state=agent_turn_settled','SHA256='+sha,'work_report'])
    assert(verboseBatch.includes(expected),expected);

  const merge=[
    {id:id('batch',1),project_ref:'alpha',workRefs:[id('work',1),id('work',2)]},
    {id:id('work',3),project_ref:'beta',workRefs:[id('work',3)]}
  ];
  const merged=mergedNotice(merge,'en');
  noChinese(merged);
  assert.equal(merged,'Agents finished: project_ref=alpha; '+merge[0].id+' ('+merge[0].workRefs.join(', ')+
    '), project_ref=beta; '+merge[1].id+' ('+merge[1].workRefs.join(', ')+').');
  for(const item of merge) {
    assert(merged.includes(item.id));
    for(const ref of item.workRefs)assert(merged.includes(ref));
  }

  const testId='test-00000000-0000-0000-0000-000000000001';
  assert.equal(notice(testId),'【Bridge 扩展测试通知；不是实际任务完成】通知编号：'+testId+
    '。这是用户授权的浏览器通知测试；无需回复，不派工、不修改文件。');
  const englishNotice=notice(testId,'en');
  noChinese(englishNotice);
  assert(englishNotice.includes(testId));
  assert(englishNotice.includes('Bridge extension test notification'));
});

test('English single and batch automatic delivery sends once with unchanged machine identities',async()=>{
  for(const item of [work(1),batch(1,2)]) {
    const h=await simpleSetup({language:'en'});
    h.publish(item);await h.tick();
    const expected=completionMessage({...item,noticeVersion:2},'en');
    assert.equal(h.page.clicks,1);
    assert.equal(h.page.editor.textContent,expected);
    noChinese(expected);
    assert(expected.includes(item.work_ref || item.batch_ref));
    for(const member of item.members || [])assert(expected.includes(member.work_ref));
    assert.deepEqual(h.state.automation.deliveries,[]);
    await h.wake();assert.equal(h.page.clicks,1);
  }
});

test('serialized adapter matches English formatters for legacy and current notice versions',async()=>{
  for(const item of [work(1),batch(1,2)])for(const version of [1,4]) {
    const h=await simpleSetup({language:'en'});
    const binding=h.state.binding;
    const ready=await h.io.page(binding,{op:'prepare'});
    const request=item.batch_ref?{op:'commit',eventId:item.batch_ref,batch:item,noticeVersion:version,
      language:'en',lease:ready.lease}:{op:'commit',eventId:item.work_ref,reportSha:item.report_sha256,
      noticeVersion:version,language:'en',lease:ready.lease};
    const result=await h.io.page(binding,request);
    const expected=completionMessage({...item,noticeVersion:version},'en');
    assert.equal(h.page.clicks,1);
    assert.equal(h.page.editor.textContent,expected);
    noChinese(expected);
    assert.equal(result.code,'SEND_CLICK_INVOKED');
  }
});

test('subsequent notifications use the newly selected language without changing delivery semantics',async()=>{
  const h=await simpleSetup();
  h.publish(work(1));await h.tick();
  assert.equal(h.page.editor.textContent,completionMessage({...work(1),noticeVersion:2}));
  assert.equal(h.page.clicks,1);
  h.page.editor.textContent='';h.page.renderVoice();h.page.clock.now+=2100;
  h.setLanguage('en');
  h.publish(work(2));await h.tick();
  assert.equal(h.page.clicks,2);
  assert.equal(h.page.editor.textContent,completionMessage({...work(2),noticeVersion:2},'en'));
  assert.deepEqual(h.state.automation.consumed,[work(1).work_ref,work(2).work_ref]);
});

test('switching language after delivery or an unknown outcome never resends or replays',async()=>{
  const h=await simpleSetup();
  h.publish(work(1));await h.tick();
  const text=h.page.editor.textContent,clicks=h.page.clicks;
  assert.equal(clicks,1);
  h.setLanguage('en');await h.wake();await h.wake();
  assert.equal(h.page.clicks,clicks);assert.equal(h.page.editor.textContent,text);
  assert.deepEqual(h.state.automation.deliveries,[]);

  const u=await simpleSetup();u.publish(work(2));
  const page=u.io.page;
  u.io.page=async(binding,request)=>{
    if(request.op!=='commit')return page(binding,request);
    await page(binding,request);
    throw Error('ACK_LOST');
  };
  await u.tick();
  const unknownClicks=u.page.clicks,unknownText=u.page.editor.textContent;
  assert.equal(unknownClicks,1);
  assert(u.state.automation.consumed.includes(work(2).work_ref));
  u.setLanguage('en');await u.wake();await u.wake();
  assert.equal(u.page.clicks,unknownClicks);assert.equal(u.page.editor.textContent,unknownText);
  assert.equal(u.page.choiceButtons().length,0);
});

test('language selection never changes the native page guards for Stop or Voice',async()=>{
  for(const stop of ['Stop','停止']) {
    const h=await simpleSetup({language:'en'});
    h.page.add(h.page.footer,'button',{type:'button','aria-label':stop});
    h.publish(work(1));await h.tick();
    assert.equal(h.page.clicks,0);
    assert.equal(h.state.automation.deliveries[0].code,'BUSY_STOP_PRESENT');
    for(const node of h.page.footer.querySelectorAll('[aria-label="'+stop+'"]'))node.parentNode.removeChild(node);
    h.page.clock.now+=2100;await h.wake();
    assert.equal(h.page.clicks,1);
    assert.equal(h.page.editor.textContent,completionMessage({...work(1),noticeVersion:2},'en'));
  }
  for(const voice of ['Start Voice','开始语音']) {
    const h=await simpleSetup({language:'en'});
    h.page.button.attrs['aria-label']=voice;
    h.publish(work(2));await h.tick();
    assert.equal(h.page.clicks,1);
    assert.equal(h.page.editor.textContent,completionMessage({...work(2),noticeVersion:2},'en'));
  }
});

test('legacy synthetic test notification follows the selected language',async()=>{
  const h=harness();h.io.notificationLanguage=async()=>'en';
  h.worker=new Controller(h.io);
  await h.worker.run('bind');h.page.clock.now+=2100;
  await h.worker.run('arm',{delayMs:0});
  assert.equal(h.page.clicks,1);
  noChinese(h.page.editor.textContent);
  assert(h.page.editor.textContent.includes('Bridge extension test notification'));
  assert(h.page.editor.textContent.includes('test-'));
});

function crossProjectSetup(language='en') {
  const projects=['alpha','beta'].map((project_ref,i)=>({project_ref,root:'/synthetic/'+project_ref,
    scope_id:String(i+1).repeat(64)}));
  const key=p=>'bridgeProjectV1:'+p.scope_id;
  const pageWork=(p,n)=>({work_ref:id('work',n),project_ref:p.project_ref,sequence:n,ready_at:1,
    report_sha256:sha,result_class:'result_ready',report_status:'readable'});
  const h=harness(),data={},events=new Map(projects.map(p=>[p.project_ref,[]]));
  let currentLanguage=language;
  h.io.exactTabs=async route=>[{id:route===CHAT?1:2,incognito:false}];
  h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
  h.pages.get(2).location.href=OTHER;
  const page=h.io.page;
  const io={
    read:async k=>structuredClone(data[k]),write:async(k,v)=>{data[k]=structuredClone(v);},
    writeMany:async rows=>{for(const row of rows)data[row.key]=structuredClone(row.value);},
    catalog:async()=>({projects}),
    forProject:p=>({...h.io,notificationLanguage:async()=>currentLanguage,
      page:async(binding,request)=>page(binding,{...request,project:binding.project}),
      feed:async q=>{
        const rows=events.get(p.project_ref).filter(e=>q?.check?completionId(e)===q.check:e.sequence>(q?.after||0)).slice(0,16);
        return {epoch,events:structuredClone(rows),cursor:Math.max(q?.after||0,...rows.map(e=>e.sequence),0),
          latest:Math.max(0,...[...events.values()].flat().map(e=>e.sequence))};
      }})
  };
  const manager=new ProjectControllers(io);
  return {h,data,events,manager,projects,key,pageWork,
    setLanguage:value=>{currentLanguage=value;},
    state:p=>data[key(p)]};
}

test('multi-project English draft banner, IME feedback and Append keep identifiers without sending',async()=>{
  const f=crossProjectSetup('en'),{h,manager,projects,key}=f;
  for(const project of projects){h.selected=1;await manager.run(project.project_ref,'enable',{delayMs:0});}
  h.page.clock.now+=2100;
  h.page.editor.textContent='draft';h.page.renderSend();
  f.events.get('alpha').push(f.pageWork(projects[0],1));
  f.events.get('beta').push(f.pageWork(projects[1],2));
  await manager.tick();

  const offer=h.page.window.__bridgeDraftChoiceV1;
  const panel=offer.host._closedShadow.childNodes[0];
  assert.equal(panel.getAttribute('aria-label'),'Bridge completion reminder');
  const offered=f.projects.map(project=>f.state(project)).filter(state=>state?.automation?.offer);
  assert(offered.length>=1);
  for(const state of offered)assert.equal(state.automation.offer.language,'en');
  assert.match(panel.childNodes[0].textContent,/Work finished.*already contains a draft/);
  assert.deepEqual(h.page.choiceButtons().map(button=>button.textContent),
    ['Append to the end of the input (new line)','Ignore']);
  assert.equal(h.page.clicks,0);

  h.page.doc.emit(new DOMEvent('compositionstart',{target:h.page.editor}));
  h.page.userClick(h.page.choiceButtons()[0]);
  await settle();
  assert.match(panel.childNodes[0].textContent,/Finish the current IME composition before appending/);
  h.page.doc.emit(new DOMEvent('compositionend',{target:h.page.editor}));

  f.setLanguage('zh');
  await manager.tick();
  assert.equal(h.page.window.__bridgeDraftChoiceV1,offer);
  assert.deepEqual(h.page.choiceButtons().map(button=>button.textContent),
    ['Append to the end of the input (new line)','Ignore']);

  h.page.onPageMessage=async m=>{
    const out=await manager.run(m.project_ref,'draft_choice',{...m,source:{tabId:1,documentId:'doc-1',url:CHAT}});
    return draftChoiceReply(out.state.automation,m.offerId);
  };
  h.page.userClick(h.page.choiceButtons()[0]);
  await settle();

  const text=h.page.editor.textContent;
  noChinese(text);
  assert(text.startsWith('draft'));
  assert(text.includes('Agents finished: project_ref=alpha;'));
  assert(text.includes('project_ref=beta;'));
  for(const project of projects) {
    assert(text.includes(f.pageWork(project,project===projects[0]?1:2).work_ref));
    assert(f.state(project).automation.consumed.includes(f.pageWork(project,project===projects[0]?1:2).work_ref));
  }
  assert.equal(h.page.clicks,0);
  assert.equal(h.page.choiceButtons().length,0);

  const before=h.page.editor.textContent;
  await manager.tick();
  assert.equal(h.page.editor.textContent,before);
  assert.equal(h.page.clicks,0);
  assert.equal(h.page.choiceButtons().length,0);

  // The persisted offer remains the only source of its frozen language.
  assert.equal(f.state(projects[0]).automation.consumed.length,1);
  assert.equal(f.state(projects[1]).automation.consumed.length,1);
});

const popupHtml=fs.readFileSync(new URL('../extension/popup.html',import.meta.url),'utf8');
const popupSource=fs.readFileSync(new URL('../extension/popup.js',import.meta.url),'utf8').replace(/^import .*;\n/,'');
const flush=async()=>{for(let i=0;i<15;i++)await new Promise(r=>setImmediate(r));};
const popupRows=[{project_ref:'alpha',root:'/synthetic/a',available:true}];
function waitingState() {
  return {binding:{project:'alpha',route:CHAT,tabId:77,generation:'private-generation'},events:[],
    automation:{enabled:true,route:CHAT,delayMs:0,error:null,deliveries:[
      {work_ref:'work-0000000000000002',route:CHAT,status:'waiting',code:'DRAFT_CHOICE_PENDING'}]}};
}
function storage(initial={},fail=false) {
  const data=structuredClone(initial),writes=[];
  return {data,writes,local:{
    async get(key){return typeof key==='string'?{[key]:data[key]}:{...data};},
    async set(values){writes.push(structuredClone(values));if(fail)throw Error('QUOTA');Object.assign(data,structuredClone(values));}
  }};
}
function popup(store,send=async m=>({ok:true,projects:popupRows,selected:m.project_ref,
  state:m.project_ref?waitingState():undefined})) {
  const elements={};
  for(const [,id] of popupHtml.matchAll(/id="([^"]+)"/g))elements[id]={value:id==='delay'?'0':'',
    textContent:'',disabled:false,checked:false,options:[],attrs:{},handlers:{},
    addEventListener(k,f){this.handlers[k]=f;},replaceChildren(...options){this.options=options;this.value=options[0]?.value||'';},
    add(option){this.options.push(option);},getAttribute(name){return this.attrs[name]??null;}};
  const i18n=[];
  for(const [,id,key] of popupHtml.matchAll(/id="([^"]+)"[^>]*data-i18n="([^"]+)"/g)) {
    elements[id].attrs['data-i18n']=key;i18n.push(elements[id]);
  }
  const messages=[];
  const document={getElementById:id=>elements[id],documentElement:{},
    querySelectorAll:selector=>selector==='[data-i18n]'?i18n:[]};
  vm.runInNewContext(popupSource,{document,
    Option:function(text,value){return {text,value};},setTimeout,clearTimeout,
    chrome:{tabs:{query:{active:true,currentWindow:true}},runtime:{sendMessage:async m=>{
      messages.push(m);return send(m);
    }},storage:store}});
  return {elements,messages,async change(value){elements.language.value=value;
    elements.language.handlers.change();await flush();}};
}

test('popup defaults to Chinese without a preference and safely falls back from invalid values',async()=>{
  for(const initial of [{},{bridgeNotificationLanguage:'fr'}]) {
    const store=storage(initial),p=popup(store);
    await flush();
    assert.equal(p.elements.language.value,'zh');
    assert.equal(p.elements.heading.textContent,'Bridge 完成通知');
    assert.equal(p.elements['language-note'].textContent,'仅影响之后的新提醒；不会重发或迁移已有通知。');
    assert.equal(p.elements['automatic-status'].textContent,'自动通知已启用');
    assert.match(p.elements.feedback.textContent,/追加.*忽略/);
    assert.equal(store.writes.length,0);
    assert(p.messages.every(m=>m.action==='status'));
  }
});

test('English popup preference persists in one field, translates reminders and never triggers worker actions',async()=>{
  const store=storage({bridgeNotificationLanguage:'en',bridgeProjectsV1:{keep:true}});
  const p=popup(store);
  await flush();
  assert.equal(p.elements.language.value,'en');
  assert.equal(p.elements.heading.textContent,'Bridge completion notifications');
  assert.match(p.elements['automatic-label'].textContent,/Allow automatic sending.*not migrated or replayed/);
  assert.equal(p.elements['automatic-status'].textContent,'Automatic notifications enabled');
  assert.match(p.elements.feedback.textContent,/Append.*Ignore/);
  assert.equal(p.elements['language-note'].textContent,
    'Applies to new reminders only; existing notifications are not resent or migrated.');
  assert.match(p.elements['diagnostics-help'].textContent,/Actions apply only to the selected project/);
  assert.match(p.elements['legacy-help'].textContent,/Creates no new tests/);
  assert(p.messages.every(m=>m.action==='status'));

  const beforeMessages=p.messages.length;
  await p.change('zh');
  assert.deepEqual(store.writes,[{bridgeNotificationLanguage:'zh'}]);
  assert.equal(store.data.bridgeProjectsV1.keep,true);
  assert.equal(p.elements.language.value,'zh');
  assert.equal(p.elements.heading.textContent,'Bridge 完成通知');
  assert.match(p.elements.feedback.textContent,/追加.*忽略/);
  assert.match(p.elements['language-status'].textContent,/已有通知不会重发/);
  assert.equal(p.messages.length,beforeMessages);
  assert(p.messages.every(m=>m.action==='status'));

  const reopened=popup(store);
  await flush();
  assert.equal(reopened.elements.language.value,'zh');
  const beforeSecond=reopened.messages.length;
  await reopened.change('en');
  assert.equal(store.data.bridgeNotificationLanguage,'en');
  assert.equal(reopened.messages.length,beforeSecond);
  const again=popup(store);
  await flush();
  assert.equal(again.elements.language.value,'en');
  assert.equal(again.elements.heading.textContent,'Bridge completion notifications');
  assert.equal(store.writes.length,2);
});

test('popup save failure keeps the previous language and repeated selection is inert',async()=>{
  const store=storage({bridgeNotificationLanguage:'zh'},true);
  const p=popup(store);
  await flush();
  const beforeMessages=p.messages.length;
  await p.change('en');
  assert.equal(p.elements.language.value,'zh');
  assert.equal(p.elements.heading.textContent,'Bridge 完成通知');
  assert.match(p.elements['language-status'].textContent,/保存失败.*中文/);
  assert.equal(store.data.bridgeNotificationLanguage,'zh');
  assert.deepEqual(store.writes,[{bridgeNotificationLanguage:'en'}]);
  assert.equal(p.messages.length,beforeMessages);

  const writes=store.writes.length;
  await p.change('zh');
  assert.equal(store.writes.length,writes);
  assert.equal(p.messages.length,beforeMessages);
  assert.equal(p.elements.language.value,'zh');
});
