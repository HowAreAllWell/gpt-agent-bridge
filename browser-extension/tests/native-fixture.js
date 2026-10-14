import {IDBFactory} from 'fake-indexeddb';
export function nativeFixture() {
  const tails=new Map();
  return {indexedDB:new IDBFactory(),navigator:{locks:{request(name,options,fn){
    const next=(tails.get(name)||Promise.resolve()).then(()=>fn({name,mode:'exclusive'}));
    tails.set(name,next.catch(()=>{}));return next;
  }}}};
}
export const settle=async()=>{for(let i=0;i<40;i++)await new Promise(r=>setImmediate(r));};
