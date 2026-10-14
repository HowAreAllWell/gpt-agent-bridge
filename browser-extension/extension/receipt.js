// Serialized read-only observation of the bounded, observed ChatGPT message structure.
export function observeReceipt(request) {
  const fail=code=>({ok:false,code});
  if(location.href!==request.route)return fail('ROUTE_CHANGED_REBIND');
  if(typeof request.message!=='string' || request.message.length>160000 ||
    !/^(?:(?:work|batch)-[0-9a-f]{16}|test-[0-9a-f-]{36})$/.test(request.id))return fail('INVALID_RECEIPT_REQUEST');
  const all=(root,selector)=>[...root.querySelectorAll(selector)];
  const visible=e=>e.getClientRects().length>0 && getComputedStyle(e).display!=='none' && getComputedStyle(e).visibility!=='hidden';
  if(all(document,'dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"],iframe,[role="alert"]').some(visible))return fail('DIALOG_OR_CHALLENGE');
  const ROOT='div[data-thread-find-target="conversation"][data-chatgpt-conversation-selection-target="true"]';
  const roots=all(document,ROOT);
  if(roots.length!==1 || !visible(roots[0]) || !roots[0].closest('div[role="region"][aria-label="Conversation"][data-app-action-timeline-scroll]'))
    return fail('RECEIPT_STRUCTURE_UNKNOWN');
  const root=roots[0], excluded='[contenteditable],textarea,input,select,blockquote,q,pre,code,[data-composer-body],[role="dialog"],[role="alertdialog"]';
  if(root.closest(excluded))return fail('RECEIPT_STRUCTURE_UNKNOWN');
  const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const heading=(node,label)=>node?.tagName==='H4' && (node.getAttribute('class')||'').split(/\s+/).includes('sr-only') && node.textContent===label;
  let notices=0,replies=0,tooMany=false;const turnKeys=[];
  const draft=all(document,'[contenteditable],textarea,input').some(e=>(e.textContent||e.value||'').includes(request.id));
  // No document-wide text/XPath fallback. A preview outside these message roots is irrelevant.
  const bubbles=all(root,'[data-user-message-bubble]');
  if(bubbles.length>2000)return fail('RECEIPT_STRUCTURE_LIMIT');
  for(const bubble of bubbles) {
    if(bubble.textContent.trim()!==request.message)continue;
    if(bubble.tagName!=='DIV' || bubble.getAttribute('data-user-message-bubble')!=='true' ||
      !visible(bubble) || bubble.closest(excluded) || all(bubble,excluded).length)continue;
    const unit=bubble.closest('[data-chatgpt-search-unit-key]'), turn=bubble.closest('[data-turn-key]'), search=bubble.closest('[data-content-search-turn-key]');
    if(!unit || !turn || !search || [unit,turn,search].some(e=>e.tagName!=='DIV' || e.closest(ROOT)!==root))continue;
    const turnKey=turn.getAttribute('data-turn-key'), searchKey=search.getAttribute('data-content-search-turn-key');
    if(!uuid.test(turnKey||'') || !searchKey || searchKey.length>128 || search.closest('[data-turn-key]')!==turn ||
      unit.getAttribute('data-chatgpt-search-message-ids')!==turnKey || unit.getAttribute('data-chatgpt-search-unit-key')!==searchKey+':0:user')continue;
    // Observed user block: direct "You said:" heading + one user unit, not assistant/quote content.
    const block=unit.parentElement, children=block?.children;
    if(!children || children.length!==2 || !heading(children[0],'You said:') || children[1]!==unit ||
      unit.children.length!==1 || unit.children[0].getAttribute('data-content-search-unit-key')!==searchKey+':0:user' ||
      all(unit,'[data-user-message-bubble]').length!==1 || all(unit,'[data-chatgpt-search-unit-key]').length)continue;
    const contents=all(bubble,'[data-search-result-target]');
    if(contents.length!==1 || contents[0].getAttribute('data-search-result-target')!=='' || contents[0].children.length!==1)continue;
    const wrapper=contents[0].children[0], leaf=wrapper.children[0];
    if(wrapper.tagName!=='DIV' || wrapper.children.length!==1 || !leaf || leaf.tagName!=='DIV' || leaf.children.length ||
      !(leaf.getAttribute('class')||'').split(/\s+/).includes('whitespace-pre-wrap') || leaf.textContent.trim()!==request.message)continue;
    notices++;turnKeys.push(turnKey);
    if(notices>64){tooMany=true;break;}
    // Legacy synthetic receipts retain their additional same-turn exact reply requirement.
    // Real completion receipts do not require any assistant reply.
    for(const assistant of all(turn,'[data-chatgpt-search-unit-key]')) {
      const key=assistant.getAttribute('data-chatgpt-search-unit-key')||'';
      if(assistant.closest('[data-content-search-turn-key]')!==search || !key.startsWith(searchKey+':') ||
        !/^[0-9]+:assistant$/.test(key.slice(searchKey.length+1)) || !heading(assistant.children[0],'ChatGPT said:') || assistant.closest(excluded))continue;
      replies+=all(assistant,'p').filter(p=>p.textContent.trim()===request.id && !p.closest(excluded) && visible(p)).length;
    }
  }
  const visibility=document.visibilityState,focused=document.hasFocus();
  return {ok:location.href===request.route,code:'USER_MESSAGE_RECEIPT_OBSERVED',scope:'chat-user-message-v1',
    notices,replies,draft,tooMany,turnKeys,visibility,focused};
}
