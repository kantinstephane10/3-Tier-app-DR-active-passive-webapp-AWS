import { createHash, randomUUID } from 'node:crypto';
export class HttpError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
export const isUuid = value => typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value);

export function validateItems(body) {
  if (!body || !Array.isArray(body.items) || body.items.length < 1 || body.items.length > 20) throw new HttpError(400, 'invalid_items');
  const seen = new Set();
  return body.items.map(item => {
    if (!item || typeof item.productId !== 'string' || !/^[a-z0-9-]{1,64}$/.test(item.productId) ||
        !Number.isInteger(item.quantity) || item.quantity < 1 || item.quantity > 10 || seen.has(item.productId)) throw new HttpError(400, 'invalid_items');
    seen.add(item.productId);
    return { productId: item.productId, quantity: item.quantity };
  }).sort((a,b) => a.productId.localeCompare(b.productId));
}

export function requestHash(items) { return createHash('sha256').update(JSON.stringify(items)).digest('hex'); }

export async function createOrder(pool, customerId, key, body, region) {
  if (!isUuid(key)) throw new HttpError(400, 'invalid_idempotency_key');
  const items = validateItems(body);
  const hash = requestHash(items);
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const productResult = await client.query('SELECT * FROM products WHERE id = ANY($1::text[]) AND active = true', [items.map(i => i.productId)]);
    const products = new Map(productResult.rows.map(p => [p.id,p]));
    if (products.size !== items.length) throw new HttpError(400, 'unknown_product');
    const total = items.reduce((sum, i) => sum + products.get(i.productId).price_cents * i.quantity, 0);
    const result = await client.query(`INSERT INTO orders(id,customer_id,idempotency_key,request_hash,total_cents,region)
      VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(customer_id,idempotency_key) DO NOTHING RETURNING *`, [randomUUID(),customerId,key,hash,total,region]);
    let order = result.rows[0];
    const replay = !order;
    if (replay) {
      order = (await client.query('SELECT * FROM orders WHERE customer_id=$1 AND idempotency_key=$2', [customerId,key])).rows[0];
      if (order.request_hash !== hash) throw new HttpError(409, 'idempotency_key_reused');
    } else {
      for (const item of items) {
        const p = products.get(item.productId);
        await client.query('INSERT INTO order_items(order_id,product_id,name,quantity,price_cents) VALUES($1,$2,$3,$4,$5)', [order.id,p.id,p.name,item.quantity,p.price_cents]);
      }
      // The job and order commit together, so a crash cannot lose pending work.
      await client.query('INSERT INTO jobs(order_id) VALUES($1)', [order.id]);
    }
    await client.query('COMMIT');
    return { order: publicOrder(order), replay };
  } catch (error) { await client.query('ROLLBACK'); throw error; }
  finally { client.release(); }
}

export function publicOrder(row) {
  return { id: row.id, status: row.status, totalCents: row.total_cents,
    region: row.region, createdAt: row.created_at, updatedAt: row.updated_at };
}

export async function listOrders(pool, customerId) {
  return (await pool.query('SELECT * FROM orders WHERE customer_id=$1 ORDER BY created_at DESC LIMIT 50', [customerId])).rows.map(publicOrder);
}

export async function getOrder(pool, customerId, id) {
  if (!isUuid(id)) throw new HttpError(404, 'order_not_found');
  const result = await pool.query('SELECT * FROM orders WHERE id=$1 AND customer_id=$2', [id,customerId]);
  if (!result.rows[0]) throw new HttpError(404, 'order_not_found');
  const items = (await pool.query('SELECT product_id AS "productId",name,quantity,price_cents AS "priceCents" FROM order_items WHERE order_id=$1 ORDER BY product_id', [id])).rows;
  return { ...publicOrder(result.rows[0]), items };
}

export async function processNextJob(pool) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await client.query('SELECT order_id FROM jobs WHERE completed_at IS NULL ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED');
    if (!result.rows[0]) { await client.query('COMMIT'); return false; }
    const id = result.rows[0].order_id;
    // Simulated fulfillment only: no real payment, shipment or external side effect.
    await client.query("UPDATE orders SET status='FULFILLED',updated_at=now() WHERE id=$1 AND status='PENDING'", [id]);
    await client.query('UPDATE jobs SET completed_at=now() WHERE order_id=$1', [id]);
    await client.query('COMMIT');
    return true;
  } catch (error) { await client.query('ROLLBACK'); throw error; }
  finally { client.release(); }
}
