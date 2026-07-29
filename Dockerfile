# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Fail fast, no .pyc clutter, unbuffered logs for container log drivers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production \
    DATA_DIR=/data \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# Dependencies first so code edits do not invalidate the wheel layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir waitress

COPY . .

# Bundle the report fonts at build time so the container needs no network on
# first request (the runtime downloader is only a fallback).
RUN python -c "from utils.fonts import download_lora_fonts; download_lora_fonts()" || true

# Run unprivileged, and give the app a writable volume for mutable state.
RUN useradd --create-home --uid 10001 mercury && \
    mkdir -p /data/uploads /data/output_data /data/sessions && \
    chown -R mercury:mercury /app /data
USER mercury

VOLUME ["/data"]
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status==200 else 1)"

# One process, many threads - see the note in wsgi.py.
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=8", "--channel-timeout=300", "wsgi:application"]
