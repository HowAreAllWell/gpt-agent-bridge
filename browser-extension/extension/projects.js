import {Automation} from './automation.js';
import {KEY,PROJECT,ALARM,route} from './policy.js';
import {validProject} from './completion-policy.js';
export const PROJECTS_KEY='bridgeProjectsV1';
const scope=p=>p&&validProject(p.project_ref)&&/^[a-f0-9]{64}$/.test(p.scope_id)&&typeof p.root==='string'&&p.root.startsWith('/');
const offlineActions=['status','disable','unbind','inspect','cancel'];

export class ProjectControllers {
  constructor(io,legacyProject=null) {this.io=io;this.legacyProject=legacyProject;this.controllers=new Map();this.chain=Promise.resolve();this.routes=new Map();}
  exclusive(key,fn) {return this.io.exclusive?this.io.exclusive(key,fn):fn();} // injected pure harnesses; production requires native locks
  catalog(allowOffline=false) {
    const task=this.chain.then(()=>this.exclusive('catalog',async()=>{
      let remote;
      try {remote=await this.io.catalog();}catch(e){if(!allowOffline)throw e;remote={projects:[]};}
      if(!Array.isArray(remote?.projects)||remote.projects.length>32||remote.projects.some(p=>!scope(p))||new Set(remote.projects.map(p=>p.project_ref)).size!==remote.projects.length)throw Error('PROJECT_CATALOG_INVALID');
      let index=await this.io.read(PROJECTS_KEY);
      if(index===undefined)index={version:1,projects:[]};
      if(index?.version!==1||!Array.isArray(index.projects)||index.projects.some(p=>!scope(p)||p.key!==(p.legacy?KEY:'bridgeProjectV1:'+p.scope_id))||new Set(index.projects.map(p=>p.project_ref)).size!==index.projects.length||index.projects.filter(p=>p.legacy).length>1)throw Error('PROJECT_INDEX_INVALID_NO_RESET');
      const legacy=index.projects.some(p=>p.legacy)?undefined:await this.io.read(KEY);
      if(legacy!==undefined&&!index.projects.some(p=>p.legacy)) {
        const pin=this.legacyProject;
        const identity=scope(pin)?pin:{project_ref:typeof pin==='string'?pin:legacy.binding?.project||PROJECT,root:'/unverified-legacy-root',scope_id:'0'.repeat(64),unverified:true};
        index.projects.push({...identity,legacy:true,key:KEY});
        await this.io.write(PROJECTS_KEY,index);
      }
      const unverified=index.projects.find(p=>p.legacy&&p.unverified);
      if(unverified&&scope(this.legacyProject)&&this.legacyProject.project_ref===unverified.project_ref){
        Object.assign(unverified,this.legacyProject);delete unverified.unverified;unverified.requiresRebind=true;await this.io.write(PROJECTS_KEY,index);
      }
      const legacyRow=index.projects.find(p=>p.legacy);
      if(legacyRow && (!scope(this.legacyProject) || legacyRow.unverified ||
          this.legacyProject.project_ref!==legacyRow.project_ref || this.legacyProject.root!==legacyRow.root ||
          this.legacyProject.scope_id!==legacyRow.scope_id) && !legacyRow.requiresRebind) {
        legacyRow.requiresRebind=true;await this.io.write(PROJECTS_KEY,index);
      }
      // Discovery is ephemeral. Only an operation that writes state reserves a
      // durable namespace. No cumulative 32-discovery freeze; never evict history.
      const rows=[...index.projects];
      for(const p of remote.projects)if(!rows.some(x=>x.project_ref===p.project_ref))rows.push({...p,legacy:false,key:'bridgeProjectV1:'+p.scope_id});
      return rows.map(p=>({...p,available:!p.unverified&&(!p.legacy||scope(this.legacyProject)&&this.legacyProject.project_ref===p.project_ref&&this.legacyProject.root===p.root&&this.legacyProject.scope_id===p.scope_id)&&remote.projects.some(x=>x.project_ref===p.project_ref&&x.scope_id===p.scope_id&&x.root===p.root)}));
    }));
    this.chain=task.catch(()=>{});return task;
  }
  async retain(p) {
    await this.exclusive('catalog',async()=>{
      let index=await this.io.read(PROJECTS_KEY)||{version:1,projects:[]};
      const old=index.projects.find(x=>x.project_ref===p.project_ref);
      if(old){if(old.scope_id!==p.scope_id||old.root!==p.root)throw Error('PROJECT_IDENTITY_CHANGED');return;}
      // Actual storage quota errors fail this write; existing histories/controls
      // remain accessible. Never drop unknown records to admit another project.
      const {available,...row}=p;index.projects.push(row);await this.io.write(PROJECTS_KEY,index);
    });
  }
  controller(p) {
    if(!this.controllers.has(p.scope_id)) {
      const io=this.io.forProject(p);
      this.controllers.set(p.scope_id,new Automation({...io,project:p.project_ref,scopeId:p.scope_id,noticeVersion:4,
        read:key=>this.io.read(key===KEY?p.key:key),
        write:async(key,value)=>{await this.retain(p);await this.io.write(key===KEY?p.key:key,value);}}));
    }
    return this.controllers.get(p.scope_id);
  }
  serialized(route,operation) {
    const task=(this.routes.get(route)||Promise.resolve()).then(()=>this.exclusive('route:'+route,operation));
    const tail=task.catch(()=>{});this.routes.set(route,tail);tail.finally(()=>{if(this.routes.get(route)===tail)this.routes.delete(route);});return task;
  }
  async routed(p,routeOf,operation,allowRebind=false) {
    // Always route -> project. A binding can change while waiting for route
    // ownership; release both locks before requeueing, never send under its old name.
    const routesOf=s=>[...new Set([routeOf(s)].flat().filter(Boolean))].sort();
    for(let attempt=0;attempt<3;attempt++) {
      const routes=routesOf(await this.io.read(p.key));
      const owned=()=>this.exclusive('project:'+p.scope_id,async()=>{
        const current=await this.io.read(p.key);
        if(JSON.stringify(routesOf(current))!==JSON.stringify(routes))return {changed:true};
        const index=await this.io.read(PROJECTS_KEY);
        if(!allowRebind && index?.projects.some(row=>row.scope_id===p.scope_id&&row.requiresRebind))
          throw Error('LEGACY_EXPLICIT_REBIND_REQUIRED');
        return {value:await operation(current)};
      });
      // Switching owns old and new routes in sorted order before the project.
      // No old tick or other project's destination operation can overlap a bind.
      const lock=i=>i===routes.length?owned():this.serialized(routes[i],()=>lock(i+1));
      const result=await lock(0);
      if(!result.changed)return result.value;
    }
    throw Error('ROUTE_CHANGED_WAIT_NEXT_POLL');
  }
  async chooseChat(projects,p,arg) {
    const routeOf=s=>s?.automation?.route;
    const recipient=routeOf(await this.io.read(p.key));
    if(!recipient)throw Error('DRAFT_CHOICE_SOURCE_CHANGED');
    return this.serialized(recipient,async()=>{
      // Bind/tick take this same route lock. Own every participating
      // project in stable order before reading or publishing its decision.
      const candidates=[];
      for(const project of projects) {
        const s=await this.io.read(project.key);
        if(s?.automation?.enabled && routeOf(s)===recipient)candidates.push(project);
      }
      if(!candidates.some(x=>x.scope_id===p.scope_id))throw Error('DRAFT_CHOICE_SOURCE_CHANGED');
      candidates.sort((a,b)=>a.scope_id.localeCompare(b.scope_id));
      const own=async i=> {
        if(i<candidates.length)return this.exclusive('project:'+candidates[i].scope_id,()=>own(i+1));
        const index=await this.io.read(PROJECTS_KEY),rows=[];
        for(const project of candidates) {
          if(!project.available || project.requiresRebind || index?.projects.some(x=>x.scope_id===project.scope_id && x.requiresRebind))
            throw Error('PROJECT_UNAVAILABLE_HISTORY_RETAINED');
          const controller=this.controller(project),state=await controller.load();
          if(!state.automation?.enabled || routeOf(state)!==recipient)throw Error('DRAFT_CHOICE_SOURCE_CHANGED');
          rows.push({project,controller,state});
        }
        const origin=rows.find(x=>x.project.scope_id===p.scope_id);
        const publish=async changed=>{
          if(changed.length===1)return changed[0].controller.saveQueue(changed[0].state);
          if(!this.io.writeMany)throw Error('TRANSACTIONAL_STORAGE_REQUIRED');
          for(const row of changed) {row.controller.normalizeQueue(row.state.automation);row.state.revision++;}
          await this.io.writeMany(changed.map(row=>({key:rows.find(x=>x.controller===row.controller).project.key,value:row.state})));
        };
        return origin.controller.run('draft_choice',{...arg,
          peers:rows.filter(row=>row!==origin),publish});
      };
      return own(0);
    });
  }
  async run(ref,action,arg={}) {
    const projects=await this.catalog(offlineActions.includes(action)),p=projects.find(p=>p.project_ref===ref);
    if(!p)throw Error('SELECT_PROJECT');
    if(!p.available&&!offlineActions.includes(action))throw Error('PROJECT_UNAVAILABLE_HISTORY_RETAINED');
    if(p.requiresRebind&&['arm','alarm','retry'].includes(action))throw Error('LEGACY_EXPLICIT_REBIND_REQUIRED');
    if(action==='arm'&&p.project_ref!==PROJECT)throw Error('SYNTHETIC_DIAGNOSTIC_UNSUPPORTED_PROJECT'); // before allocating intent
    const operation=()=>this.exclusive('project:'+p.scope_id,()=>this.controller(p).run(action,arg));
    let recipient;
    if(action==='enable') {
      const tab=await this.controller(p).io.selectedTab(),canonical=route(tab?.url);
      if(!canonical || tab.incognito || !Number.isInteger(tab.id))throw Error('INELIGIBLE_CHAT');
      recipient={tabId:tab.id,route:canonical};
    }
    const state=await (action==='enable'?
      this.routed(p,s=>[s?.automation?.route,s?.binding?.route,recipient.route],
        ()=>this.controller(p).run(action,{...arg,recipient}),true):action==='draft_choice'?
      this.chooseChat(projects,p,arg):['arm','alarm','retry'].includes(action)?
      this.routed(p,s=>s?.binding?.route,()=>this.controller(p).run(action,arg)):operation());
    if(action==='enable'&&p.requiresRebind)await this.exclusive('catalog',async()=>{
      const index=await this.io.read(PROJECTS_KEY),row=index.projects.find(x=>x.scope_id===p.scope_id);
      if(!row)throw Error('PROJECT_IDENTITY_CHANGED');delete row.requiresRebind;await this.io.write(PROJECTS_KEY,index);
    });
    return {projects:projects.map(({project_ref,root,available})=>({project_ref,root,available})),selected:p.project_ref,state};
  }
  async alarm(name) {
    if(!name.startsWith(ALARM+':'))return;
    const id=name.slice(ALARM.length+1),p=(await this.catalog()).find(p=>p.scope_id===id&&p.available);
    if(p&&p.project_ref===PROJECT)return this.run(p.project_ref,'alarm');
  }
  async tick(startup=false) {
    const projects=await this.catalog(),snapshots=new Map();
    return Promise.allSettled(projects.filter(p=>p.available&&!p.requiresRebind).map(async p=>{
      // Independent reads start before any other project's pending read resolves.
      const s=await this.io.read(p.key);snapshots.set(p.scope_id,s);
      if(!s?.automation?.enabled){if(startup&&s)await this.exclusive('project:'+p.scope_id,()=>this.controller(p).run('startup'));return;}
      return this.routed(p,current=>current?.automation?.route,async current=>{
        if(!current?.automation?.enabled)return;
        const c=this.controller(p);if(startup)await c.run('startup');
        // Use already-resolved reads only: a broken unrelated project must
        // not become a global prerequisite. The page also fences any live banner.
        const deferAutomatic=[...snapshots].some(([id,peer])=>id!==p.scope_id &&
          peer?.automation?.enabled && peer.automation.route===current.automation.route && peer.automation.offer);
        await c.run('tick',{deferAutomatic});
      });
    }));
  }
}
