# Both bases are pinned by digest (the multi-arch index digest); the tag stays in the FROM line
# and in the comment so Dependabot can bump tag and digest together.
# ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim
FROM ghcr.io/astral-sh/uv:0.11.29-python3.13-trixie-slim@sha256:0b973c14a35cb0dc8fe63a2e8c9919fd797ac566de13090fcf0df4a6b3994b78 AS builder
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# README.md, LICENSE and NOTICE are named by pyproject.toml (readme, license-files), so the
# package build needs them; nothing else outside src/ is built.
COPY README.md LICENSE NOTICE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# python:3.13-slim-trixie
FROM python:3.13-slim-trixie@sha256:98ce6fb13b3803744fbca11434f00818f1e300e4e48a4f204e07b2c928b6218e
# Build arguments are recorded by provenance: labels only, never a secret.
ARG GIT_SHA=unknown
ARG VERSION=0.5.0
LABEL org.opencontainers.image.source="https://github.com/Md-Nisar/neuron" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.version="${VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000
WORKDIR /app
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser
COPY --from=builder /app/.venv /app/.venv
# The app runs from /app/.venv, which has no pip. The base image's own pip and setuptools
# (and the packages pip vendors) only add scanner findings and an install tool to a runtime
# image, so they are removed (#140: the first scan on main flagged them).
RUN python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && ! python -c "import pip" 2>/dev/null
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "from neuron_agent.config.settings import Settings; import urllib.request; urllib.request.urlopen('http://127.0.0.1:%d/health/live' % Settings().port, timeout=2).read()"
CMD ["neuron-api"]
