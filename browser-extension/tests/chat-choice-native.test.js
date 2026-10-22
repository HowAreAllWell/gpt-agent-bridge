import test from 'node:test';
import assert from 'node:assert/strict';
import {stateStore,nativeExclusive} from '../extension/state-store.js';
import {wiring,primitives,A,B,key,settle} from './review-wiring-fixture.js';
for(const conflict of [false,true])test('native IDB multi-project publication is all-or-none; conflict='+conflict,async()=>{
 const p=primitives(),s=stateStore(p.native.indexedDB,async()=>undefined,undefined,nativeExclusive(p.native.navigator.locks));
 for(const k of ['one','two']){await s.read(k);await s.write(k,{schema:1,revision:1,consumed:[]});}
 const other=stateStore(p.native.indexedDB,async()=>undefined,undefined,nativeExclusive(p.native.navigator.locks));
 if(conflict){await other.read('two');await other.write('two',{schema:1,revision:2,consumed:['other']});}
 const rows=['one','two'].map(k=>({key:k,value:{schema:1,revision:2,consumed:['selected']}}));
 if(conflict)await assert.rejects(s.writeMany(rows),/STATE_CHANGED_NO_OVERWRITE/);else await s.writeMany(rows);
 assert.deepEqual((await other.read('one')).consumed,conflict?[]:['selected']);
 assert.deepEqual((await other.read('two')).consumed,conflict?['other']:['selected']);
});
for(const choice of ['append','ignore'])test('wired native choice commits both projects before one page effect: '+choice,async()=>{
 const f=wiring(),w=f.start();await f.enable(w,A,1);await f.enable(w,B,1);
 const pg=f.pages.get(1);pg.editor.textContent='draft';pg.renderSend();f.publish(A,1);
 pg.onPageMessage=m=>new Promise(resolve=>w.listeners.message(m,{id:'a'.repeat(32),frameId:0,
  documentId:f.docs.get(1),url:pg.location.href,tab:{id:1,incognito:false}},resolve));
 w.tick();await settle();assert.equal(pg.choiceButtons().length,2);f.publish(B,2);let commits=0;
 f.hooks.scriptBefore=async spec=>{if(spec.args[0].op==='draft_commit'){
  commits++;for(const p of [A,B])assert((await f.record(key(p))).automation.consumed.length>0);
 }};
 pg.userClick(pg.choiceButtons()[choice==='append'?0:1]);await settle();
 for(const p of [A,B])assert((await f.record(key(p))).automation.consumed.length>0);
 assert.equal(commits,choice==='append'?1:0);assert.equal(pg.choiceButtons().length,0);assert.equal(pg.clicks,0);
 const text=pg.editor.textContent;const replacement=f.start();replacement.tick();await settle();
 assert.equal(pg.editor.textContent,text);assert.equal(pg.choiceButtons().length,0);
});
