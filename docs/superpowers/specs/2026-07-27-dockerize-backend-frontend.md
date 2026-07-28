# Dockerización: Backend + Frontend con hot-reload

## Objetivo

Crear contenedores Docker para backend y frontend que compartan red con PostgreSQL,
exponiendo **solo el frontend** en el puerto 5174 del host. Modo desarrollo con hot-reload.

## Arquitectura

```
Host:5174 ──► Frontend (Vite :5173) ──HTTP──► Backend (FastAPI :8000) ──SQL──► PostgreSQL (:5432)
                  │
            lakehouse-net (internal)
```

- **Frontend**: `node:22-alpine`, `pnpm dev`, hot-reload vía volume mount
- **Backend**: `python:3.13-slim`, `uv`, `fastapi dev --reload`, hot-reload vía volume mount
- **PostgreSQL**: `pgvector/pgvector:pg17` (existente, se une a la red)

## Servicios

### backend (Dockerfile + compose)

| Atributo | Valor |
|----------|-------|
| Base | `python:3.13-slim` |
| Gestor | `uv` |
| Comando | `fastapi dev --host 0.0.0.0 --port 8000 --reload src/lakehouse/main.py` |
| Puerto expuesto | **Ninguno al host** |
| Volumen | `./backend:/app` |
| Variables | `POSTGRES_HOST=postgres` (desde compose) |

### frontend (Dockerfile + compose)

| Atributo | Valor |
|----------|-------|
| Base | `node:22-alpine` |
| Gestor | `pnpm` |
| Comando | `pnpm dev` |
| Puerto host | `5174:5173` |
| Volumen | `./frontend:/app` |
| Variables | `VITE_API_BASE=/api` (inyectado via Vite proxy) |

## Comunicación Frontend → Backend

Vite proxy en `vite.config.ts`:

```ts
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
```

El frontend (`client.ts`) cambia `API_BASE` de `http://localhost:8000` a `/api`.
Las peticiones `/api/health` se traducen a `http://backend:8000/health` internamente.

El backend no necesita cambios en sus rutas.

## Red

Nueva red bridge `lakehouse-net` en docker-compose.
PostgreSQL se une a `lakehouse-net` además de su comportamiento actual.

## Variables de entorno

Se actualiza `POSTGRES_HOST=postgres` en el compose para el backend en Docker.
El `.env` local con `POSTGRES_HOST=localhost` sigue funcionando para desarrollo nativo.

## Archivos creados/modificados

| Archivo | Acción |
|---------|--------|
| `backend/Dockerfile` | Crear |
| `frontend/Dockerfile` | Crear |
| `frontend/Dockerfile.dev` | No necesario (usamos mismo Dockerfile) |
| `docker-compose.yml` | Modificar: agregar backend + frontend + red |
| `frontend/vite.config.ts` | Modificar: agregar proxy |
| `frontend/src/api/client.ts` | Modificar: cambiar API_BASE |
| `.env` | Sin cambios (se sobreescribe en compose) |

## No incluido

- CORS (innecesario con Vite proxy)
- Build multi-etapa (no relevante para dev)
- Autenticación en los servicios internos
