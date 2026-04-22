#!/bin/sh
set -eu

CERT_DIR="/etc/nginx/certs"
CERT_FILE="${SSL_CERT_FILE:-$CERT_DIR/server.crt}"
KEY_FILE="${SSL_KEY_FILE:-$CERT_DIR/server.key}"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
  exit 0
fi

mkdir -p "$CERT_DIR"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
  exit 0
fi

echo "Generating self-signed TLS certificate for nginx frontend..."
openssl req -x509 -nodes -newkey rsa:2048 \
  -days 3650 \
  -subj "/CN=carvision.local" \
  -keyout "$KEY_FILE" \
  -out "$CERT_FILE" >/dev/null 2>&1
