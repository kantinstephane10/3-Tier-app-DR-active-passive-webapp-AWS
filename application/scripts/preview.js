import { randomBytes } from 'node:crypto';
import { createPglitePool } from '../test/pglite-pool.js';
import { migrate } from '../src/schema.js';
import { createServer } from '../src/http.js';
import { processNextJob } from '../src/orders.js';
if(process.env.NODE_ENV==='production')throw new Error('Preview is development only');
const pool=await createPglitePool();await migrate(pool);
const config={production:false,sessionSecret:randomBytes(32).toString('hex'),region:'local-preview',release:'local',writeEnabled:true};
const server=createServer(pool,config);
server.listen(Number(process.env.PORT||3000),'127.0.0.1',()=>console.log('Preview: http://127.0.0.1:'+(process.env.PORT||3000)+' (temporary database; resets on restart)'));
let working=false;
const worker=setInterval(async()=>{if(working)return;working=true;try{while(await processNextJob(pool)) {}}catch{console.error('Preview worker failed');}finally{working=false;}},1000);
async function stop(){clearInterval(worker);server.closeAllConnections();server.close(async()=>{await pool.end();});}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
