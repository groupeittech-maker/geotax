FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p qr_codes static/uploads/poi instance \
    && chmod +x deploy/docker/entrypoint.sh \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    GUNICORN_BIND=0.0.0.0:8000

EXPOSE 8000

ENTRYPOINT ["/app/deploy/docker/entrypoint.sh"]
