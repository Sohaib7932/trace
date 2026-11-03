# Portable application artifact. Deployment, secrets and HTTPS edge are separate release steps.
FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.12.1 \
    && groupadd --gid 10001 trace \
    && useradd --uid 10001 --gid trace --no-create-home --shell /usr/sbin/nologin trace
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/alembic-postgresql.ini ./
COPY backend/scripts/run_production.py backend/scripts/migrate_production.py backend/scripts/reconcile_ai_controls.py backend/scripts/platform_status.py ./scripts/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).close()"]
CMD ["/app/.venv/bin/python", "-m", "scripts.run_production"]
