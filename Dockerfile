# ===== Build stage =====
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for wheels (none heavy — slowapi/pydantic all pure-Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


# ===== Runtime stage =====
FROM python:3.11-slim AS runtime

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/app/.local
ENV PATH=/home/app/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy app code
COPY --chown=app:app . /app

USER app

# HF Spaces uses 7860; Railway/Fly/etc inject PORT. Default to 7860 for HF compat.
ENV PORT=7860
EXPOSE 7860

# Healthcheck hits our built-in endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','7860')+'/api/health').read()" || exit 1

# Production launch: no reload, no debug
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips=*"]
