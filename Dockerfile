FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN python manage.py collectstatic --noinput
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health/', timeout=3)"

# Content bootstrap runs on every boot. Both seed commands are idempotent
# (they only insert when a table is empty), so existing data is never touched.
# Without this step a freshly provisioned database has schema but zero rows,
# and the public website renders as an empty shell.
ENV AURAFOODS_SEED_ON_START=1

CMD sh -c "python manage.py migrate --noinput && \
  if [ \"$AURAFOODS_SEED_ON_START\" = \"1\" ]; then \
    python manage.py seed_erp_roles || echo 'WARNING: seed_erp_roles failed; ERP role groups may be missing'; \
    python manage.py seed || echo 'WARNING: seed failed; storefront content may be missing'; \
  fi && \
  gunicorn aurafoods_erp.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2"

