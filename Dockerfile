# One image: FastAPI backend + the built frontend, served from the same origin on port 8000.
#   docker build -t nim-arena .
#   docker run --rm -p 8000:8000 --env-file backend/.env nim-arena
# Match state lives in memory: run exactly ONE container (replica) per deployment.

# --- 1. build the frontend (Vite -> static files) ---
FROM node:22-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. backend runtime ---
FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Dependencies first (cached until pyproject/uv.lock change).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/llm_agents.toml ./
COPY --from=frontend /src/dist ./static
ENV FRONTEND_DIST=/app/static

RUN useradd --create-home nim
USER nim
EXPOSE 8000
# --proxy-headers: behind Azure's ingress (TLS ends there).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
