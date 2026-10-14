import {Automation} from './automation.js';
import {KEY} from './policy.js';
import {validProject} from './completion-policy.js';
export const PROJECTS_KEY='bridgeProjectsV1';
const scope = p => p && validProject(p.project_ref) && /^[a-f0-9]{64}$/.test(p.scope_id) &&
  typeof p.root==='string' && p.root.startsWith('/');

// Catalog grants eligibility, never a destination. Storage stays under its original
// key for a migrated 0.3.4 install; no old intent/body is rewritten or replayed.
export class ProjectControllers {
  constructor(io, legacyProject=null) {this.io=io;this.legacyProject=legacyProject;this.controllers=new Map();this.chain=Promise.resolve();this.routes=new Map();}
  catalog(allowOffline=false) {
    const task=this.chain.then(async()=>{
      let remote;
      try {remote=await this.io.catalog();}
      catch(error) {if(!allowOffline)throw error;remote={projects:[]};}
      if(!Array.isArray(remote?.projects) || remote.projects.length>32 ||
         remote.projects.some(p=>!scope(p)) || new Set(remote.projects.map(p=>p.project_ref)).size!==remote.projects.length)
        throw Error('PROJECT_CATALOG_INVALID');
      let index=await this.io.read(PROJECTS_KEY);
      if(index===undefined)index={version:1,projects:[]};
      if(index?.version!==1 || !Array.isArray(index.projects) || index.projects.length>32 ||
        index.projects.some(p=>!scope(p) || p.key!==(p.legacy?KEY:'bridgeProjectV1:'+p.scope_id)) ||
        new Set(index.projects.map(p=>p.project_ref)).size!==index.projects.length ||
        index.projects.filter(p=>p.legacy).length>1)throw Error('PROJECT_INDEX_INVALID_NO_RESET');
      const legacy=await this.io.read(KEY);
      if(legacy!==undefined && !this.legacyProject && !index.projects.some(p=>p.legacy))throw Error('LEGACY_PROJECT_IDENTITY_REQUIRED_NO_RESET');
      let changed=false;
      for(const p of remote.projects) {
        const old=index.projects.find(x=>x.project_ref===p.project_ref);
        if(old)continue; // Root changes never reinterpret a namespace or its unknown history.
        if(index.projects.length>=32)throw Error('PROJECT_HISTORY_FULL');
        const isLegacy=legacy!==undefined && p.project_ref===this.legacyProject && !index.projects.some(x=>x.legacy);
        index.projects.push({...p,legacy:isLegacy,key:isLegacy?KEY:'bridgeProjectV1:'+p.scope_id});changed=true;
      }
      if(changed)await this.io.write(PROJECTS_KEY,index); // Unknown write result stops dispatch.
      return index.projects.map(p=>({...p,available:remote.projects.some(x=>x.project_ref===p.project_ref && x.scope_id===p.scope_id && x.root===p.root)}));
    });
    this.chain=task.catch(()=>{});return task;
  }
  controller(project) {
    if(!this.controllers.has(project.scope_id)) {
      const io=this.io.forProject(project);
      this.controllers.set(project.scope_id,new Automation({...io,project:project.project_ref,noticeVersion:4,
        read:async key=>this.io.read(key===KEY?project.key:key),
        write:async(key,value)=>this.io.write(key===KEY?project.key:key,value)}));
    }
    return this.controllers.get(project.scope_id);
  }
  serialized(route, operation) {
    const task=(this.routes.get(route)||Promise.resolve()).then(operation);
    const tail=task.catch(()=>{});this.routes.set(route,tail);
    tail.finally(()=>{if(this.routes.get(route)===tail)this.routes.delete(route);});
    return task;
  }
  async run(ref,action,arg={}) {
    const projects=await this.catalog(['status','disable','unbind','inspect','close_delivery'].includes(action)), p=projects.find(p=>p.project_ref===ref);
    if(!p)throw Error('SELECT_PROJECT');
    if(!p.available && !['status','disable','unbind','inspect','close_delivery'].includes(action))
      throw Error('PROJECT_UNAVAILABLE_HISTORY_RETAINED');
    const state=await this.controller(p).run(action,arg);
    return {projects:projects.map(({project_ref,root,available})=>({project_ref,root,available})),selected:p.project_ref,state};
  }
  async tick(startup=false) {
    const projects=await this.catalog();
    const groups=new Map();
    for(const p of projects.filter(p=>p.available)) {
      const s=await this.io.read(p.key);
      if(startup && !s?.automation?.enabled) {if(s)await this.controller(p).run('startup');continue;}
      if(!s?.automation?.enabled)continue; // Adding a project never enables it or imports old completions.
      const key=s.automation.route;
      if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);
    }
    // Same Chat is serialized; distinct Chats make progress independently.
    return Promise.allSettled([...groups.entries()].map(([route,group])=>this.serialized(route,async()=>{
      for(const p of group) {
        try {
          const c=this.controller(p);if(startup)await c.run('startup');await c.run('tick');
        } catch { /* Failure belongs to this project, never to another Chat's stream. */ }
      }
    })));
  }
}
