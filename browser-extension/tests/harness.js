import vm from "node:vm";
import {domOperation} from "../extension/adapter.js";
import {Controller} from "../extension/controller.js";
import {KEY} from "../extension/policy.js";
export const CHAT = "https://chatgpt.com/c/11111111-1111-1111-1111-111111111111";
export const OTHER = "https://chatgpt.com/c/22222222-2222-2222-2222-222222222222";
function match(el, raw) {
  if (el.nodeType !== 1) return false;
  let selector = raw.trim();
  const excluded = selector.match(/:not\(([^)]+)\)/);
  if (excluded) { if (match(el, excluded[1])) return false; selector = selector.replace(excluded[0], ""); }
  const tag = selector.match(/^[A-Za-z][A-Za-z0-9]*/);
  if (tag && tag[0].toUpperCase() !== el.tagName) return false;
  const id = selector.match(/#([\w-]+)/);
  if (id && el.getAttribute("id") !== id[1]) return false;
  for (const m of selector.matchAll(/\[([^=\]]+)(?:="([^"]*)")?\]/g)) {
    if (!el.attrs.hasOwnProperty(m[1]) || m[2] !== undefined && el.attrs[m[1]] !== m[2]) return false;
  }
  return true;
}
export class DOMEvent {
  constructor(type, args={}) {Object.assign(this,{type,bubbles:false,cancelable:false,defaultPrevented:false},args);}
  preventDefault() {if(this.cancelable)this.defaultPrevented=true;}
  stopPropagation() {this.stopped=true;}
  stopImmediatePropagation() {this.stopped=true;this.immediate=true;}
  composedPath() {return [...(this.path || [])];}
}
class EventTarget {
  constructor() {this.listeners={};}
  addEventListener(type,fn,options=false) {
    const capture=typeof options==='boolean'?options:!!options.capture;
    const list=this.listeners[type]??=[];
    if(!list.some(x=>x.fn===fn&&x.capture===capture))list.push({fn,capture,once:!!options?.once});
  }
  removeEventListener(type,fn,options=false) {
    const capture=typeof options==='boolean'?options:!!options.capture;
    this.listeners[type]=(this.listeners[type]||[]).filter(x=>x.fn!==fn||x.capture!==capture);
  }
  dispatchEvent(event) {return dispatch(this,event);}
}
// Frozen propagation path: connected targets traverse Window -> document ->
// ancestors -> target and bubble back; detached nodes never reach the document.
function dispatch(target,event) {
  const path=[];for(let n=target;n;n=n.parentNode)path.push(n);
  if(path.at(-1)===target.ownerDocument)path.push(target.ownerDocument.defaultView);
  event.target=target;event.path=path;event.stopped=false;event.immediate=false;
  const invoke=(node,capture,phase)=>{
    event.currentTarget=node;event.eventPhase=phase;
    for(const item of [...(node.listeners?.[event.type]||[])]) {
      if(item.capture!==capture || !(node.listeners[event.type]||[]).includes(item))continue;
      if(item.once)node.removeEventListener(event.type,item.fn,item.capture);
      item.fn.call(node,event);if(event.immediate)break;
    }
  };
  for(const node of path.slice(1).reverse()) {invoke(node,true,1);if(event.stopped)break;}
  if(!event.stopped) {invoke(target,true,2);if(!event.immediate)invoke(target,false,2);}
  if(event.bubbles&&!event.stopped)for(const node of path.slice(1)) {invoke(node,false,3);if(event.stopped)break;}
  event.currentTarget=null;event.eventPhase=0;event.path=[];
  return !event.defaultPrevented;
}
class Element extends EventTarget {
  constructor(tag, attrs={}) { super();this.nodeType=1;this.tagName=tag.toUpperCase();this.attrs=attrs;this.childNodes=[];this.parentNode=null;this.disabled=false;this.files=[]; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  get children() { return this.childNodes.filter(n=>n.nodeType===1); }
  get parentElement() { return this.parentNode?.nodeType===1?this.parentNode:null; }
  contains(node) { while(node){if(node===this)return true;node=node.parentNode;}return false; }
  appendChild(node) { if(node.parentNode)node.parentNode.removeChild(node);node.parentNode=this; node.ownerDocument=this.ownerDocument;this.childNodes.push(node);return node; }
  get hidden() { return Object.prototype.hasOwnProperty.call(this.attrs,"hidden"); }
  set hidden(value) { if(value)this.attrs.hidden="";else delete this.attrs.hidden; }
  get form() {
    if(this.tagName!=="BUTTON")return undefined;
    const id=this.getAttribute("form");
    return id===null ? this.closest("form") : this.ownerDocument.querySelectorAll("form").find(el=>el.getAttribute("id")===id) || null;
  }
  removeChild(node) { const i=this.childNodes.indexOf(node);if(i<0)throw Error("NOT_CHILD");this.childNodes.splice(i,1);node.parentNode=null;return node; }
  replaceChild(next,previous) {
    const i=this.childNodes.indexOf(previous);if(i<0)throw Error("NOT_CHILD");
    if(next.parentNode)next.parentNode.removeChild(next);
    this.childNodes[i]=next;next.parentNode=this;next.ownerDocument=this.ownerDocument;previous.parentNode=null;return previous;
  }
  get textContent() { return this.childNodes.map(n=>n.nodeType===3?n.nodeValue:n.textContent).join(""); }
  set textContent(value) { for(const child of this.childNodes)child.parentNode=null;this.childNodes=[]; if(value)this.appendChild({nodeType:3,nodeValue:value}); }
  closest(selector) { let n=this;while(n){if(selector.split(',').some(s=>match(n,s)))return n;n=n.parentNode;}return null; }
  querySelectorAll(selector) {
    const result=[]; const selectors=selector.split(",");
    const walk=n=>{for(const child of n.childNodes || []){if(selectors.some(s=>match(child,s)))result.push(child);walk(child);}};
    walk(this);return result;
  }
  getClientRects() { let n=this;while(n){if(n.hidden)return [];n=n.parentNode;}return [{}]; }
  click() {
    if(this.disabled)return;
    const accepted=this.dispatchEvent(new DOMEvent('click',{bubbles:true,cancelable:true}));
    this.onClick?.(); // Instrument physical activation independently of submit acceptance.
    if(accepted&&this.getAttribute('type')==='submit'&&this.form)this.form.requestSubmit(this);
  }
  requestSubmit(submitter=null) {
    if(this.tagName!=='FORM')throw Error('NOT_FORM');
    if(this.dispatchEvent(new DOMEvent('submit',{bubbles:true,cancelable:true,submitter})))this.onSubmit?.();
  }
}
export function fixture(operation = domOperation, options = {}) {
  const doc=new Element("html");doc.ownerDocument=doc;
  // Compatibility helper dispatches through the target's real ancestor path.
  doc.emit=event=>dispatch(event.target || doc,event instanceof DOMEvent?event:new DOMEvent(event.type,{bubbles:true,cancelable:true,...event}));
  doc.createTextNode=value=>({nodeType:3,nodeValue:value});
  const add=(parent,tag,attrs={})=>parent.appendChild(new Element(tag,attrs));
  const region=add(doc,"div",{role:"region","aria-label":"Conversation","data-app-action-timeline-scroll":""});
  const conversation=add(region,"div",{"data-thread-find-target":"conversation","data-chatgpt-conversation-selection-target":"true"});
  const turn=add(conversation,"div",{"data-turn-key":"completed-turn"});
  add(turn,"h4",{class:"sr-only"}).textContent="You said:";
  const assistantHeading=add(turn,"h4",{class:"sr-only"});assistantHeading.textContent="ChatGPT said:";
  const readAloud=add(turn,"button",{"aria-label":"Read aloud"});
  const moreActions=add(turn,"button",{"aria-label":"More actions"});
  // Composer body/footer/control attributes are user supplied. The document root,
  // optional outer form, unobserved file input and render transition are synthetic.
  const owner = options.owner ? add(doc,"form") : null;
  const body = add(owner || doc,"div",{"data-composer-layout":"single-line","data-composer-body":"",style:"opacity: 1;"});
  const attachments = add(body,"div",{"data-composer-attachments":"","data-composer-spacing":"flush",hidden:""});
  const footer = add(body,"div",{"data-composer-footer-responsive":"","data-composer-layout":"single-line",
    "data-composer-rows":"responsive","data-composer-spacing":"default"});
  const addContext = add(footer,"button",{type:"button","aria-label":"Add files and more",
    "aria-expanded":"false","data-composer-navigation-target":"add-context","data-state":"closed"});
  const reasoning = add(footer,"button",{type:"button","aria-label":"Select ChatGPT model",
    "aria-haspopup":"menu","aria-expanded":"false","data-state":"closed",
    "data-codex-intelligence-trigger":"true","data-composer-navigation-target":"reasoning",
    "data-selected-reasoning-effort":"high"});
  add(reasoning,"span").textContent="Thinking effort";add(reasoning,"span").textContent="High";
  const input = add(footer,"div",{"data-composer-input":""});
  const rich = add(input,"div",{"data-rich-text-layout":"single-line",role:"presentation","data-composer-input-layout":"single-line"});
  const editor=add(rich,"div",{
    contenteditable:"true","aria-multiline":"true",dir:"auto",role:"textbox",
    spellcheck:"true",tabindex:"0",translate:"no",class:"ProseMirror",
    "data-composer-markdown":"","aria-label":"Ask ChatGPT","data-virtualkeyboard":"true"
  });
  add(add(editor,"p",{"data-empty-paragraph":"true","data-placeholder":"Ask ChatGPT",class:"placeholder"}),
    "br",{class:"ProseMirror-trailingBreak"});
  const dictate = add(footer,"button",{type:"button","aria-busy":"false","aria-label":"Dictate"});
  let button = add(footer,"button",{type:"button","aria-label":"Start Voice","data-state":"closed"});
  add(body,"div");add(body,"div"); // Empty tail wrappers.
  const file=new Element("input",{type:"file",hidden:""});file.ownerDocument=doc;
  const clock={now:10000},location={href:CHAT},navigator={onLine:true},navigation={listeners:[]};
  navigation.addEventListener=(_,fn)=>navigation.listeners.push(fn);
  let clicks=0,voiceClicks=0,onYield=()=>{},transition=options.transition || "replace";
  const count = node=>{node.onClick=()=>{clicks++;if(node.getAttribute("aria-label")==="Start Voice")voiceClicks++;};};
  for (const node of [addContext,reasoning,dictate,button]) count(node);
  function renderSend(mode=transition) {
    if(mode==="none" || !editor.textContent)return;
    if(mode==="reuse") {
      button.attrs={type:"submit","aria-label":"Send"};
    } else {
      const replacement=new Element("button",{type:"submit","aria-label":"Send"});
      footer.replaceChild(replacement,button);button=replacement;count(button);
    }
  }
  function renderVoice() {
    if(button.getAttribute('aria-label')==='Start Voice')return;
    const replacement=new Element("button",{type:"button","aria-label":"Start Voice","data-state":"closed"});
    footer.replaceChild(replacement,button);button=replacement;count(button);
  }
  doc.addEventListener('input',event=>{
    if(event.inputType==='deleteContentBackward' && editor.textContent==='')renderVoice();
  });
  const window=new EventTarget();window.navigation=navigation;doc.defaultView=window;
  let uuids=0;
  const context=vm.createContext({
    window,document:doc,location,navigator,URL,Date:{now:()=>clock.now},
    crypto:{randomUUID:()=>`00000000-0000-0000-0000-${(++uuids).toString().padStart(12,"0")}`},
    getComputedStyle:el=>({display:el.hidden?"none":"block",visibility:"visible"}),
    InputEvent:DOMEvent,
    setTimeout:fn=>{queueMicrotask(()=>{renderSend();onYield();clock.now+=50;fn();});}
  });
  const serializedOperation=vm.runInContext("("+operation.toString()+")",context);
  return {doc,body,footer,owner,attachments,input,rich,editor,file,clock,location,navigator,window,add,addContext,reasoning,dictate,renderSend,renderVoice,
    region,conversation,turn,assistantHeading,readAloud,moreActions,
    get button(){return button;},set transition(value){transition=value;},get voiceClicks(){return voiceClicks;},
    get clicks(){return clicks;},set onYield(fn){onYield=fn;},
    edit(text,type="input"){editor.textContent=text;doc.emit({type,target:editor});},
    navigate(url){location.href=url;navigation.listeners.forEach(fn=>fn({}));},
    op:request=>serializedOperation(request)};
}
export function harness(options = {}) {
  const page=fixture(undefined,options), pages=new Map([[1,page],[2,fixture(undefined,options)]]);
  let state,boot="boot-1",counter=0,selected=1,writeHook=()=>{},pageHook=()=>{},failTab=false;
  const calls=[],alarms=new Map();
  const io={
    boot:async()=>boot,read:async()=>structuredClone(state),
    write:async(_,s)=>{await writeHook(s);state=structuredClone(s);},
    uuid:()=>`aaaaaaaa-aaaa-aaaa-aaaa-${(++counter).toString().padStart(12,"0")}`,
    now:()=>page.clock.now,
    selectedTab:async()=>({id:selected,url:pages.get(selected).location.href,incognito:false}),
    tab:async id=>{if(failTab)throw Error("NO_ACCESS");return {id,url:pages.get(id)?.location.href,incognito:false};},
    clearAlarm:async name=>alarms.delete(name),alarm:async(name,when)=>{alarms.set(name,when);},
    page:async(binding,request)=>{
      calls.push({tab:binding.tabId,op:request.op});
      await pageHook(binding,request);
      if(binding.documentId && binding.documentId!=="doc-"+binding.tabId)throw Error("DOCUMENT_CHANGED");
      const result=await pages.get(binding.tabId).op({...request,route:binding.route,generation:binding.generation,documentToken:binding.documentToken});
      return {...result,documentId:"doc-"+binding.tabId};
    }
  };
  const h={io,page,pages,calls,alarms,newWorker:()=>new Controller(io),
    get state(){return structuredClone(state);},set state(v){state=structuredClone(v);},
    set selected(v){selected=v;},set boot(v){boot=v;},
    set failTab(v){failTab=v;},set writeHook(fn){writeHook=fn;},set pageHook(fn){pageHook=fn;}};
  h.worker=h.newWorker();
  h.bind=async()=>{await h.worker.run("bind");page.clock.now+=2100;pages.get(2).clock.now+=2100;};
  h.arm=()=>h.worker.run("arm",{delayMs:0});
  return h;
}
