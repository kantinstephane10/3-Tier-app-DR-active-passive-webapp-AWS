import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { createPglitePool } from './pglite-pool.js';
import pg from 'pg';
import { migrate } from '../src/schema.js';
import { createServer, writable } from '../src/http.js';
import { createOrder, processNextJob, validateItems } from '../src/orders.js';
import { loadConfig } from '../src/config.js';

let pool,server,base;
const config={ production:false,sessionSecret:'test-session-secret-with-at-least-32-characters',region:'us-east-1',release:'test',writeEnabled:true };

before(async()=>{
  if(process.env.TEST_DATABASE_URL){
    const url=new URL(process.env.TEST_DATABASE_URL);
    assert.match(url.pathname,/_test$/, 'Integration database name must end in _test');
    const schema=`test_${randomUUID().replaceAll('-','')}`;
    const admin=new pg.Pool({connectionString:url.href});
    await admin.query(`CREATE SCHEMA ${schema}`);await admin.end();
    pool=new pg.Pool({connectionString:url.href,options:`-c search_path=${schema},public`});
    pool.testSchema=schema;
  } else pool=await createPglitePool();
  await migrate(pool);
  server=createServer(pool,config,{log:()=>{}});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  base=`http://127.0.0.1:${server.address().port}`;
});
after(async()=>{
  if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
  if(pool?.testSchema)await pool.query(`DROP SCHEMA ${pool.testSchema} CASCADE`);
  if(pool)await pool.end();
});
async function session(){const response=await fetch(`${base}/api/session`);return{cookie:response.headers.get('set-cookie').split(';')[0],csrf:(await response.json()).csrfToken};}
async function post(client,items,key=randomUUID(),headers={}){
  return fetch(`${base}/api/orders`,{method:'POST',headers:{'Content-Type':'application/json',Cookie:client.cookie,'X-CSRF-Token':client.csrf,'Idempotency-Key':key,...headers},body:JSON.stringify({items})});
}

test('migrations are repeatable and catalog comes from PostgreSQL',async()=>{
  await migrate(pool);
  const response=await fetch(`${base}/api/products`);
  assert.equal(response.status,200);assert.equal((await response.json()).products.length,6);
});
test('checkout calculates trusted prices and commits the pending job',async()=>{
  const client=await session();
  const response=await post(client,[{productId:'cloud-notebook',quantity:2,priceCents:1},{productId:'tote',quantity:1}]);
  assert.equal(response.status,201);const {order}=await response.json();assert.equal(order.totalCents,7000);assert.equal(order.status,'PENDING');
  assert.equal((await pool.query('SELECT order_id FROM jobs WHERE order_id=$1',[order.id])).rows.length,1);
});
test('concurrent idempotent retries create one order and one job',async()=>{
  const client=await session(),key=randomUUID(),items=[{productId:'tote',quantity:1}];
  const responses=await Promise.all([post(client,items,key),post(client,items,key),post(client,items,key)]);
  const values=await Promise.all(responses.map(r=>r.json()));
  assert.deepEqual(responses.map(r=>r.status).sort(),[200,200,201]);
  assert.equal(new Set(values.map(v=>v.order.id)).size,1);
  assert.equal((await pool.query('SELECT count(*)::int AS total FROM jobs WHERE order_id=$1',[values[0].order.id])).rows[0].total,1);
});
test('reusing an idempotency key for a changed order is rejected',async()=>{
  const client=await session(),key=randomUUID();await post(client,[{productId:'tote',quantity:1}],key);
  const response=await post(client,[{productId:'tote',quantity:2}],key);assert.equal(response.status,409);
});
test('guest sessions cannot retrieve another browser’s order',async()=>{
  const a=await session(),b=await session();const {order}=await(await post(a,[{productId:'tote',quantity:1}])).json();
  assert.equal((await fetch(`${base}/api/orders/${order.id}`,{headers:{Cookie:b.cookie}})).status,404);
  assert.equal((await fetch(`${base}/api/orders/${order.id}`,{headers:{Cookie:a.cookie}})).status,200);
});
test('mutation requires a signed session and matching CSRF token',async()=>{
  const client=await session();assert.equal((await post(client,[{productId:'tote',quantity:1}],randomUUID(),{'X-CSRF-Token':'bad'})).status,403);
  assert.equal((await post({...client,cookie:'ko_session=forged'},[{productId:'tote',quantity:1}])).status,401);
});
test('unknown products roll back without partial orders',async()=>{
  const client=await session();const before=(await pool.query('SELECT count(*)::int AS n FROM orders')).rows[0].n;
  assert.equal((await post(client,[{productId:'unknown',quantity:1}])).status,400);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM orders')).rows[0].n,before);
});
test('worker fulfills pending orders once and safely handles an empty queue',async()=>{
  await Promise.all([processNextJob(pool),processNextJob(pool),processNextJob(pool)]);
  while(await processNextJob(pool)){}
  assert.equal(await processNextJob(pool),false);
  assert.equal((await pool.query("SELECT count(*)::int AS n FROM orders WHERE status='PENDING'")).rows[0].n,0);
});
test('standby rejects checkout and readiness, but deployment health works',async()=>{
  config.writeEnabled=false;
  try{
    const client=await session();assert.equal((await post(client,[{productId:'tote',quantity:1}])).status,503);
    assert.equal((await fetch(`${base}/health/ready`)).status,503);
    assert.equal((await fetch(`${base}/health/deploy`)).status,200);
    assert.equal((await fetch(`${base}/health`)).status,200);
  }finally{config.writeEnabled=true;}
});
test('database read-only mode blocks writes even when write flag is active',async()=>{
  const client=await pool.connect();
  try{await client.query('BEGIN READ ONLY');assert.equal(await writable(client,config),false);}
  finally{await client.query('ROLLBACK');client.release();}
});
test('input validation rejects duplicates, excessive quantities and injection-like IDs',()=>{
  for(const items of [[{productId:'tote',quantity:11}],[{productId:"tote';DROP",quantity:1}],[{productId:'tote',quantity:1},{productId:'tote',quantity:2}]])assert.throws(()=>validateItems({items}));
});
test('production cannot disable database TLS or omit Secrets Manager',async()=>{
  await assert.rejects(loadConfig({NODE_ENV:'production',SESSION_SECRET:config.sessionSecret,DB_SSL:'false'}));
});
test('limited runtime DB role supports orders and jobs without catalog write privileges',async()=>{
  const client=await pool.connect();const role=`runtime_${randomUUID().replaceAll('-','')}`;
  const schema=(await client.query('SELECT current_schema() AS name')).rows[0].name;
  try{
    await client.query(`CREATE ROLE ${role}`);
    await client.query(`GRANT USAGE ON SCHEMA ${schema} TO ${role}`);
    await client.query(`GRANT SELECT ON products,schema_versions TO ${role}`);
    await client.query(`GRANT SELECT,INSERT,UPDATE ON orders,order_items,jobs TO ${role}`);
    await client.query(`SET ROLE ${role}`);
    const runtimePool={connect:async()=>({query:client.query.bind(client),release:()=>{}}),query:client.query.bind(client)};
    const result=await createOrder(runtimePool,randomUUID(),randomUUID(),{items:[{productId:'tote',quantity:1}]},'test');
    assert.equal(result.order.totalCents,2200);assert.equal(await processNextJob(runtimePool),true);
    await assert.rejects(client.query("UPDATE products SET price_cents=1 WHERE id='tote'"),error=>error.code==='42501');
  }finally{
    await client.query('RESET ROLE');await client.query(`DROP OWNED BY ${role}`);await client.query(`DROP ROLE ${role}`);client.release();
  }
});
