# =============================================================================
# Stage 1: Builder - compile dependencies
# =============================================================================
FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files for better layer caching
COPY requirements.lock .

# Install dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock

# =============================================================================
# Stage 2: Runtime - minimal production image
# =============================================================================
FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS runtime

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PORT=8080
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=appuser:appgroup src/ src/

# hs_reference.py resolves data/hs_reference.yaml relative to the repo root
# (parents[2] of the module file), so it must sit next to src/ and not inside it.
# It is read at import time with no fallback, so omitting it makes the container
# fail to boot rather than degrade.
#
# Named explicitly rather than copying data/: the other three files in that
# directory are test and benchmark fixtures, one of which is 1.4 MB, and none is
# read at runtime.
COPY --chown=appuser:appgroup data/hs_reference.yaml data/hs_reference.yaml

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check for Cloud Run
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run with gunicorn for production
# - workers: 1 (Cloud Run scales horizontally, not vertically)
# - threads: 8 (handle concurrent requests within the instance)
# - timeout: 300 (5 minutes for long document processing, not 0/infinite)
# - graceful-timeout: 30 (allow in-flight requests to complete on shutdown)
#
# The three limit-request flags bound what an attacker can make gunicorn parse
# before the application sees the request at all. Body size is capped separately
# by MAX_CONTENT_LENGTH in app.py, which Werkzeug enforces from Content-Length;
# these cover the request line and headers, which that ceiling does not.
# - limit-request-line: 8190 is gunicorn's default; stated rather than implied
#   because a URL is the one part of a request we never need to be long.
# - limit-request-fields / field_size: a flood of headers, or one enormous one,
#   is parsed before routing and so before any rate limit can refuse it.
CMD exec gunicorn \
    --bind :$PORT \
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
    vf_logistics.app:app
