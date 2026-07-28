# Dockerizar Backend + Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear Dockerfiles para backend (FastAPI) y frontend (Vite+Vue 3) que corran en la misma red que PostgreSQL, exponiendo solo el frontend en puerto 5174 del host, con hot-reload.

**Architecture:** Red bridge `lakehouse-net`. Frontend usa Vite proxy para comunicarse con backend por nombre de servicio (`backend:8000`). Backend se conecta a PostgreSQL por nombre de servicio (`postgres:5432`). Variables de entorno `POSTGRES_HOST` y `POSTGRES_PORT` se sobreescriben via compose.

**Tech Stack:** Docker Compose, Python 3.13 + uv, Node 22 + pnpm, FastAPI, Vite

---

### Task 1: Backend Dockerfile

**Files:**
- Create: `backend/Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY pyproject.toml uv.lock .
RUN uv sync --frozen

EXPOSE 8000

CMD ["uv", "run", "fastapi", "dev", "--host", "0.0.0.0", "--port", "8000", "--reload", "src/lakehouse/main.py"]
```

- [ ] **Step 2: Commit**

```bash
git add backend/Dockerfile
git commit -m "cp-00: agrega Dockerfile para backend con uv"
```

---

### Task 2: Frontend Dockerfile

**Files:**
- Create: `frontend/Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

```dockerfile
FROM node:22-alpine

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

EXPOSE 5173

CMD ["pnpm", "dev"]
```

- [ ] **Step 2: Commit**

```bash
git add frontend/Dockerfile
git commit -m "cp-00: agrega Dockerfile para frontend con pnpm"
```

---

### Task 3: Update docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add backend service, frontend service, network, and update postgres**

Replace the entire file with:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    container_name: mananeras-postgres
    restart: unless-stopped
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: mananeras
      POSTGRES_USER: mananeras
      POSTGRES_PASSWORD: mananeras
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mananeras -d mananeras"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - lakehouse-net

  backend:
    build: ./backend
    container_name: mananeras-backend
    restart: unless-stopped
    volumes:
      - ./backend:/app
    environment:
      APP_ENV: docker
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      OLLAMA_BASE_URL: http://ollama:11434
      LLAMACPP_BASE_URL: http://llamacpp:9200/v1
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - lakehouse-net

  frontend:
    build: ./frontend
    container_name: mananeras-frontend
    restart: unless-stopped
    ports:
      - "5174:5173"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    depends_on:
      - backend
    networks:
      - lakehouse-net

networks:
  lakehouse-net:
    driver: bridge

volumes:
  pgdata:
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "cp-00: agrega servicios backend y frontend a compose con red compartida"
```

---

### Task 4: Configure Vite proxy

**Files:**
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: Add proxy configuration**

Edit `frontend/vite.config.ts`:

```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.ts'],
  },
})
```

- [ ] **Step 2: Commit**

```bash
git add frontend/vite.config.ts
git commit -m "cp-00: configura Vite proxy para comunicacion con backend en Docker"
```

---

### Task 5: Update frontend API client

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Change API_BASE to relative /api path**

Edit `frontend/src/api/client.ts`:

```typescript
const API_BASE = '/api'
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "cp-00: cambia API_BASE a ruta relativa /api para Vite proxy"
```

---

### Task 6: Verify the setup

**Files:** None (manual verification)

- [ ] **Step 1: Build and start all services**

```bash
docker compose up -d --build
```

Expected: all three services start without errors.

- [ ] **Step 2: Verify frontend is accessible**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5174
```

Expected: `200`

- [ ] **Step 3: Verify API is reachable through the proxy**

```bash
curl -s http://localhost:5174/api/health
```

Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 4: Verify backend is NOT directly exposed**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "connection refused"
```

Expected: connection refused (port not mapped to host)

- [ ] **Step 5: View logs**

```bash
docker compose logs -f
```

Verify no error messages in any service.

```bash
git add -A && git commit -m "cp-00: verifica dockerizacion completa"
```
