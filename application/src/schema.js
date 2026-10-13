import { readFile } from 'node:fs/promises';

export async function migrate(pool) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query('SELECT pg_advisory_xact_lock(84219301)');
    const state = await client.query('SHOW transaction_read_only');
    if (state.rows[0].transaction_read_only === 'on') throw new Error('Cannot migrate a read replica');
    await client.query(await readFile(new URL('../db/001-initial.sql', import.meta.url), 'utf8'));
    await client.query('COMMIT');
  } catch (error) { await client.query('ROLLBACK'); throw error; }
  finally { client.release(); }
}
