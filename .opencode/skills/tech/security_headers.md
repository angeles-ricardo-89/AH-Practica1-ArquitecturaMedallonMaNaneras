# Tech Skill: Security Headers, CORS, docs y limite de body (FastAPI/Starlette)

## Proposito

Definir como se implementa y mantiene en ESTE repo el middleware de headers seguros, el CORS de
origen exacto, las docs deshabilitadas en produccion y el limite de body. Todo se registra dentro
de la factory `create_app(settings)` en `backend/src/lakehouse/main.py`; no hay configuracion
global por modulo.

## Referencias

- FastAPI + Pydantic + Typer: `../tech/fastapi_pydantic_typer.md`
- Testing de Seguridad: `../tech/security_testing.md` (marcador HDRS)
- Testing + QA: `../tech/testing_qa.md`

## Patron actual (create_app)

En `main.py` la factory construye el `FastAPI`, anula las docs si `app_env == "production"` y
registra los middlewares en este orden:

```python
def create_app(settings: Settings) -> FastAPI:
    docs_kwargs: dict[str, Any] = {}
    if settings.app_env == "production":
        docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(..., lifespan=lifespan, **docs_kwargs)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, production=settings.app_env == "production")
    ...
    return app
```

En Starlette `add_middleware` inserta al inicio del stack: el ultimo registrado
(`SecurityHeadersMiddleware`) queda como el MAS EXTERNO, de modo que decora tambien las respuestas
cortas de middlewares internos (404 de docs deshabilitadas, 413 de body, 401/403) y del handler de
errores. Verificado por `test_security.py`: el `413` y el error saneado incluyen los headers.

## Configuracion (config.py)

- `cors_allowed_origins: list[str] = []` -> lista vacia = fail-closed, sin middleware CORS (no se usa `*`).
- `max_request_body_bytes: int = 65536` -> limite de body (64 KB).
- `app_env` -> decide docs, HSTS/CSP y `cookie_secure`.

## Headers (api/security_headers.py)

`SecurityHeadersMiddleware(BaseHTTPMiddleware)` aplica SIEMPRE `_ALWAYS` y en produccion anade HSTS y CSP:

```python
_ALWAYS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
```

- `nosniff`, `no-referrer`, `DENY`: siempre (no rompen el dev de Vite).
- HSTS + CSP: solo `production`; en local no se emiten para no romper HMR/inline de Vite.
- CSP: `script-src 'self'` PROHIBE `unsafe-inline` y `unsafe-eval` porque permiten ejecutar codigo
  arbitrario; `style-src 'self' 'unsafe-inline'` se permite porque Vue y ECharts dependen de
  estilos inline que no ejecutan codigo. Si un componente nuevo necesita un ajuste, documentar y
  actualizar la politica sin degradar `script-src`.

## Body limit (api/body_limit.py)

`BodySizeLimitMiddleware` rechaza con `413` cualquier `POST`/`PUT`/`PATCH` cuyo
`Content-Length` supere `max_bytes`; no aplica a `GET`/`HEAD` (que no llevan body de peticion).

## Reglas de mantenimiento

- Un header o politica nueva se agrega en estos dos archivos y se refleja en los tests de
  `backend/tests/test_security.py` (marcador HDRS) y en la CSP de este mismo archivo.
- CORS nunca con `*` ni con origen derivado de `Origin` del cliente: siempre lista estatica de config.
- Docs solo visibles fuera de produccion; si se habilita una ruta de debug nueva, protegerla con el mismo criterio.

## Verificaciones

- [ ] `uv run pytest tests/test_security.py --cov=src --cov-fail-under=90` verde.
- [ ] `make security-report` muestra HDRS en OK.
- [ ] Smoke en navegador del build Vue+ECharts en produccion con CSP activa.
