import { readFile } from 'node:fs/promises';
import pg from 'pg';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

export async function loadConfig(env = process.env, { requireSession = true } = {}) {
  const production = env.NODE_ENV === 'production';
  let secrets = {};
  if (env.APP_SECRET_ARN) {
    const client = new SecretsManagerClient({ region: env.AWS_REGION });
    const result = await client.send(new GetSecretValueCommand({ SecretId: env.APP_SECRET_ARN }));
    try { secrets = JSON.parse(result.SecretString); }
    catch { throw new Error('Invalid Secrets Manager JSON'); }
    client.destroy();
  }
  const sessionSecret = secrets.sessionSecret || env.SESSION_SECRET;
  if (requireSession && (typeof sessionSecret !== 'string' || sessionSecret.length < 32)) throw new Error('A session secret of at least 32 characters is required');
  if (production && !env.APP_SECRET_ARN) throw new Error('Production requires APP_SECRET_ARN');
  if (production && env.DB_SSL === 'false') throw new Error('Production requires verified database TLS');
  let release='local';
  try { release=JSON.parse(await readFile(new URL('../release.json',import.meta.url),'utf8')).release; } catch { /* Local source checkout. */ }
  const config = {
    production, sessionSecret, port: Number(env.PORT || 3000),
    region: env.AWS_REGION || 'local', release: env.RELEASE_ID || release,
    writeEnabled: env.WRITE_ENABLED === 'true',
    db: { max: 10, connectionTimeoutMillis: 5000, idleTimeoutMillis: 30000,
      statement_timeout: 5000, query_timeout: 8000, application_name: 'kantin-orders' }
  };
  if (!Number.isInteger(config.port) || config.port < 0 || config.port > 65535) throw new Error('Invalid port');
  if (secrets.host) {
    for (const field of ['host','dbname','username','password']) if (typeof secrets[field] !== 'string' || !secrets[field]) throw new Error('Incomplete database secret');
    Object.assign(config.db, { host: secrets.host, port: Number(secrets.port || 5432),
      database: secrets.dbname, user: secrets.username, password: secrets.password });
  } else if (env.DATABASE_URL && !production) {
    config.db.connectionString = env.DATABASE_URL;
  } else throw new Error('Database configuration is required');
  if (env.DB_SSL !== 'false') {
    const ca = env.DB_CA_FILE ? await readFile(env.DB_CA_FILE, 'utf8') : undefined;
    config.db.ssl = { rejectUnauthorized: true, ...(ca ? { ca } : {}) };
  }
  return config;
}

export function createPool(config) {
  const pool = new pg.Pool(config.db);
  pool.on('error', () => console.error(JSON.stringify({ event: 'database_pool_error' })));
  return pool;
}
