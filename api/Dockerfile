# Build context is the repository root (see docker-compose.yml).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

COPY --from=ghcr.io/astral-sh/uv:0.12.12 /uv /bin/uv

WORKDIR /app
COPY api/pyproject.toml /app/pyproject.toml
COPY api/src /app/src
RUN uv sync --no-dev

RUN useradd --create-home --uid 10001 riffle
USER riffle

EXPOSE 8000
CMD ["uvicorn", "riffle.main:app", "--host", "0.0.0.0", "--port", "8000"]
