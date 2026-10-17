import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture, harness, CHAT, OTHER} from './harness.js';
import {Automation} from '../extension/automation.js';

test('explicit binding accepts an old conversation without new last-turn markers, without input or Send', async()=>{
  const p=fixture();p.turn.removeChild(p.assistantHeading);p.turn.removeChild(p.readAloud);
  const text=p.editor.textContent;let inputs=0;p.doc.addEventListener('input',()=>inputs++);
  const b=await p.op({op:'bind',route:CHAT,generation:'old-chat'});
  assert.equal(b.ok,true);assert(b.documentToken);assert.equal(p.clicks,0);
  assert.equal(p.editor.textContent,text);assert.equal(inputs,0);
  p.clock.now+=2100;
  const r=await p.op({op:'prepare',route:CHAT,generation:'old-chat',documentToken:b.documentToken});
  assert.equal(r.code,'BUSY_TURN_UNSETTLED');assert.equal(p.clicks,0);
});

for(const [name,mutate,code] of [
  ['Stop',p=>p.add(p.doc,'button',{'data-testid':'stop-button'}),'BUSY_STOP_PRESENT'],
  ['draft',p=>p.edit('user draft'),'DRAFT_PRESENT'],
  ['attachment',p=>p.add(p.attachments,'span'),'ATTACHMENT_SLOT_UNKNOWN_OR_NONEMPTY'],
  ['missing main button',p=>p.footer.removeChild(p.button),'PRIMARY_UNKNOWN_OR_AMBIGUOUS'],
  ['missing conversation',p=>p.conversation.parentNode.removeChild(p.conversation),'TURN_STRUCTURE_UNKNOWN']
])test('binding '+name+' does not authorize unsafe prepare or commit',async()=>{
  const p=fixture();mutate(p);const text=p.editor.textContent;
  const b=await p.op({op:'bind',route:CHAT,generation:'explicit'});assert.equal(b.ok,true);
  p.clock.now+=2100;
  const r={route:CHAT,generation:'explicit',documentToken:b.documentToken};
  assert.equal((await p.op({...r,op:'prepare'})).code,code);
  const commit=await p.op({...r,op:'commit',eventId:'test-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',lease:'unissued'});
  assert.equal(commit.stage,'blocked_before_mutation');assert.equal(p.clicks,0);assert.equal(p.editor.textContent,text);
});

test('enable on old context only binds and pins feed; a later complete page can send once',async()=>{
  const h=harness(),p=h.page;p.turn.removeChild(p.moreActions);
  h.pages.get(2).location.href=OTHER;
  let ready=false;
  const e={work_ref:'work-0000000000000001',project_ref:'gpt-agent-bridge',sequence:1,ready_at:1,report_sha256:'b'.repeat(64),result_class:'result_ready',report_status:'readable'};
  h.io.feed=async()=>({epoch:'a'.repeat(32),events:ready?[e]:[],cursor:ready?1:0,latest:ready?1:0});
  h.io.pollAlarm=async()=>{};h.io.reportStatus=async()=>{};
  h.io.exactTabs=async route=>[...h.pages].filter(([,page])=>page.location.href===route).map(([id])=>({id,incognito:false}));
  h.io.receipt=async()=>({ok:true,scope:'chat-user-message-v1',notices:0,replies:0});
  h.worker=new Automation(h.io);
  await h.worker.run('enable',{delayMs:0});assert.equal(h.state.automation.enabled,true);
  assert.equal(p.clicks,0);assert.deepEqual(h.state.automation.deliveries,[]);
  p.clock.now+=2100;ready=true;await h.worker.run('tick');assert.equal(p.clicks,0);
  p.turn.appendChild(p.moreActions);await h.worker.run('tick');assert.equal(p.clicks,1);
  const old=h.state.automation.deliveries;await h.worker.run('enable',{delayMs:0});
  assert.deepEqual(h.state.automation.deliveries,old);await h.worker.run('tick');assert.equal(p.clicks,1);
  h.selected=2;
  await h.worker.run('enable',{delayMs:0});
  assert.equal(h.state.binding.route,OTHER);assert.equal(h.state.binding.tabId,2);
  assert.equal(h.state.automation.route,OTHER);assert.equal(h.state.automation.cursor,1);
  assert.deepEqual(h.state.automation.deliveries,old);
  await h.worker.run('tick');
  assert.deepEqual(h.state.automation.deliveries,old);assert.equal(old[0].status,'attempted_unknown');
  assert.equal(old[0].route,CHAT);assert.equal(p.clicks,1);assert.equal(h.pages.get(2).clicks,0);
});

test('invalid route and navigation still reject despite permissive identity-only bind',async()=>{
  const p=fixture();p.location.href='https://chatgpt.com/';
  assert.equal((await p.op({op:'bind',route:null,generation:'bad'})).ok,false);
  p.location.href=CHAT;const b=await p.op({op:'bind',route:CHAT,generation:'valid'});
  p.navigate(OTHER);p.navigate(CHAT);p.clock.now+=2100;
  assert.equal((await p.op({op:'prepare',route:CHAT,generation:'valid',documentToken:b.documentToken})).code,'STALE_BINDING_REBIND');
  assert.equal(p.clicks,0);
});
