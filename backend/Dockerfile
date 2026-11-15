# ── CPI Backend ──────────────────────────────────────────────────────────────
# Multi-stage build: install deps in a build stage, copy into slim runtime.
FROM python:3.11-slim AS deps

WORKDIR /deps

# System packages needed by psycopg (libpq) and Pillow / numpy deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app/backend

# Runtime system libs only (libpq + pg_isready from postgresql-client)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from build stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code (the entire backend/ directory)
COPY . .

# Make entrypoint executable
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
