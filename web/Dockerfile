# Web アプリ（BFF と画面）。ビルドの文脈はリポジトリの直下（uv のワークスペースを使うため）
#   docker build -f web/Dockerfile .

# 1. 画面をビルドする（出力は web/proactive_web/static）
FROM node:22.11.0-alpine AS frontend
WORKDIR /src/web/frontend
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/frontend/ ./
RUN npm run build

# 2. BFF を動かす
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.20 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY core core
COPY functions functions
COPY deploy deploy
COPY web web
RUN uv sync --frozen --no-dev --package proactive-web
COPY --from=frontend /src/web/proactive_web/static web/proactive_web/static
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "proactive_web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
