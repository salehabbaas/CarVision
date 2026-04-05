#!/bin/sh
set -eu

cd /app/backend/app

if [ -n "${SSL_CERTFILE:-}" ] && [ -n "${SSL_KEYFILE:-}" ]; then
  exec uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-certfile "$SSL_CERTFILE" --ssl-keyfile "$SSL_KEYFILE"
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
