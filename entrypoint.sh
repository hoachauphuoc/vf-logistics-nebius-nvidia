#!/bin/bash
# Two processes, one container (see Dockerfile):
#
#   gunicorn / Flask   127.0.0.1:9090   internal only; reached through Next.js
#   Next.js console    0.0.0.0:$PORT    the one port Cloud Run routes to
#
# Order matters. Next.js starts only once Flask answers /health, so an instance
# never takes traffic it would answer with 502s. If Flask never becomes healthy
# the script exits instead of starting Next.js anyway: Cloud Run then replaces
# the instance, where a half-started one would pass the port probe and fail
# every request behind it.
#
# `set -e` is deliberately absent. `wait -n` returns the exit status of the
# child that died, and under `set -e` that would end the script before the
# other child is stopped.
set -u

FLASK_PORT=9090
READY_TIMEOUT="${FLASK_READY_TIMEOUT:-45}"
export FLASK_API_BASE="http://127.0.0.1:${FLASK_PORT}"
export PORT="${PORT:-8080}"

GUNICORN_PID=""
NODE_PID=""

stop_children() {
  for pid in "$NODE_PID" "$GUNICORN_PID"; do
    if [ -n "$pid" ]; then kill -TERM "$pid" 2>/dev/null || true; fi
  done
  # gunicorn finishes in-flight requests within --graceful-timeout.
  wait 2>/dev/null || true
}

# Cloud Run sends SIGTERM to PID 1 -- this script -- and SIGKILLs ten seconds
# later. Without a trap bash would exit on the signal and leave both children to
# be killed mid-request.
on_signal() {
  echo "[entrypoint] $1 received; stopping both processes"
  stop_children
  exit 0
}
trap 'on_signal SIGTERM' TERM
trap 'on_signal SIGINT' INT

echo "[entrypoint] starting gunicorn on 127.0.0.1:${FLASK_PORT}"
/opt/venv/bin/gunicorn \
  --bind "127.0.0.1:${FLASK_PORT}" \
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

echo "[entrypoint] waiting up to ${READY_TIMEOUT}s for Flask /health"
ready=0
for _ in $(seq 1 "$READY_TIMEOUT"); do
  if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
    # A boot guard in app.py (auth.assert_write_access_is_guarded and friends)
    # refuses to start on an unsafe configuration. Say so and stop, rather than
    # waiting out the timeout for a process that is already gone.
    echo "[entrypoint] gunicorn exited during startup; see the log above"
    exit 1
  fi
  if /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${FLASK_PORT}/health', timeout=2)" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "[entrypoint] Flask was not healthy after ${READY_TIMEOUT}s; exiting so the instance is replaced"
  stop_children
  exit 1
fi

echo "[entrypoint] Flask is ready; starting Next.js on :${PORT}"
cd /app/console
# HOSTNAME is set per-process on purpose. Docker exports HOSTNAME as the
# container id, and Next's standalone server binds whatever it holds -- which is
# not an address Cloud Run can reach.
HOSTNAME=0.0.0.0 node server.js &
NODE_PID=$!

# Either process dying takes the instance down, so Cloud Run starts a fresh one
# rather than serving half an application.
wait -n "$GUNICORN_PID" "$NODE_PID"
status=$?
echo "[entrypoint] a process exited with status ${status}; stopping the other"
stop_children
exit 1
