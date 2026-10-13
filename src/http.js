import http from 'node:http';
import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { HttpError, isUuid, createOrder, listOrders, getOrder } from './orders.js';

const files = new Map([
  ['/', ['index.html','text/html; charset=utf-8']],
  ['/app.js', ['app.js','text/javascript; charset=utf-8']],
  ['/styles.css', ['styles.css','text/css; charset=utf-8']]
]);
function mac(secret, value) { return createHmac('sha256',secret).update(value).digest('hex'); }
function equal(a,b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const left=Buffer.from(a),right=Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left,right);
}
function identity(req, config) {
  const cookie = String(req.headers.cookie || '').split(';').map(s=>s.trim()).find(s=>s.startsWith('ko_session='));
  const value = cookie?.slice('ko_session='.length) || '';
  const [id,expiry,signature] = value.split('.');
  if (value.length > 200 || !isUuid(id) || !/^\d{10}$/.test(expiry || '') || Number(expiry) < Date.now()/1000 ||
      !equal(signature,mac(config.sessionSecret,`${id}.${expiry}`))) return null;
  return id;
}
export async function writable(pool, config) {
  if (!config.writeEnabled) return false;
  const result = await pool.query('SHOW transaction_read_only');
  return result.rows[0].transaction_read_only === 'off';
}
async function body(req) {
  if (!(req.headers['content-type'] || '').startsWith('application/json')) throw new HttpError(415,'json_required');
  return new Promise((resolve,reject) => {
    let length=0; const chunks=[]; let exceeded=false;
    req.on('data', chunk => {
      length+=chunk.length;
      if (length > 16384) { exceeded=true; reject(new HttpError(413,'body_too_large')); }
      else if (!exceeded) chunks.push(chunk);
    });
    req.on('end', () => {
      if (exceeded) return;
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
      catch { reject(new HttpError(400,'invalid_json')); }
    });
    req.on('error', () => reject(new HttpError(400,'invalid_request')));
    req.on('aborted', () => reject(new HttpError(400,'invalid_request')));
  });
}

export function createServer(pool, config, { log = console.log } = {}) {
  const server = http.createServer(async (req,res) => {
    const requestId=randomUUID(); const started=Date.now();
    res.setHeader('X-Request-Id',requestId);
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Referrer-Policy','same-origin');
    res.setHeader('X-Frame-Options','DENY');
    res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
    res.setHeader('Cache-Control','no-store');
    const json=(status,data)=> { res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'}); res.end(JSON.stringify(data)); };
    res.on('finish', () => log(JSON.stringify({ event:'http_request',requestId,method:req.method,status:res.statusCode,durationMs:Date.now()-started,region:config.region })));
    try {
      const path=new URL(req.url,'http://localhost').pathname;
      if (req.method === 'GET' && path === '/health/live') return json(200,{ status:'alive',region:config.region,release:config.release });
      if (req.method === 'GET' && ['/health/ready','/health/deploy','/health'].includes(path)) {
        const schema=await pool.query('SELECT version FROM schema_versions WHERE version=1');
        if (!schema.rows[0]) throw new Error('Schema version missing');
        if (path === '/health/ready' && !await writable(pool,config)) return json(503,{ status:'standby' });
        return json(200,{ status:'ready',region:config.region,release:config.release });
      }
      if (req.method === 'GET' && path === '/api/status') return json(200,{ owner:'Kantin Tongue',region:config.region,release:config.release,writable:await writable(pool,config),paymentMode:'simulation' });
      if (req.method === 'GET' && path === '/api/products') {
        const result=await pool.query('SELECT id,name,description,category,price_cents AS "priceCents" FROM products WHERE active=true ORDER BY price_cents DESC');
        return json(200,{ products:result.rows });
      }
      if (req.method === 'GET' && path === '/api/session') {
        const id=identity(req,config) || randomUUID();
        const expiry=Math.floor(Date.now()/1000)+3*86400;
        res.setHeader('Set-Cookie',`ko_session=${id}.${expiry}.${mac(config.sessionSecret,`${id}.${expiry}`)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=259200${config.production?'; Secure':''}`);
        return json(200,{ csrfToken:mac(config.sessionSecret,`csrf:${id}`) });
      }
      if (path.startsWith('/api/orders')) {
        const customer=identity(req,config);
        if (!customer) throw new HttpError(401,'session_required');
        if (path === '/api/orders' && req.method === 'GET') return json(200,{ orders:await listOrders(pool,customer) });
        if (path === '/api/orders' && req.method === 'POST') {
          if (!equal(req.headers['x-csrf-token'],mac(config.sessionSecret,`csrf:${customer}`))) throw new HttpError(403,'csrf_required');
          if (!await writable(pool,config)) throw new HttpError(503,'standby_read_only');
          const result=await createOrder(pool,customer,req.headers['idempotency-key'],await body(req),config.region);
          return json(result.replay?200:201,result);
        }
        const match=path.match(/^\/api\/orders\/([^/]+)$/);
        if (match && req.method === 'GET') return json(200,{ order:await getOrder(pool,customer,match[1]) });
      }
      if (req.method === 'GET' && files.has(path)) {
        const [file,type]=files.get(path);
        const bytes=await readFile(new URL(`../public/${file}`,import.meta.url));
        res.writeHead(200,{'Content-Type':type}); return res.end(bytes);
      }
      throw new HttpError(404,'not_found');
    } catch (error) {
      const known=error instanceof HttpError;
      if (!known) log(JSON.stringify({ event:'request_failed',requestId,errorCode:/^[0-9A-Z]{5}$/.test(error.code || '')?error.code:'internal',region:config.region }));
      if (!res.headersSent) json(known?error.status:503,{ error:known?error.code:'service_unavailable',requestId });
      else res.end();
    }
  });
  server.requestTimeout=15000; server.headersTimeout=10000; server.keepAliveTimeout=5000;
  server.maxHeadersCount=40;
  return server;
}
