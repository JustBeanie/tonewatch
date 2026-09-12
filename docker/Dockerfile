# syntax=docker/dockerfile:1.7
FROM node:24-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03 AS web
WORKDIR /src/web
COPY web/package.json web/pnpm-lock.yaml ./
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS builder
COPY --from=ghcr.io/astral-sh/uv@sha256:f64ad69940b634e75d2e4d799eb5238066c5eeda49f76e782d4873c3d014ea33 /uv /uvx /usr/local/bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md backend/LICENSE ./
COPY backend/src ./src
COPY --from=web /src/web/dist ./src/tonewatch/web_dist
# Trim the venv here, before the runtime stage copies it: deleting files in a later stage only
# hides them behind a whiteout and does not shrink the image. Third-party test suites, bytecode
# caches and numpy's C headers are never used at runtime (budget: 350 MB, see docker/README.md).
RUN uv sync --frozen --no-dev --no-editable \
    && find /opt/venv/lib/python3.13/site-packages -depth -type d \
        \( -name tests -o -name test -o -name __pycache__ \) -exec rm -rf {} + \
    && rm -rf /opt/venv/lib/python3.13/site-packages/numpy/_core/include

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS runtime
ARG VERSION=0.1.0
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/JustBeanie/tonewatch" \
      org.opencontainers.image.revision="$REVISION" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="MIT"
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y libportaudio2 rtl-sdr tini ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf \
        /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
        /usr/local/lib/python3.13/site-packages/pkg_resources \
        /usr/local/lib/python3.13/site-packages/setuptools \
        /usr/local/lib/python3.13/site-packages/setuptools-*.dist-info \
        /usr/local/lib/python3.13/site-packages/wheel \
        /usr/local/lib/python3.13/site-packages/wheel-*.dist-info \
        /usr/local/lib/python3.13/ensurepip \
    && rm -f /usr/local/bin/easy_install* /usr/local/bin/pip*
RUN groupadd --gid 10001 tonewatch \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin tonewatch \
    && usermod --append --groups audio,plugdev tonewatch \
    && mkdir /data \
    && chown tonewatch:tonewatch /data
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    TONEWATCH_DATA_DIR=/data \
    TONEWATCH_BIND_HOST=0.0.0.0 \
    TONEWATCH_BIND_PORT=8099
VOLUME ["/data"]
EXPOSE 8099
USER tonewatch
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/healthz', timeout=2)"
ENTRYPOINT ["tini", "--", "tonewatch"]
CMD ["serve"]
