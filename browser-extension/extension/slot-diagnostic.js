// Serialized independently of the send adapter. No SLOT access or page mutation.
export function inspectAttachmentSlots(request) {
  try {
    const u = new URL(location.href);
    if (!request || u.origin !== "https://chatgpt.com" || u.username || u.password ||
        u.href !== u.origin + u.pathname || u.href !== request.route ||
        !/^\/(?:g\/g-p-[0-9a-f]{32}-[a-z]+(?:-[a-z]+)*\/)?c\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(u.pathname))
      return {ok:false, code:"SLOT_DIAGNOSTIC_ROUTE_MISMATCH"};
    const tags = ["DIV","SPAN","P","BR","INPUT","BUTTON","IMG","SVG","PATH","TEMPLATE","SLOT","UL","LI","A","FORM","STYLE","SCRIPT"];
    const displays = ["none","contents","block","inline","inline-block","flex","inline-flex","grid","inline-grid","flow-root","list-item","table","table-row","table-cell"];
    const tag = node => { const value = (node.tagName || "").toUpperCase(); return tags.includes(value) ? value : "OTHER"; };
    const pick = (value, values) => values.includes(value) ? value : "other";
    const bodies = document.querySelectorAll("[data-composer-body]");
    const snapshot = {observation:"CURRENT_STRUCTURE_NOT_FAILURE_SNAPSHOT",
      bodyCount:bodies.length, bodiesTruncated:bodies.length > 4, bodies:[]};
    for (let i=0;i<Math.min(bodies.length,4);i++) {
      const body = bodies[i], layout = body.getAttribute("data-composer-layout");
      const slots = body.querySelectorAll("[data-composer-attachments]");
      const info = {layout:layout === null ? "absent" : pick(layout,["single-line","multi-line","multiline"]),
        slotCount:slots.length, slotsTruncated:slots.length > 4, slots:[]};
      for (let j=0;j<Math.min(slots.length,4);j++) {
        const slot = slots[j], hidden = slot.getAttribute("hidden"), css = getComputedStyle(slot);
        const item = {tag:tag(slot), hiddenPresent:hidden !== null,
          hiddenState:hidden === null ? "absent" : hidden === "" ? "empty" : pick(hidden,["hidden","until-found"]),
          display:pick(css.display,displays), visibility:pick(css.visibility,["visible","hidden","collapse"]),
          rectCount:slot.getClientRects().length, childCount:slot.childNodes.length,
          childrenTruncated:slot.childNodes.length > 8, children:[]};
        for (let k=0;k<Math.min(slot.childNodes.length,8);k++) {
          const child = slot.childNodes[k];
          item.children.push({nodeType:child.nodeType, tag:child.nodeType === 1 ? tag(child) : null,
            childCount:child.childNodes?.length || 0, hasNonWhitespace:/\S/.test(child.textContent || "")});
        }
        info.slots.push(item);
      }
      snapshot.bodies.push(info);
    }
    if (location.href !== request.route) return {ok:false, code:"SLOT_DIAGNOSTIC_ROUTE_MISMATCH"};
    return {ok:true, snapshot};
  } catch {
    return {ok:false, code:"SLOT_DIAGNOSTIC_READ_UNAVAILABLE"};
  }
}

// Accept only this fixed, bounded, content-free shape before returning it to popup.
export function validSlotSnapshot(s) {
  const keys = (o, names) => o && typeof o === "object" && !Array.isArray(o) &&
    Object.keys(o).length === names.length && names.every(k => Object.hasOwn(o,k));
  const count = n => Number.isSafeInteger(n) && n >= 0;
  const limited = (items,n,cut,max) => count(n) && Array.isArray(items) &&
    items.length === Math.min(n,max) && cut === (n > max);
  const tags = ["DIV","SPAN","P","BR","INPUT","BUTTON","IMG","SVG","PATH","TEMPLATE","SLOT","UL","LI","A","FORM","STYLE","SCRIPT","OTHER"];
  const displays = ["none","contents","block","inline","inline-block","flex","inline-flex","grid","inline-grid","flow-root","list-item","table","table-row","table-cell","other"];
  if (!keys(s,["observation","bodyCount","bodiesTruncated","bodies"]) ||
      s.observation !== "CURRENT_STRUCTURE_NOT_FAILURE_SNAPSHOT" ||
      !limited(s.bodies,s.bodyCount,s.bodiesTruncated,4)) return false;
  return s.bodies.every(b => keys(b,["layout","slotCount","slotsTruncated","slots"]) &&
    ["absent","single-line","multi-line","multiline","other"].includes(b.layout) &&
    limited(b.slots,b.slotCount,b.slotsTruncated,4) && b.slots.every(slot =>
      keys(slot,["tag","hiddenPresent","hiddenState","display","visibility","rectCount","childCount","childrenTruncated","children"]) &&
      tags.includes(slot.tag) && typeof slot.hiddenPresent === "boolean" &&
      ["absent","empty","hidden","until-found","other"].includes(slot.hiddenState) &&
      slot.hiddenPresent === (slot.hiddenState !== "absent") &&
      displays.includes(slot.display) && ["visible","hidden","collapse","other"].includes(slot.visibility) &&
      count(slot.rectCount) && limited(slot.children,slot.childCount,slot.childrenTruncated,8) &&
      slot.children.every(c => keys(c,["nodeType","tag","childCount","hasNonWhitespace"]) &&
        Number.isInteger(c.nodeType) && c.nodeType >= 1 && c.nodeType <= 12 &&
        (c.nodeType === 1 ? tags.includes(c.tag) : c.tag === null) &&
        count(c.childCount) && typeof c.hasNonWhitespace === "boolean")));
}
