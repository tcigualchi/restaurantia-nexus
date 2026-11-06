# syntax=docker/dockerfile:1.7
# Build context: repository root (see docker-compose.yml). The synthetic catalog ships inside the package.
FROM python:3.12-slim AS build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install "uv==0.11.32"
WORKDIR /app/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/ ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/apps/api/.venv/bin:${PATH}"
RUN useradd --create-home --uid 10001 nexus
COPY --from=build --chown=nexus:nexus /app/apps/api /app/apps/api
COPY --chown=nexus:nexus apps/api/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER nexus
WORKDIR /app/apps/api
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz', timeout=2).status == 200 else 1)"
ENTRYPOINT ["sh", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]
