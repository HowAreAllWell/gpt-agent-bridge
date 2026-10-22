// Native transactions fence state writes across worker lifetimes. Chrome local
// records are imported once, unchanged, and retained as the migration source.
// No transaction spans network/DOM work. Missing APIs fail closed.
export function stateStore(indexedDB, legacyRead, witness={read:async()=>false,write:async()=>{}}, exclusive=nativeExclusive(globalThis.navigator?.locks)) {
  const opened=exclusive('storage-initialize',async()=>{
    const migrated=await witness.read();
    if(migrated!==undefined&&migrated!==false&&migrated!==true)throw Error('STATE_MIGRATION_WITNESS_INVALID');
    return new Promise((resolve,reject)=>{
    if(!indexedDB) {reject(Error('TRANSACTIONAL_STORAGE_REQUIRED'));return;}
    const r=indexedDB.open('bridge-notice-state',1);
    r.onupgradeneeded=()=>{
      if(migrated){r.transaction.abort();reject(Error('TRANSACTIONAL_STATE_LOST_NO_LEGACY_REPLAY'));return;}
      r.result.createObjectStore('records');
    };
    r.onsuccess=()=>Promise.resolve(migrated?undefined:witness.write(true)).then(()=>resolve(r.result),reject);r.onerror=()=>reject(r.error);
    });
  });
  opened.catch(()=>{}); // consumed by each operation; avoid an unhandled startup rejection
  const observed=new Map();
  const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  async function transaction(key,update) {
    const db=await opened;
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('records','readwrite'),store=tx.objectStore('records');
      let result,error;
      const r=store.get(key);
      r.onsuccess=()=>{try {const next=update(r.result);result=next.value;if(next.write)store.put({value:next.value},key);}catch(e){error=e;tx.abort();}};
      tx.oncomplete=()=>resolve(structuredClone(result));
      tx.onabort=tx.onerror=()=>reject(error||tx.error||Error('STATE_TRANSACTION_UNKNOWN'));
    });
  }
  return {
    async read(key) {
      // Legacy access is read-only. Its failure is scoped to this key. Recheck
      // inside the transaction: a competing import/write always wins over this copy.
      const db=await opened;
      const existing=await new Promise((resolve,reject)=>{const tx=db.transaction('records');const r=tx.objectStore('records').get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
      let value;
      if(existing)value=existing.value;
      else {const old=await legacyRead(key);value=await transaction(key,row=>row?{value:row.value}:{value:old,write:old!==undefined});}
      observed.set(key,structuredClone(value));return structuredClone(value);
    },
    async writeMany(rows) {
      if(!Array.isArray(rows) || !rows.length || rows.length>32 || new Set(rows.map(x=>x.key)).size!==rows.length ||
        rows.some(x=>!observed.has(x.key)))throw Error('STATE_READ_REQUIRED');
      const expected=new Map(rows.map(x=>[x.key,structuredClone(observed.get(x.key))]));
      const db=await opened;
      await new Promise((resolve,reject)=>{
        const tx=db.transaction('records','readwrite'),store=tx.objectStore('records');let error;
        for(const {key,value} of rows) {
          const r=store.get(key);
          r.onsuccess=()=>{try {
            if(!equal(r.result?.value,expected.get(key)) || value?.schema!==1 ||
              value.revision!==(r.result?.value?.revision??-1)+1)throw Error('STATE_CHANGED_NO_OVERWRITE');
            store.put({value},key);
          }catch(e){error=e;tx.abort();}};
        }
        tx.oncomplete=resolve;tx.onabort=tx.onerror=()=>reject(error||tx.error||Error('STATE_TRANSACTION_UNKNOWN'));
      });
      for(const {key,value} of rows)observed.set(key,structuredClone(value));
    },
    async write(key,value) {
      if(!observed.has(key))throw Error('STATE_READ_REQUIRED');
      const expected=observed.get(key);
      await transaction(key,row=>{
        if(!equal(row?.value,expected) || value?.schema===1 &&
          value.revision!==(row?.value?.revision??-1)+1 && !(row?.value===undefined&&value.revision===1))
          throw Error('STATE_CHANGED_NO_OVERWRITE');
        return {value,write:true};
      });
      observed.set(key,structuredClone(value));
    }
  };
}

export function nativeExclusive(locks) {
  return (key,operation)=>{
    if(!locks?.request)return Promise.reject(Error('NATIVE_LOCKS_REQUIRED'));
    // Never steal/time out a held lock. Termination releases the lock; native
    // transactions order or abort outstanding writes before another transaction.
    return locks.request('bridge-notice:'+key,{mode:'exclusive'},operation);
  };
}
