# syntax=docker/dockerfile:1
# Tempest API for Render (render.yaml). DEMO_MODE by default: every route is served from the
# committed fixtures (data/demo) and reference files (data/reference); no data/raw or data/processed.
# Build from api/:  docker build -t tempest-api .   (see deploy.md)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime dependencies only (tests and lint are in requirements-dev.txt).
COPY requirements.txt .
RUN pip install -r requirements.txt

# The OASIS CAP 1.2 XSD for dispatch, downloaded at build time and checked against a pinned
# SHA-256 (the same value as app/dispatch/cap.py). A failed download or mismatch fails the build.
ARG CAP_XSD_URL=https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.xsd
ARG CAP_XSD_SHA256=b7798ef25868b068c97b268bda02d067c7d4ba9373adc5638bf37105804ee723
RUN mkdir -p /app/data/xsd && python -c "\
import hashlib, sys, urllib.request; \
data = urllib.request.urlopen('${CAP_XSD_URL}', timeout=60).read(); \
digest = hashlib.sha256(data).hexdigest(); \
sys.exit(f'CAP XSD SHA-256 {digest} != ${CAP_XSD_SHA256}') if digest != '${CAP_XSD_SHA256}' else None; \
open('/app/data/xsd/CAP-v1.2.xsd', 'wb').write(data); \
print('CAP XSD verified', digest)"

# Code and the committed data the demo needs. .dockerignore keeps out .venv, data/raw,
# data/cache, data/processed, data/state, .env files and secrets/.
COPY app ./app
COPY data/demo ./data/demo
COPY data/reference ./data/reference

RUN useradd --create-home --uid 10001 tempest
USER tempest

# DEMO_MODE on; SQLite state in /tmp (lost on every restart and spin-down).
# Keys (Gemini, Groq, Telegram, Gmail, dispatch PIN) are Render environment variables.
# Render sets PORT at runtime; 8080 is only the default for a local `docker run`.
ENV DEMO_MODE=true \
    STATE_DB_PATH=/tmp/tempest.db \
    CAP_XSD_PATH=/app/data/xsd/CAP-v1.2.xsd \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
