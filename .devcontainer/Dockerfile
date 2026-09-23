FROM mcr.microsoft.com/devcontainers/javascript-node:1-22-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y \
    bubblewrap \
    git \
    curl \
    ripgrep \
    jq \
    unzip \
    python3 \
    php-cli \
    composer \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex

WORKDIR /workspaces/codex_laya_dev
