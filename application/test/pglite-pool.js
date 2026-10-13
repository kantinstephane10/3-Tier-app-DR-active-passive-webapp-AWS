import { PGlite } from '@electric-sql/pglite';

// Development/testing adapter only. Production uses the real node-postgres pool.
export async function createPglitePool() {
  const engine=new PGlite(); await engine.waitReady;
  let tail=Promise.resolve();
  async function lock(){const previous=tail;let unlock;tail=new Promise(resolve=>{unlock=resolve;});await previous;return unlock;}
  async function query(sql,params){
    if(sql.includes('CREATE TABLE') || sql.includes('GRANT CONNECT')){await engine.exec(sql);return{rows:[]};}
    return engine.query(sql,params);
  }
  return {
    async connect(){const unlock=await lock();return{query,release:unlock};},
    async query(sql,params){const unlock=await lock();try{return await query(sql,params);}finally{unlock();}},
    async end(){await engine.close();}
  };
}
