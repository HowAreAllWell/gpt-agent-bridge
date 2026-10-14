import {wireWorker} from '../extension/wiring.js';
import {KEY} from '../extension/policy.js';
export const project={project_ref:'gpt-agent-bridge',root:'/synthetic/bridge',scope_id:'a'.repeat(64)};
export function setupWorker(chrome) {
  wireWorker(chrome,{extension_id:'prototype',url:'http://127.0.0.1:8765',token:'synthetic',project_ref:project.project_ref},async()=>({ok:true,json:async()=>({projects:[project]})}));
}
export function seedIndex(data) {
  data.bridgeProjectsV1={version:1,projects:[{...project,legacy:true,key:KEY}]};
}
