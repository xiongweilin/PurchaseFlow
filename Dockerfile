FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir pip==26.2.1
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY alembic.ini /app/alembic.ini
COPY backend/migrations /app/backend/migrations

FROM base AS test
COPY requirements-dev.txt /app/requirements-dev.txt
RUN python -m pip install --no-cache-dir -r /app/requirements-dev.txt
COPY pyproject.toml /app/pyproject.toml
COPY tests /app/tests
COPY n8n/workflows /app/n8n/workflows
CMD ["pytest", "-q"]

FROM base AS production
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
