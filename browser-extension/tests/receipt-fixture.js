// Synthetic text/IDs, topology and role attributes observed on the selected Chat.
import vm from 'node:vm';
import {fixture} from './harness.js';
import {observeReceipt} from '../extension/receipt.js';
export function messageFixture(page=fixture()) {
 const {add,doc}=page;
 doc.visibilityState='hidden';doc.hasFocus=()=>false;
 const region=page.region;
 const root=page.conversation;
 let count=0;
 function user(message,withReply) {
  const key='fallback-turn-'+(++count),uuid='11111111-2222-3333-4444-'+String(count).padStart(12,'0');
  const turn=add(root,'div',{'data-turn-key':uuid});
  const search=add(turn,'div',{'data-content-search-turn-key':key}),block=add(search,'div');
  const h=add(block,'h4',{class:'sr-only'});h.textContent='You said:';
  const unit=add(block,'div',{'data-chatgpt-search-unit-key':key+':0:user','data-chatgpt-search-message-ids':uuid});
  const content=add(unit,'div',{'data-content-search-unit-key':key+':0:user'});
  const bubble=add(add(content,'div'),'div',{'data-user-message-bubble':'true'});
  const target=add(add(add(bubble,'div'),'div'),'div',{'data-search-result-target':''});
  const leaf=add(add(target,'div'),'div',{class:'text-size-chat whitespace-pre-wrap'});leaf.textContent=message;
  const assistant=add(search,'div',{'data-chatgpt-search-unit-key':key+':2:assistant'});
  add(assistant,'h4',{class:'sr-only'}).textContent='ChatGPT said:';
  add(assistant,'button',{'aria-label':'Read aloud'});
  add(assistant,'button',{'aria-label':'More actions'});
  if(withReply)add(assistant,'p').textContent=withReply;
  return {turn,search,block,h,unit,content,bubble,target,leaf,assistant};
 }
 function observe(request) {
  return vm.runInNewContext('('+observeReceipt.toString()+')(request)',{document:doc,location:page.location,
   getComputedStyle:e=>({display:e.hidden?'none':'block',visibility:'visible'}),request});
 }
 return {page,root,region,user,observe};
}
