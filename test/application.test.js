import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/http.js';
import { validateItems, requestHash, createOrder, processNextJob } from '../src/orders.js';
import { loadConfig } from '../src/config.js';

const config={production:true,sessionSecret:'test-only-session-secret-longer-than-32-chars',region:'us-east-1',release:'test-release',writeEnabled:false};
async function withServer(fn) {
  let queries=0;
  const pool={query:async()=>{queries++;throw new Error('Database must not be accessed');}};
  const server=createServer(pool,config,{log:()=>{}});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {await fn(`http://127.0.0.1:${server.address().port}`,()=>queries);}
  finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}
test('release liveness succeeds without database access',async()=>{
  await withServer(async(url,queries)=>{
    const response=await fetch(`${url}/health/live`);
    assert.equal(response.status,200);
    assert.deepEqual(await response.json(),{status:'alive',region:'us-east-1',release:'test-release'});
    assert.equal(queries(),0);
  });
});
test('guest session is signed, HttpOnly and Secure; unauthorized orders rejected',async()=>{
  await withServer(async(url,queries)=>{
    const session=await fetch(`${url}/api/session`);
    const cookie=session.headers.get('set-cookie');
    assert.match(cookie,/HttpOnly; SameSite=Lax/);assert.match(cookie,/; Secure$/);
    assert.match((await session.json()).csrfToken,/^[a-f0-9]{64}$/);
    for(const headers of [{},{cookie:'ko_session=invalid'}]){
      const response=await fetch(`${url}/api/orders`,{headers});
      assert.equal(response.status,401);
    }
    assert.equal(queries(),0);
  });
});
test('CSRF rejection and configured standby checkout never reach database',async()=>{
  await withServer(async(url,queries)=>{
    const session=await fetch(`${url}/api/session`);
    const cookie=session.headers.get('set-cookie').split(';')[0];
    const {csrfToken}=await session.json();
    const missing=await fetch(`${url}/api/orders`,{method:'POST',headers:{cookie}});
    assert.equal(missing.status,403);
    const standby=await fetch(`${url}/api/orders`,{method:'POST',headers:{cookie,'x-csrf-token':csrfToken}});
    assert.equal(standby.status,503);assert.equal((await standby.json()).error,'standby_read_only');
    assert.equal(queries(),0);
  });
});
test('item validation rejects duplicates, injected identifiers and invalid quantities',()=>{
  for(const items of [[],[{productId:'hoodie',quantity:0}],[{productId:'hoodie',quantity:11}],[{productId:'hoodie',quantity:1.1}],[{productId:"';DROP TABLE orders;",quantity:1}],[{productId:'hoodie',quantity:1},{productId:'hoodie',quantity:2}]]){
    assert.throws(()=>validateItems({items}),{code:'invalid_items'});
  }
});
test('idempotency hash ignores item ordering and untrusted client pricing',()=>{
  const a=validateItems({items:[{productId:'tote',quantity:2,priceCents:1},{productId:'hoodie',quantity:1}]});
  const b=validateItems({items:[{productId:'hoodie',quantity:1},{productId:'tote',quantity:2}]});
  assert.equal(requestHash(a),requestHash(b));
});
test('checkout prices come from server catalog and job commits with order',async()=>{
  const statements=[];let released=false;
  const client={release(){released=true;},async query(sql,params){
    statements.push({sql,params});
    if(sql.startsWith('SELECT * FROM products'))return {rows:[{id:'hoodie',name:'Hoodie',price_cents:6900}]};
    if(sql.startsWith('INSERT INTO orders'))return {rows:[{id:params[0],status:'PENDING',total_cents:params[4],region:params[5]}]};
    return {rows:[]};
  }};
  const result=await createOrder({connect:async()=>client},'c1','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',{items:[{productId:'hoodie',quantity:2,priceCents:1}]},'us-east-1');
  assert.equal(result.order.totalCents,13800);
  assert.ok(statements.findIndex(s=>s.sql.startsWith('INSERT INTO jobs'))<statements.findIndex(s=>s.sql==='COMMIT'));
  assert.equal(released,true);
});
test('checkout rollback releases connection on unknown products',async()=>{
  const statements=[];let released=false;
  const client={release(){released=true;},async query(sql){statements.push(sql);return {rows:[]};}};
  await assert.rejects(()=>createOrder({connect:async()=>client},'c1','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',{items:[{productId:'unknown',quantity:1}]},'us-east-1'),{code:'unknown_product'});
  assert.equal(statements.at(-1),'ROLLBACK');assert.equal(released,true);
});
test('worker holds a row lock and commits both fulfillment and job completion',async()=>{
  const statements=[];
  const client={release(){},async query(sql){statements.push(sql);return {rows:sql.startsWith('SELECT order_id')?[{order_id:'order-id'}]:[]};}};
  assert.equal(await processNextJob({connect:async()=>client}),true);
  assert.match(statements[1],/FOR UPDATE SKIP LOCKED/);
  assert.ok(statements.some(s=>s.startsWith('UPDATE orders')));
  assert.ok(statements.some(s=>s.startsWith('UPDATE jobs')));
  assert.equal(statements.at(-1),'COMMIT');
});
test('production rejects local configuration without a runtime secret ARN',async()=>{
  await assert.rejects(()=>loadConfig({NODE_ENV:'production',SESSION_SECRET:config.sessionSecret,DATABASE_URL:'postgres://unused'}),/Production requires APP_SECRET_ARN/);
});
