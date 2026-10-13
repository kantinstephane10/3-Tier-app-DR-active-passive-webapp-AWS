import { loadConfig, createPool } from './config.js';
import { migrate } from './schema.js';
import { readFile } from 'node:fs/promises';
const config = await loadConfig({ ...process.env, APP_SECRET_ARN: process.env.MIGRATION_SECRET_ARN || process.env.APP_SECRET_ARN }, { requireSession: false });
if (!config.writeEnabled) throw new Error('Migrations are disabled in standby mode');
const pool = createPool(config);
try {
  await migrate(pool);
  if (config.production) await pool.query(await readFile(new URL('../db/grants.sql',import.meta.url),'utf8'));
  console.log(JSON.stringify({ event: 'migration_complete' }));
}
finally { await pool.end(); }
