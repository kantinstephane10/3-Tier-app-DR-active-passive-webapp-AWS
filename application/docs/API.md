# Application API

All browser API calls use the same origin through Nginx. Responses are JSON and are not cacheable. Amounts are integer USD cents. `X-Request-Id` ties an error to the structured HTTP log without exposing credentials or request bodies.

| Method/path | Behavior |
|---|---|
| GET /api/products | Six database-backed products and trusted prices |
| GET /api/status | Public region/release/write mode; no DB hostname or credentials |
| GET /api/session | Sets signed HttpOnly guest cookie and returns CSRF token |
| GET /api/orders | Latest 50 orders belonging to this guest session |
| GET /api/orders/:id | This guest's order and item details; another session gets 404 |
| POST /api/orders | Creates an order and pending job in one transaction |
| GET /health/live | Process is alive; does not contact DB |
| GET /health/deploy | DB connection and schema v1 are reachable, including standby |
| GET /health/ready | Schema reachable and this deployment/database allow writes |

POST requires the guest cookie, `X-CSRF-Token`, a UUID `Idempotency-Key`, and Content-Type application/json. Example payload:

```json
{"items":[{"productId":"cloud-notebook","quantity":2},{"productId":"tote","quantity":1}]}
```

The API computes a $70.00 total from catalog prices. Client price fields are ignored. Quantity must be 1–10 per product; duplicate product IDs, unknown products, invalid UUIDs and invalid JSON are rejected. Request bodies are limited to 16 KiB. This is not inventory reservation or payment processing.

Example success:

```json
{
  "order": {
    "id": "example-uuid",
    "status": "PENDING",
    "totalCents": 7000,
    "region": "us-east-1",
    "createdAt": "timestamp",
    "updatedAt": "timestamp"
  },
  "replay": false
}
```

First creation returns 201. The same guest/key and identical item quantities return the original order with HTTP 200 and replay=true, including when retried after a lost response. Reusing the key for a different payload returns 409. Completed orders become FULFILLED when a worker processes their job. Prices and names are snapshotted on the order's items.

Error codes include 400 invalid_items/unknown_product/invalid_idempotency_key/invalid_json, 401 session_required, 403 csrf_required, 404 order_not_found, 409 idempotency_key_reused, 413 body_too_large, 415 json_required and 503 standby_read_only/service_unavailable. The server does not return raw database errors.

The storefront persists a bag and its current checkout attempt key locally for retries. It is still a demo: avoid changing a bag while a checkout outcome is ambiguous; retry that same attempt and inspect order history first. A new key represents a new order. No PII, password, address or card data is collected.
