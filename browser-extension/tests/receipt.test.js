import test from 'node:test';
import assert from 'node:assert/strict';
import {completionNotice} from '../extension/completion-policy.js';
import {messageFixture} from './receipt-fixture.js';
import {CHAT} from './harness.js';
const id='work-1111222233334444',message=completionNotice(id,'a'.repeat(64));
const request={id,message,route:CHAT};
test('observed user-turn topology accepts a real notice without requiring a reply or returning text',()=>{
 const f=messageFixture();f.user(message);const r=f.observe(request);
 assert.equal(r.ok,true);assert.equal(r.scope,'chat-user-message-v1');assert.equal(r.notices,1);assert.equal(r.replies,0);
 assert.equal(r.focused,false);assert.equal(r.visibility,'hidden');assert.equal(r.turnKeys.length,1);
 assert.equal(JSON.stringify(r).includes(id),false);
});
test('legacy same-turn plain reply remains observable',()=>{
 const f=messageFixture();f.user(message,id);assert.equal(f.observe(request).replies,1);
});
for(const place of ['outside','conversation','composer'])test('exact non-message preview is not receipt: '+place,()=>{
 const f=messageFixture(),parent=place==='outside'?f.page.doc:place==='conversation'?f.root:f.page.editor;
 f.page.add(parent,'div').textContent=message;const r=f.observe(request);
 assert.equal(r.notices,0);assert.equal(r.draft,place==='composer');
});
for(const kind of ['quote','draft','assistant','heading','identity','unscoped','hidden'])test('matching text in an untrusted message shape does not confirm: '+kind,()=>{
 const f=messageFixture(),m=f.user(message);
 if(kind==='quote') {const q=f.page.add(m.bubble,'blockquote');q.appendChild(m.target);}
 if(kind==='draft')m.leaf.attrs.contenteditable='true';
 if(kind==='assistant')m.unit.attrs['data-chatgpt-search-unit-key']='fallback-turn-1:0:assistant';
 if(kind==='heading')m.h.textContent='Preview:';
 if(kind==='identity')m.unit.attrs['data-chatgpt-search-message-ids']='different-message';
 if(kind==='unscoped')f.page.doc.appendChild(m.turn);
 if(kind==='hidden')m.bubble.hidden=true;
 assert.equal(f.observe(request).notices,0);
});
test('assistant quote cannot borrow the user bubble marker to confirm',()=>{
 const f=messageFixture(),m=f.user('some other synthetic message');
 const b=f.page.add(m.assistant,'div',{'data-user-message-bubble':'true'});b.textContent=message;
 assert.equal(f.observe(request).notices,0);
});
test('duplicate sent messages remain ambiguous',()=>{
 const f=messageFixture();f.user(message);f.user(message);assert.equal(f.observe(request).notices,2);
});
test('unknown roots, dialog and before/after route changes conservatively reject',()=>{
 const f=messageFixture();f.user(message);f.page.location.href=CHAT+'?other';assert.equal(f.observe(request).ok,false);
 f.page.location.href=CHAT;const d=f.page.add(f.page.doc,'dialog',{open:''});assert.equal(f.observe(request).ok,false);f.page.doc.removeChild(d);
 const original=f.page.doc.hasFocus;f.page.doc.hasFocus=()=>{f.page.location.href=CHAT+'#changed';return original();};
 // location is checked at the end before any caller can accept the observation.
 const r=f.observe(request);assert.equal(r.ok,false);
});
