# syntax=docker/dockerfile:1
# Wrangler uses image_build_context=.. so this Dockerfile is evaluated from the
# repository root. A local `docker build cloud/` cannot see Python source; use
# `docker build -f cloud/Dockerfile .` for the equivalent offline check.
FROM node:24-bookworm-slim AS codex-node
RUN npm install --global --omit=dev @openai/codex@0.152.0 && npm cache clean --force

FROM ghcr.io/astral-sh/uv:0.11.21 AS uv
FROM docker.io/cloudflare/sandbox:0.12.9

ARG CODEX_BASE_URL=""
ARG RVW_IMAGE_VERSION="dev"
ARG GH_VERSION="v2.100.0"
ARG GH_SHA256="e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be"
ARG MIN_GH_VERSION="2.18.0"
LABEL org.opencontainers.image.title="rvw-cloud" org.opencontainers.image.version="${RVW_IMAGE_VERSION}"
ENV HOME=/root PYTHONUNBUFFERED=1 RVW_CODEX_DEFAULT_BASE_URL="${CODEX_BASE_URL}" RVW_CODEX_SANDBOX=danger-full-access PATH="/opt/rvw-venv/bin:${PATH}"
RUN apt-get update && apt-get install --yes --no-install-recommends bash ca-certificates coreutils curl git gzip ripgrep tar util-linux && rm -rf /var/lib/apt/lists/*
COPY docker/install-gh.sh /usr/local/lib/rvw/install-gh.sh
RUN sh /usr/local/lib/rvw/install-gh.sh

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=codex-node /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
WORKDIR /opt/rvw
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv python install 3.12 --default && uv venv --python 3.12 /opt/rvw-venv && uv pip install --python /opt/rvw-venv/bin/python --no-cache . && rvw --version && codex --version && node --version && rvw lanes list
COPY docker/codex-config.toml /etc/rvw/codex-config.toml
WORKDIR /workspace
