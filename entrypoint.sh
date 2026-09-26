#!/bin/bash
set -e

FLASK_PORT=9090
export FLASK_API_BASE="http://127.0.0.1:${FLASK_PORT}"

echo "[entrypoint] Starting gunicorn on :${FLASK_PORT}"
/opt/venv/bin/gunicorn \
  --bind :"${FLASK_PORT}" \
  --workers 1 \
  --threads 8 \
  --timeout 300 \
  --graceful-timeout 30 \
  --limit-request-line 8190 \
  --limit-request-fields 100 \
  --limit-request-field_size 16380 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  vf_logistics.app:app &
GUNICORN_PID=$!

echo "[entrypoint] Waiting for Flask to be ready..."
for i in $(seq 1 30); do
  if wget -q -O /dev/null "http://127.0.0.1:${FLASK_PORT}/health" 2>/dev/null; then
    echo "[entrypoint] Flask is ready"
    break
  fi
  sleep 1
done

echo "[entrypoint] Starting Next.js on :${PORT:-8080}"
cd /app/console
export HOSTNAME="0.0.0.0"
export PORT="${PORT:-8080}"
node server.js &
NODE_PID=$!

# If either process dies, kill the other and exit so Cloud Run restarts us
wait -n "$GUNICORN_PID" "$NODE_PID" 2>/dev/null || true
echo "[entrypoint] A process exited, shutting down"
kill "$GUNICORN_PID" "$NODE_PID" 2>/dev/null || true
exit 1
