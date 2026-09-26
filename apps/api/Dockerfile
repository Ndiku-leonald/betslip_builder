FROM python:3.11-slim AS builder
WORKDIR /build
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app PORT=8000 WEB_CONCURRENCY=2
RUN useradd --create-home --uid 10001 slipiq
WORKDIR /app
COPY --from=builder /install /usr/local
COPY apps/api /app
RUN chown -R slipiq:slipiq /app
USER slipiq
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/livez', timeout=3)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers $WEB_CONCURRENCY"]
