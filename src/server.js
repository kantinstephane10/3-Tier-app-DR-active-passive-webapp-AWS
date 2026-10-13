import { loadConfig, createPool } from './config.js';
import { createServer } from './http.js';
const config=await loadConfig();
const pool=createPool(config);
const server=createServer(pool,config);
server.listen(config.port,'0.0.0.0',()=>console.log(JSON.stringify({ event:'api_started',port:config.port,region:config.region,release:config.release })));
let closing=false;
async function shutdown() {
  if (closing) return; closing=true;
  const timer=setTimeout(()=>process.exit(1),10000); timer.unref();
  server.close(async()=>{ await pool.end(); clearTimeout(timer); });
  server.closeIdleConnections();
}
process.on('SIGTERM',shutdown); process.on('SIGINT',shutdown);
