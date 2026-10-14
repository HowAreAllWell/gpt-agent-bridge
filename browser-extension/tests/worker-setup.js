import {wireWorker} from '../extension/wiring.js';
import {stateStore} from '../extension/state-store.js';
import {nativeFixture} from './native-fixture.js';
import {KEY} from '../extension/policy.js';
export const project={project_ref:'gpt-agent-bridge',root:'/synthetic/bridge',scope_id:'a'.repeat(64)};
export async function setupWorker(chrome) {
  const native=nativeFixture(),store=stateStore(native.indexedDB,async k=>(await chrome.storage.local.get(k))[k],{
    read:async()=>(await chrome.storage.local.get('bridgeTransactionalStoreV1')).bridgeTransactionalStoreV1,
    write:async value=>chrome.storage.local.set({bridgeTransactionalStoreV1:value})
  });
  // Finish one-time unchanged import before exercising read-only diagnostics.
  await store.read('bridgeProjectsV1');await store.read(KEY);
  wireWorker(chrome,{extension_id:'prototype',url:'http://127.0.0.1:8765',token:'synthetic',legacy_identity:project},async()=>({ok:true,json:async()=>({projects:[project]})}),native);
  return store;
}
export function seedIndex(data) {
  data.bridgeProjectsV1={version:1,projects:[{...project,legacy:true,key:KEY}]};
}
