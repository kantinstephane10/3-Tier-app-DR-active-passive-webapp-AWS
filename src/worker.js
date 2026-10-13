import { setTimeout } from 'node:timers/promises';
import { loadConfig,createPool } from './config.js';
import { processNextJob } from './orders.js';
import { writable } from './http.js';
const config=await loadConfig(); const pool=createPool(config);
let stopping=false;
process.on('SIGTERM',()=>{stopping=true;}); process.on('SIGINT',()=>{stopping=true;});
try {
  while (!stopping) {
    try {
      if (await writable(pool,config) && await processNextJob(pool)) {
        console.log(JSON.stringify({ event:'order_fulfilled',region:config.region }));
        continue;
      }
    } catch { console.error(JSON.stringify({ event:'worker_retry',region:config.region })); }
    await setTimeout(2000);
  }
} finally { await pool.end(); }
