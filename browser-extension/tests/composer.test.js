import test from "node:test";
import assert from "node:assert/strict";
import {domOperation} from "../extension/adapter.js";
import {notice} from "../extension/policy.js";
import {fixture,harness,CHAT,boundPreparation} from "./harness.js";

const SELECTOR = 'div[contenteditable="true"][role="textbox"][data-composer-markdown]';
const SLOT = "__bridgeSyntheticNoticeV1";
const EVENT = "test-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const last = s => s.events.at(-1);

// Keep the historical ID-only negative selector control on the new body fixture.
// The actual intermediate adapter is tested separately in the controls receipt.
const legacySource = domOperation.toString().replace(
  "'"+SELECTOR+"'", "'#prompt-textarea[contenteditable=\"true\"]'");

async function bind(p) {
  const bound = await p.op({op:"bind",route:CHAT,generation:"composer-test"});
  assert.equal(bound.ok,true);
  return {route:CHAT,generation:"composer-test",documentToken:bound.documentToken};
}
async function prepare(p) {
  const req = await bind(p);
  p.clock.now += 2100;
  const ready = await p.op({...req,op:"prepare"});
  assert.equal(ready.ok,true);
  return {...req,op:"commit",lease:ready.lease,eventId:EVENT};
}

test("composer: legacy ID-only operation rejects the supplied id-less subtree",async()=>{
  assert(!legacySource.includes(SELECTOR));
  const p = fixture(legacySource);
  assert.equal(p.editor.getAttribute("id"),null);
  assert.equal(p.doc.querySelectorAll('#prompt-textarea[contenteditable="true"]').length,0);
  assert.equal(p.doc.querySelectorAll(SELECTOR).length,1);
  const result = await boundPreparation(p,"old");
  assert.equal(result.ok,false);
  assert.equal(result.code,"COMPOSER_UNKNOWN_OR_AMBIGUOUS");
  assert.equal(p.clicks,0);assert.equal(p.editor.textContent,"");
  // Identity binds; the ID-only selector still cannot prepare a send.
  assert.equal(p.window[SLOT].generation,"old");
  assert.equal(p.doc.listeners.input.length,2); // Fixture also models clearing its own prefill.
});

test("composer: supplied div/p/br attributes bind and pass both discovery and body checks",async()=>{
  const p = fixture();
  assert.deepEqual(p.editor.attrs,{
    contenteditable:"true","aria-multiline":"true",dir:"auto",role:"textbox",
    spellcheck:"true",tabindex:"0",translate:"no",class:"ProseMirror",
    "data-composer-markdown":"","aria-label":"Ask ChatGPT","data-virtualkeyboard":"true"
  });
  const paragraph = p.editor.childNodes[0], br = paragraph.childNodes[0];
  assert.deepEqual(paragraph.attrs,{"data-empty-paragraph":"true","data-placeholder":"Ask ChatGPT",class:"placeholder"});
  assert.deepEqual(br.attrs,{class:"ProseMirror-trailingBreak"});
  assert.deepEqual(p.body.querySelectorAll(SELECTOR),[p.editor]);
  assert.equal(paragraph.closest(SELECTOR),p.editor);
  assert.equal(br.closest(SELECTOR),p.editor);
  const commit = await prepare(p);
  const result = await p.op(commit);
  assert.equal(result.stage,"clicked");assert.equal(p.clicks,1);
  assert.equal(p.editor.textContent,notice(EVENT));
  assert.equal(p.window[SLOT].revision,0); // Own input must stay excluded.
});

test("composer: localization/class/id are not selector requirements or fallbacks",async()=>{
  const p = fixture();
  p.editor.attrs["aria-label"] = "別の言語";
  p.editor.attrs.class = "changed-class";
  p.editor.attrs.id = "different-id";
  p.editor.childNodes[0].attrs["data-placeholder"] = "other";
  await prepare(p);
  assert.equal(p.clicks,0);
});

for (const [name,mutate] of [
  ["zero",p=>{delete p.editor.attrs["data-composer-markdown"];}],
  ["id-only legacy",p=>{p.editor.attrs={id:"prompt-textarea",contenteditable:"true"};}],
  ["non-div",p=>{p.editor.tagName="SPAN";}],
  ["wrong role",p=>{p.editor.attrs.role="searchbox";}],
  ["not editable",p=>{p.editor.attrs.contenteditable="false";}],
  ["multiple visible",p=>p.add(p.body,"div",{...p.editor.attrs})],
  ["sole hidden",p=>{p.editor.hidden=true;}]
]) test("composer: "+name+" candidates reject rather than choose a first/visible match",async()=>{
  const p = fixture();mutate(p);
  const result = await boundPreparation(p,"rejected");
  assert.equal(result.ok,false);assert.equal(result.code,"COMPOSER_UNKNOWN_OR_AMBIGUOUS");
  assert.equal(p.clicks,0);assert.equal(p.editor.textContent,"");
});

test("composer: recognized subtree outside its body still rejects",async()=>{
  const p = fixture();
  p.doc.appendChild(p.editor);
  const result = await boundPreparation(p,"no-form");
  assert.equal(result.code,"COMPOSER_BODY_UNKNOWN_OR_AMBIGUOUS");assert.equal(p.clicks,0);
});

for (const type of ["beforeinput","input","keydown","paste","drop","compositionstart","compositionupdate","compositionend"])
test("composer: child-target "+type+" preserves capture registration, revision and active IME without a quiet timer",async()=>{
  for (const child of ["p","br"]) {
    const p = fixture(), capture = new Map();
    const register = p.doc.addEventListener;
    p.doc.addEventListener = (name,fn,option)=>{capture.set(name,option);register.call(p.doc,name,fn,option);};
    const req = await bind(p);
    assert.equal(capture.get(type),true);
    const target = p.editor.querySelectorAll(child)[0];
    assert(target);assert.equal(target.closest(SELECTOR),p.editor);
    if (type==="compositionend") p.doc.emit({type:"compositionstart",target});
    p.clock.now += 2100;
    const state = p.window[SLOT], revision = state.revision;
    p.doc.emit({type,target});
    assert.equal(state.revision,revision+1,child);
    assert.equal(Object.hasOwn(state,'lastEdit'),false);
    const composing = type==="compositionstart" || type==="compositionupdate";
    assert.equal(state.composing,composing);
    const immediate=await p.op({...req,op:"prepare"});
    assert.equal(composing?immediate.code:immediate.ok,composing?"IME_ACTIVE":true);
    if (composing) {
      assert.equal((await p.op({...req,op:"prepare"})).code,"IME_ACTIVE");
      p.doc.emit({type:"compositionend",target});
      assert.equal(state.composing,false);
      assert.equal((await p.op({...req,op:"prepare"})).ok,true);
    }
    assert.equal((await p.op({...req,op:"prepare"})).ok,true);
    assert.equal(p.clicks,0);
  }
});

test("composer: child keydown isComposing blocks even after quiet time",async()=>{
  const p = fixture(), req = await bind(p);
  p.clock.now += 2100;
  p.doc.emit({type:"keydown",target:p.editor.querySelectorAll("br")[0],isComposing:true});
  assert.equal(p.window[SLOT].revision,1);
  p.clock.now += 2100;
  assert.equal((await p.op({...req,op:"prepare"})).code,"IME_ACTIVE");
  assert.equal(p.clicks,0);
});

test("composer: child edit invalidates prepared lease even after quiet time recovers",async()=>{
  const p = fixture(), commit = await prepare(p);
  p.doc.emit({type:"keydown",target:p.editor.querySelectorAll("p")[0]});
  p.clock.now += 2100; // Quiet again, still within the three-second lease.
  const result = await p.op(commit);
  assert.equal(result.stage,"blocked_before_mutation");
  assert.equal(result.code,"STALE_PAGE_OBSERVATION");
  assert.equal(p.clicks,0);assert.equal(p.editor.textContent,"");
});

for (const type of ["input","keydown","paste","compositionstart","compositionend"])
test("composer: child "+type+" during post-prefill await leaves text and unknown with zero click",async()=>{
  const h = harness();await h.bind();
  let retained, revision;
  h.page.onYield = ()=>{
    const paragraph = h.page.editor.querySelectorAll("p")[0];
    const target = type==="keydown" ? paragraph.childNodes[0] : paragraph;
    // A keydown need not change text to invalidate the observation.
    if (type!=="keydown") paragraph.appendChild(h.page.doc.createTextNode(" USER"));
    revision = h.page.window[SLOT].revision;
    h.page.doc.emit({type,target});
    retained = h.page.editor.textContent;
  };
  const s = await h.arm();
  assert.equal(h.page.window[SLOT].revision,revision+1);
  assert.equal(h.page.clicks,0);
  assert.equal(last(s).status,"attempted_unknown");
  assert.equal(last(s).code,type==="compositionstart"?"IME_ACTIVE":type==="keydown"?"STALE_AFTER_PREFILL_LEFT_IN_PLACE":"OWNED_TEXT_CHANGED_LEFT_IN_PLACE");
  assert.equal(h.page.editor.textContent,retained);
  assert(retained.includes(notice(last(s).id)));
  if (type!=="keydown") assert(retained.includes(" USER"));
  await assert.rejects(h.worker.run("retry"),/NOT_SAFE_TO_RETRY/);
  await h.newWorker().run("alarm");
  assert.equal(h.page.clicks,0);assert.equal(h.page.editor.textContent,retained);
});
