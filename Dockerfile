FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen || uv sync --no-dev
COPY . .
RUN uv sync --no-dev

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN useradd --create-home --shell /usr/sbin/nologin appuser
COPY --from=builder /app /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"
CMD ["uvicorn", "neuron_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
