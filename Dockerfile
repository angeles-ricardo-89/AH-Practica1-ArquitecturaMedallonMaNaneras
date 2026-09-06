# Build productivo single-origin (web + API bajo el mismo origen) para Cloud Run.
# Stage 1: compila el frontend Vue con Vite (VITE_API_BASE vacio => llamadas same-origin).
# Stage 2: runtime Python con la API FastAPI y los estaticos servidos por la propia app.

FROM node:22-alpine AS frontend-build
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /fe
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
RUN pnpm build

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN uv sync --frozen --no-dev
ENV FRONTEND_DIST_DIR=/app/frontend_dist
COPY --from=frontend-build /fe/dist ./frontend_dist
EXPOSE 8080
CMD ["uv", "run", "uvicorn", "lakehouse.main:app", "--host", "0.0.0.0", "--port", "8080"]
