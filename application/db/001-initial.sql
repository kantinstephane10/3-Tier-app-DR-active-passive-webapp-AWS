CREATE TABLE IF NOT EXISTS schema_versions (
  version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS products (
  id text PRIMARY KEY, name text NOT NULL, description text NOT NULL,
  category text NOT NULL, price_cents integer NOT NULL CHECK (price_cents > 0),
  active boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS orders (
  id uuid PRIMARY KEY, customer_id uuid NOT NULL, idempotency_key uuid NOT NULL,
  request_hash text NOT NULL, status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','FULFILLED','CANCELLED')),
  total_cents integer NOT NULL CHECK (total_cents > 0),
  region text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (customer_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS orders_customer_created ON orders(customer_id,created_at DESC);
CREATE TABLE IF NOT EXISTS order_items (
  order_id uuid NOT NULL REFERENCES orders(id), product_id text NOT NULL REFERENCES products(id),
  name text NOT NULL, quantity integer NOT NULL CHECK (quantity BETWEEN 1 AND 10),
  price_cents integer NOT NULL CHECK (price_cents > 0), PRIMARY KEY (order_id, product_id)
);
CREATE TABLE IF NOT EXISTS jobs (
  order_id uuid PRIMARY KEY REFERENCES orders(id),
  completed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS pending_jobs ON jobs(created_at) WHERE completed_at IS NULL;
INSERT INTO products(id,name,description,category,price_cents) VALUES
  ('cloud-notebook','Cloud Architect Notebook','Plan your next architecture, one decision at a time.','Workspace',2400),
  ('desk-mat','Infrastructure Desk Mat','A clean foundation for your daily build.','Workspace',3900),
  ('travel-mug','On-call Travel Mug','Keep your coffee warm through the recovery drill.','Everyday',2800),
  ('hoodie','CloudOps Hoodie','Comfort for long debugging sessions.','Apparel',6900),
  ('tote','Deploy Day Tote','Carry the essentials for your next release.','Everyday',2200),
  ('sticker-pack','Architecture Sticker Pack','Six designs for your laptop and lab notebook.','Workspace',1200)
ON CONFLICT (id) DO NOTHING;
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
