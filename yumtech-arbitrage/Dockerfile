FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml /app/
COPY app /app/app
RUN pip install --no-cache-dir .

COPY dashboard /app/dashboard
RUN chmod 0555 /app/app/entrypoint.sh && useradd --system --uid 1000 --create-home yumtech && \
    mkdir -p /data && chown -R yumtech:yumtech /data

USER yumtech
EXPOSE 8098
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8098/api/health', timeout=3)"
ENTRYPOINT ["/app/app/entrypoint.sh"]
