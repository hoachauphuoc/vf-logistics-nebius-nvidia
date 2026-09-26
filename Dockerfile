# =============================================================================
# Unified container: Flask backend + Next.js console on one Cloud Run service.
#
# Next.js listens on $PORT (Cloud Run sets this, default 8080) and proxies
# /api/proxy/* to Flask on an internal port (9090). The browser never reaches
# Flask directly -- the same BFF proxy pattern the split deployment used,
# except localhost instead of a second Cloud Run URL.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS py-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# ---------------------------------------------------------------------------
# Stage 2: Next.js build (standalone output)
# ---------------------------------------------------------------------------
FROM node:22-slim AS node-builder

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ .
ENV NEXT_PUBLIC_DEMO_MODE=false
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 3: Runtime -- Python 3.11 + Node 22 in one image
# ---------------------------------------------------------------------------
FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS runtime

# Install Node.js 22.x from NodeSource
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg wget bash && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PATH="/opt/venv/bin:$PATH"

COPY --from=py-builder /opt/venv /opt/venv
COPY src/ src/
COPY data/hs_reference.yaml data/hs_reference.yaml

# Next.js standalone
COPY --from=node-builder /app/.next/standalone ./console/
COPY --from=node-builder /app/.next/static ./console/.next/static/
COPY --from=node-builder /app/public ./console/public/

# Entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser && \
    chown -R appuser:appgroup /app
USER appuser

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:${PORT}/ || exit 1

CMD ["/app/entrypoint.sh"]
