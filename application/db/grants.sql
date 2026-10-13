-- Run once as the DB owner after migration, replacing the role name if needed.
-- Create orders_app with a generated password outside this file; store it in Secrets Manager.
GRANT CONNECT ON DATABASE orders TO orders_app;
GRANT USAGE ON SCHEMA public TO orders_app;
GRANT SELECT ON products, schema_versions TO orders_app;
GRANT SELECT, INSERT, UPDATE ON orders, order_items, jobs TO orders_app;
-- No schema ownership, DDL, role administration, superuser or DELETE privilege.
