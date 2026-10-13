#!/usr/bin/env bash
set -euo pipefail
set +x
source /etc/kantin-orders/web.env
: "${INTERNAL_ALB_DNS:?Set the internal load balancer DNS name}"
[[ "$INTERNAL_ALB_DNS" =~ ^[a-zA-Z0-9.-]+$ ]] || exit 1
[[ "${INTERNAL_ALB_PORT:-8080}" == 8080 || "${INTERNAL_ALB_PORT:-8080}" == 80 || "${INTERNAL_ALB_PORT:-8080}" == 443 ]] || exit 1
if [[ "${INTERNAL_ALB_PORT:-8080}" == 443 ]]; then
  : "${INTERNAL_API_TLS_NAME:?Set the certificate hostname}"
  [[ "$INTERNAL_API_TLS_NAME" =~ ^[a-zA-Z0-9.-]+$ ]] || exit 1
  UPSTREAM_SCHEME=https
else UPSTREAM_SCHEME=http; INTERNAL_API_TLS_NAME="$INTERNAL_ALB_DNS"; fi
cat > /etc/nginx/conf.d/kantin-orders.conf <<EOF
server {
  listen 80 default_server;
  server_name _;
  server_tokens off;
  root /opt/kantin-orders/web;
  index index.html;
  client_max_body_size 16k;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy same-origin always;
  add_header Cache-Control no-store always;
  add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" always;
  resolver 169.254.169.253 valid=30s ipv6=off;
  set \$api_origin "$UPSTREAM_SCHEME://$INTERNAL_ALB_DNS:${INTERNAL_ALB_PORT:-8080}";
  location = /health { proxy_pass \$api_origin; proxy_connect_timeout 3s; proxy_read_timeout 8s; }
  location = /health/live { access_log off; return 200 'alive'; }
  location = /health/ready { proxy_pass \$api_origin; proxy_connect_timeout 3s; proxy_read_timeout 8s; }
  location = /health/deploy { proxy_pass \$api_origin; proxy_connect_timeout 3s; proxy_read_timeout 8s; }
  location /api/ {
    proxy_pass \$api_origin;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Connection "";
    proxy_ssl_server_name on;
    proxy_ssl_name $INTERNAL_API_TLS_NAME;
    proxy_ssl_verify on;
    proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
    proxy_connect_timeout 3s;
    proxy_read_timeout 10s;
    proxy_buffering off;
  }
  location / { try_files \$uri =404; }
}
EOF
# Stock Ubuntu nginx site would conflict with this default listener.
rm -f /etc/nginx/sites-enabled/default
nginx -t
