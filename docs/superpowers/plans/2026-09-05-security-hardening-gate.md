# Plan de implementación — Endurecimiento de seguridad, gate perpetuo e inspector

**Fecha:** 2026-09-05
**Spec:** `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md`
**PRD:** `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` §13
**Estado:** Plan propuesto, pendiente de aprobación explícita del usuario

> **Para workers agénticos:** implementar tarea por tarea, en orden, sin saltar dependencias. Cada tarea termina con un checkpoint verificable antes de avanzar.

**Objetivo:** materializar los controles de seguridad que el PRD/spec dejaron como promesas (headers, docs en prod, CORS, errores saneados, límites/timeouts, escáner de secretos) y añadir un gate perpetuo `GATE-SEC` con inspector determinista, skills atómicas y pruebas de seguridad trazables amenaza→control→prueba.

**Arquitectura:** middleware de Starlette/FastAPI para headers, CORS y límite de body; deshabilitación de docs por `APP_ENV`; handler de excepciones sanitizado; helper de conexión PostgreSQL con timeouts; inspector estático en `backend/scripts/security_check.py` que cruza un catálogo YAML contra marcadores en pruebas backend (pytest) y frontend (comentario `// security:`); escáner de secretos en `scripts/scan_secrets.py`.

**Tech Stack:** Python 3.13 (uv), FastAPI/Starlette, Pydantic v2, psycopg, pytest (marcador `security`), vitest, YAML (PyYAML), Vue 3 (frontend, solo marcador en test existente).

---

## Línea de corte

| Nivel | Contenido | Condición |
|---|---|---|
| **P0 (no negociable)** | S1–S10 completos y probados | Entrega. Nunca se recorta el gate, los controles H1–H6, las skills ni las pruebas de seguridad |
| **P1** | Endurecimiento adicional (segunda instancia, WAF, IDS) | Fuera de alcance del MVP; no se hace |

---

## Checkpoints obligatorios (al cierre de cada tarea aplicable)

1. Backend: `make test-backend` (cobertura ≥90% global, marcador `security` incluido).
2. `make lint` y `make typecheck-backend` sin errores.
3. Frontend: `pnpm typecheck` y `pnpm test:unit`.
4. `make security` verde (gate bloqueante).
5. `make security-report` emite matriz sin huecos.
6. `scripts/scan_secrets.py` sin hallazgos.
7. Pruebas con PostgreSQL/pgvector vivo (`docker compose up -d postgres`) para integración.

---

## Restricciones de implementación (vigentes en todo el plan)

1. No debilitar CSP a `unsafe-eval` ni `unsafe-inline` en `script-src` (estilos inline solo en `style-src`).
2. No habilitar `*` en CORS: lista explícita, cerrado por defecto.
3. No devolver `str(exc)` ni tipo de excepción al cliente en ningún handler.
4. No loguear contraseñas, JWTs, API keys ni contenido completo de mensajes.
5. No romper el dev de Vite: headers estrictos (CSP/HSTS) solo en `production`.
6. No inventar pruebas de amenazas que no aplican al diseño (sin SSRF/web, sin SQL injection por tools — no hay SQL libre).
7. No modificar skills sin actualizar `AGENTS.md`.

---

## Edge Case Coverage

- **CSP en producción rompe ECharts/Vue:** la política se verifica con smoke en navegador; ajuste puntual documentado sin habilitar `unsafe-eval`.
- **Headers en local rompen HMR:** HSTS/CSP se omiten en `APP_ENV != production`; solo `nosniff` + `Referrer-Policy` + `X-Frame-Options` se aplican siempre.
- **CORS sin origen configurado:** `cors_allowed_origins` vacío → ningún `Access-Control-Allow-Origin` (fail-closed); request con `Origin` no listado no recibe encabezado CORS.
- **Request con `Content-Length` ausente (chunked):** el middleware de body size no bloquea; la validación queda en Pydantic (esquema de pregunta ≤2000 chars). No se introduce lectura de body en middleware (evitar consumo del stream).
- **`statement_timeout` rompe consultas largas del pipeline:** el timeout se aplica solo a conexiones de API (helper `pg_connect`); el pipeline usa su propio camino (`ducklake_catalog`) y no pasa por el helper.
- **Escáner de secretos con falsos positivos:** exclusiones explícitas (`docs/`, `*.lock`, placeholders de `.env.template` con valor `changeme`/vacío).
- **Inspector sin Postgres ni red:** verificación puramente estática (existencia de archivo + marcador + checks); no levanta el stack.
- **E2E sin segundo usuario definido:** la aserción de aislamiento hace `pytest.skip` si faltan `E2E_USERNAME2`/`E2E_PASSWORD2`.

---

## Tareas

### S1 — Registro del marcador `security` y catálogo de controles

- **Archivos:**
  - Modificar: `backend/pyproject.toml` (sección `[tool.pytest.ini_options]` → `markers`).
  - Crear: `governance/security-controls.yaml`.
- **Prueba primero:** no aplica TDD aquí; es configuración. El criterio de verificación es que `pytest` no emita warning por marcador desconocido al recolectar tests que lo usen (validado en S10).
- **Cambio mínimo:**
  - `pyproject.toml`, añadir al array `markers`:
    ```toml
    markers = [
        "e2e: prueba end-to-end sin mocks contra un backend en vivo (requiere stack real)",
        "security: prueba que ejercita un control de seguridad OWASP (ID del control como argumento)",
    ]
    ```
  - `governance/security-controls.yaml` con el esquema y los 14 controles de la spec §5.3:
    ```yaml
    version: 1
    controls:
      - id: "A07"
        title: "Authentication Failures"
        family: "security-auth-jwt"
        control: "mensaje genérico, límite de login, expiración JWT"
        backend_tests: ["tests/test_api/test_auth.py"]
        frontend_tests: []
        checks: []
      - id: "A04"
        title: "Cryptographic Failures"
        family: "security-auth-jwt"
        control: "secreto fuerte en prod, Argon2, flags de cookie"
        backend_tests: ["tests/test_security.py", "tests/test_api/test_auth.py"]
        frontend_tests: []
        checks: []
      - id: "CSRF"
        title: "CSRF Protection"
        family: "security-csrf"
        control: "token CSRF obligatorio en operaciones con estado"
        backend_tests: ["tests/test_api/test_auth.py"]
        frontend_tests: []
        checks: []
      - id: "A01"
        title: "Broken Access Control"
        family: "security-access-control"
        control: "propiedad por JWT, 404 en conversación ajena, aislamiento"
        backend_tests: ["tests/test_api/test_conversations.py"]
        frontend_tests: []
        checks: []
      - id: "A05"
        title: "Injection"
        family: "security-injection"
        control: "SQL parametrizado, tools sin SQL"
        backend_tests: ["tests/test_agent/test_tools.py"]
        frontend_tests: []
        checks: []
      - id: "LLM01"
        title: "Prompt Injection"
        family: "security-injection"
        control: "corpus como dato, allowlist de 3 tools"
        backend_tests: ["tests/test_agent/test_planner.py", "tests/test_agent/test_executor.py"]
        frontend_tests: []
        checks: []
      - id: "LLM03"
        title: "Excessive Agency"
        family: "security-injection"
        control: "máximo 2 ejecuciones, parámetros estrictos"
        backend_tests: ["tests/test_agent/test_executor.py"]
        frontend_tests: []
        checks: []
      - id: "LLM10"
        title: "Improper Output Handling"
        family: "security-output-handling"
        control: "sanitización Markdown/HTML en frontend"
        backend_tests: []
        frontend_tests: ["tests/utils/markdown.test.ts"]
        checks: []
      - id: "LLM08"
        title: "Hidden Context Exposure"
        family: "security-output-handling"
        control: "errores saneados sin detalle interno"
        backend_tests: ["tests/test_security.py"]
        frontend_tests: []
        checks: []
      - id: "HDRS"
        title: "Security Headers & Misconfiguration"
        family: "security-headers-config"
        control: "headers seguros, docs deshabilitadas en prod, CORS exacto"
        backend_tests: ["tests/test_security.py"]
        frontend_tests: []
        checks: []
      - id: "A10"
        title: "Exceptional Conditions & Consumption"
        family: "security-headers-config"
        control: "límite de body, timeouts BD/modelo"
        backend_tests: ["tests/test_security.py"]
        frontend_tests: []
        checks: []
      - id: "A09"
        title: "Logging Failures"
        family: "security-headers-config"
        control: "sin secretos ni contenido en logs"
        backend_tests: ["tests/test_api/test_auth.py"]
        frontend_tests: []
        checks: []
      - id: "A03"
        title: "Supply Chain"
        family: "security-headers-config"
        control: "lockfiles presentes, dependencias fijadas"
        backend_tests: []
        frontend_tests: []
        checks: ["lockfiles"]
      - id: "SEC"
        title: "Secret Scanning"
        family: "security-headers-config"
        control: "sin secretos rastreados por git"
        backend_tests: []
        frontend_tests: []
        checks: ["secrets-scan"]
    ```
- **Comando de validación:** `cd backend && uv run pytest --collect-only -q -m 'not e2e'` no arroja warnings de marcador; YAML parsea (`uv run python -c "import yaml;yaml.safe_load(open('../governance/security-controls.yaml'))"`).
- **Criterio de terminado:** catálogo cargable y marcador registrado.
- **Dependencia:** ninguna (base).
- **Rollback:** revertir `pyproject.toml` y borrar el YAML.

### S2 — H1: middleware de headers seguros

- **Archivos:**
  - Crear: `backend/src/lakehouse/api/security_headers.py`.
  - Modificar: `backend/src/lakehouse/main.py`, `backend/src/lakehouse/config.py`, `backend/tests/test_security.py`.
- **Prueba primero** (añadir a `test_security.py`, con `pytestmark = pytest.mark.security("HDRS")` al inicio del archivo):
  ```python
  from fastapi.testclient import TestClient
  from lakehouse.config import Settings
  from lakehouse.main import create_app

  def test_security_headers_always_present():
      client = TestClient(create_app(Settings()))
      r = client.get("/health")
      assert r.headers.get("x-content-type-options") == "nosniff"
      assert r.headers.get("referrer-policy") == "no-referrer"
      assert r.headers.get("x-frame-options") == "DENY"

  def test_hsts_and_csp_only_in_production():
      client = TestClient(create_app(Settings(app_env="production")))
      r = client.get("/health")
      assert "strict-transport-security" in r.headers
      assert "content-security-policy" in r.headers

  def test_no_hsts_csp_in_local():
      client = TestClient(create_app(Settings()))
      r = client.get("/health")
      assert "strict-transport-security" not in r.headers
      assert "content-security-policy" not in r.headers
  ```
  Verificar que falla antes del cambio (headers ausentes).
- **Cambio mínimo:**
  - `main.py`: introducir factory:
    ```python
    def create_app(settings: Settings) -> FastAPI:
        docs_kwargs = {}
        if settings.app_env == "production":
            docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}
        app = FastAPI(
            title="Lakehouse Mañaneras API",
            description="API para el pipeline de datos de las conferencias mañaneras",
            version="0.1.0",
            lifespan=lifespan,
            **docs_kwargs,
        )
        app.add_middleware(SecurityHeadersMiddleware, production=settings.app_env == "production")
        # ... CORS (S3) y BodySizeLimit (S5) se añaden aquí ...
        # ... routers, exception handler ...
        return app

    app = create_app(Settings())
    ```
  - `security_headers.py`:
    ```python
    from __future__ import annotations

    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response

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

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, *, production: bool) -> None:
            super().__init__(app)
            self._production = production

        async def dispatch(
            self, request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            response = await call_next(request)
            response.headers.update(_ALWAYS)
            if self._production:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                response.headers["Content-Security-Policy"] = _CSP
            return response
    ```
  - Nota: mantener `app = create_app(Settings())` a nivel módulo para no romper `conftest.py` ni los imports existentes (`from lakehouse.main import app`).
  - Nota (refactor explícito): todo lo que hoy está a nivel módulo en `main.py` — los `app.include_router(...)` (líneas 32–45 actuales) y el `@app.exception_handler(RuntimeError)` — se mueve **dentro** de `create_app`, sin cambiar su contenido. En S4 el handler cambia de cuerpo; los routers quedan idénticos. El `lifespan` se mantiene igual.
- **Comando de validación:** `make test-backend` (test de headers verde) y `make lint`.
- **Criterio de terminado:** headers presentes; HSTS/CSP solo en prod.
- **Dependencia:** S1.
- **Rollback:** quitar `add_middleware` y el archivo.

### S3 — H2 (docs en prod) + H3 (CORS de origen exacto)

- **Archivos:** modificar `backend/src/lakehouse/main.py`, `backend/src/lakehouse/config.py`, `backend/tests/test_security.py`.
- **Prueba primero:**
  ```python
  def test_docs_disabled_in_production():
      client = TestClient(create_app(Settings(app_env="production")))
      assert client.get("/docs").status_code == 404
      assert client.get("/redoc").status_code == 404
      assert client.get("/openapi.json").status_code == 404

  def test_docs_available_in_local():
      client = TestClient(create_app(Settings()))
      assert client.get("/docs").status_code == 200

  def test_cors_exact_origin():
      client = TestClient(create_app(Settings(cors_allowed_origins=["https://app.example"])))
      ok = client.get("/health", headers={"Origin": "https://app.example"})
      assert ok.headers.get("access-control-allow-origin") == "https://app.example"
      bad = client.get("/health", headers={"Origin": "https://evil.example"})
      assert "access-control-allow-origin" not in bad.headers
  ```
- **Cambio mínimo:**
  - `config.py`: añadir `cors_allowed_origins: list[str] = []`.
  - `main.py` (dentro de `create_app`, tras `add_middleware(SecurityHeadersMiddleware, ...)`):
    ```python
    if settings.cors_allowed_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ```
  - Nota: `docs_kwargs` vacío en local deja `/docs` disponible (comportamiento actual preservado).
- **Comando de validación:** `make test-backend` y `make lint`.
- **Criterio de terminado:** `/docs` y `/openapi.json` → 404 en prod; CORS cerrado por defecto (sin `*`).
- **Dependencia:** S2.
- **Rollback:** revertir `main.py`/`config.py`.

### S4 — H4: errores saneados

- **Archivos:** modificar `backend/src/lakehouse/main.py`, `backend/tests/test_security.py`.
- **Prueba primero:**
  ```python
  def test_runtime_error_does_not_leak_internals():
      app_ = create_app(Settings())

      @app_.get("/_boom")
      def _boom() -> None:
          raise RuntimeError("SECRET_INTERNAL_DETAIL")

      client = TestClient(app_, raise_server_exceptions=False)
      r = client.get("/_boom")
      assert r.status_code == 503
      assert "SECRET_INTERNAL_DETAIL" not in r.text
      assert r.json() == {"detail": "Internal server error"}
  ```
- **Cambio mínimo** en `main.py` (dentro de `create_app`):
  ```python
  @app.exception_handler(RuntimeError)
  async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
      logging.getLogger("lakehouse").exception("RuntimeError no controlado", exc_info=exc)
      return JSONResponse(status_code=503, content={"detail": "Internal server error"})
  ```
- **Comando de validación:** `make test-backend`.
- **Criterio de terminado:** el body no expone el texto ni el tipo del error; el detalle queda en logs.
- **Dependencia:** S2.
- **Rollback:** restaurar el handler previo.

### S5 — H5: límite de tamaño de body

- **Archivos:** crear `backend/src/lakehouse/api/body_limit.py`; modificar `backend/src/lakehouse/config.py`, `backend/src/lakehouse/main.py`, `backend/tests/test_security.py`.
- **Prueba primero:**
  ```python
  def test_body_size_limit_returns_413():
      client = TestClient(create_app(Settings()))
      big = '{"question": "' + "a" * 70000 + '"}'
      r = client.post("/auth/login", content=big, headers={"content-type": "application/json"})
      assert r.status_code == 413
      assert r.json() == {"detail": "Request body too large"}
  ```
  (El middleware corre antes del enrutado, por lo que no importa el endpoint; un body pequeño no se ve afectado.)
- **Cambio mínimo:**
  - `config.py`: `max_request_body_bytes: int = 65536`.
  - `body_limit.py`:
    ```python
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BodySizeLimitMiddleware(BaseHTTPMiddleware):
        def __init__(self, app, *, max_bytes: int) -> None:
            super().__init__(app)
            self._max_bytes = max_bytes

        async def dispatch(self, request, call_next):
            if request.method in ("POST", "PUT", "PATCH"):
                length = request.headers.get("content-length")
                if length and length.isdigit() and int(length) > self._max_bytes:
                    return JSONResponse(status_code=413, content={"detail": "Request body too large"})
            return await call_next(request)
    ```
  - `main.py`: `app.add_middleware(BodySizeLimitMiddleware, max_bytes=_settings.max_request_body_bytes)`.
- **Comando de validación:** `make test-backend`.
- **Criterio de terminado:** body grande → 413; body normal no afectado.
- **Dependencia:** S2.
- **Rollback:** quitar el middleware.

### S6 — H5: timeouts de BD y modelo

- **Archivos:**
  - Crear: `backend/src/lakehouse/db/connection.py`.
  - Modificar: `backend/src/lakehouse/config.py`, `backend/src/lakehouse/services/memory.py`, `backend/src/lakehouse/services/agent/tools.py`, `backend/src/lakehouse/services/rate_limit.py`, `backend/src/lakehouse/api/routers/auth.py`, `backend/src/lakehouse/services/rag_search.py`, `backend/tests/test_security.py`.
- **Subspec (migración mecánica a helper):**
  - `config.py`: `db_connect_timeout: int = 5`, `db_statement_timeout_ms: int = 10000`, `model_request_timeout: float = 10.0`.
  - `connection.py`:
    ```python
    import psycopg

    def pg_connect(conn_str: str, *, connect_timeout: int, statement_timeout_ms: int) -> psycopg.Connection:
        return psycopg.connect(
            conn_str,
            connect_timeout=connect_timeout,
            options=f"-c statement_timeout={statement_timeout_ms}",
        )
    ```
  - Reemplazar `psycopg.connect(conn_str)` / `psycopg.connect(pg_conn_str)` / `psycopg.connect(_pg_conn_str(settings))` por `pg_connect(<conn_str>, connect_timeout=settings.db_connect_timeout, statement_timeout_ms=settings.db_statement_timeout_ms)` en cada sitio listado. En `rate_limit.py` (que no recibe `Settings`) pasar los valores como parámetros desde el caller o leer `Settings()`.
  - `rag_search.py`: `httpx.Client()` → `httpx.Client(timeout=settings.model_request_timeout)` (inyectar `Settings()` o pasar timeout como parámetro).
- **Prueba primero:**
  ```python
  def test_pg_connect_applies_timeouts(monkeypatch):
      import psycopg
      captured = {}
      real = psycopg.connect
      def fake(conn_str, **kw):
          captured.update(kw)
          raise RuntimeError("stop")
      monkeypatch.setattr(psycopg, "connect", fake)
      try:
          pg_connect("x", connect_timeout=5, statement_timeout_ms=10000)
      except RuntimeError:
          pass
      assert captured.get("connect_timeout") == 5
      assert "statement_timeout=10000" in captured.get("options", "")
  ```
- **Comando de validación:** `make test-backend` (integración con Postgres vivo valida el flujo) y `make lint`.
- **Criterio de terminado:** todas las conexiones de API pasan por el helper con timeouts; `rag_search` con timeout explícito.
- **Dependencia:** S5.
- **Rollback:** revertir a `psycopg.connect` directo.

### S7 — H6: escáner de secretos

- **Archivos:** crear `scripts/scan_secrets.py`.
- **Prueba primero:** no es pytest; se valida con fixtures de archivos en `/tmp` (caso con secreto → exit 1; caso limpio → exit 0). Se verifica manualmente en S10.
- **Cambio mínimo** (`scripts/scan_secrets.py`):
  - Recorrer `git ls-files` (ejecutado desde la raíz del repo).
  - Excluir: `docs/`, `*.lock`, `uv.lock`, `pnpm-lock.yaml`, `.env.template`.
  - Patrones (regex, case-sensitive/insensitive según patrón):
    - `GEMINI_API_KEY\s*=\s*[A-Za-z0-9_-]{20,}`
    - `DATABASE_URL\s*=\s*postgres(ql)?://[^@\s]+@`
    - `(jwt_secret|csrf_secret)\s*=\s*[A-Za-z0-9+/=]{32,}`
    - `password\s*=\s*[^\s"']{8,}` (solo en líneas no `changeme`/`<...>`/vacías)
    - `-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----`
  - Para `.env.template`: permitir solo placeholders (`changeme`, `<valor>`, cadena vacía tras `=`); marcar cualquier valor no-placeholder como hallazgo.
  - Salida: lista `archivo:línea: tipo`; exit 0 si vacío, exit 1 si hay hallazgos.
- **Comando de validación:** `python scripts/scan_secrets.py; echo $?` → `0`.
- **Criterio de terminado:** no detecta secretos reales en el repo.
- **Dependencia:** ninguna.
- **Rollback:** borrar el script.

### S8 — Inspector determinista y gate

- **Archivos:**
  - Crear: `backend/scripts/security_check.py`, `governance/GATE-SEC-SECURITY.md`.
  - Modificar: `Makefile`.
- **Cambio mínimo:**
  - `security_check.py`:
    ```python
    #!/usr/bin/env python3
    import argparse, sys, subprocess
    from pathlib import Path
    import yaml

    ROOT = Path(__file__).resolve().parents[2]
    CATALOG = ROOT / "governance" / "security-controls.yaml"

    def main() -> int:
        ap = argparse.ArgumentParser()
        ap.add_argument("--report", action="store_true")
        args = ap.parse_args()
        controls = yaml.safe_load(CATALOG.read_text())["controls"]
        failures = []
        for c in controls:
            cid = c["id"]
            for t in c.get("backend_tests", []):
                p = ROOT / "backend" / t
                if not p.exists() or f'pytest.mark.security("{cid}")' not in p.read_text():
                    failures.append(f"{cid}: falta marcador/en archivo {t}")
            for t in c.get("frontend_tests", []):
                p = ROOT / "frontend" / t
                if not p.exists() or f"// security: {cid}" not in p.read_text():
                    failures.append(f"{cid}: falta marcador/en archivo {t}")
            for chk in c.get("checks", []):
                if chk == "lockfiles":
                    if not (ROOT/"backend"/"uv.lock").exists() or not (ROOT/"frontend"/"pnpm-lock.yaml").exists():
                        failures.append(f"{cid}: lockfiles ausentes")
                elif chk == "secrets-scan":
                    r = subprocess.run([sys.executable, str(ROOT/"scripts"/"scan_secrets.py")])
                    if r.returncode != 0:
                        failures.append(f"{cid}: scan_secrets falló")
        print_security_report(controls, failures)
        if args.report:
            return 0
        return 1 if failures else 0
    ```
    (`print_security_report` imprime `ID | título | control | prueba | OK/FAIL`.)
  - `Makefile`:
    ```make
    security:
    	cd backend && uv run python scripts/security_check.py --check
    security-report:
    	cd backend && uv run python scripts/security_check.py --report
    ```
  - `GATE-SEC-SECURITY.md`: criterios de la spec §5.1 (propósito, activación, criterio de salida, regla de bloqueo, relación con otros gates).
- **Comando de validación:** `make security-report` (muestra matriz) y `make security` (exit 0 al final de S10).
- **Criterio de terminado:** el inspector recorre el catálogo y falla si hay control sin prueba.
- **Dependencia:** S1, S7.
- **Rollback:** borrar script y targets.

### S9 — Skills de seguridad (6 dominio + 2 técnicas) + AGENTS.md

- **Archivos:**
  - Crear: `domain/security-auth-jwt.md`, `domain/security-csrf.md`, `domain/security-access-control.md`, `domain/security-injection.md`, `domain/security-output-handling.md`, `domain/security-headers-config.md`, `tech/security_headers.md`, `tech/security_testing.md` (todos bajo `.opencode/skills/`).
  - Modificar: `AGENTS.md` (tabla de skills de dominio y técnicas + sección de gates con `GATE-SEC`).
- **Cambio mínimo:** cada skill de dominio sigue el formato existente (responsabilidad, amenaza OWASP, control materializado, prueba que lo vigila, referencia a tech skill). Las dos técnicas contienen snippet de middleware (S2) y de escritura de pruebas con marcadores (S5/S10) respectivamente.
- **Comando de validación:** verificación manual de que los enlaces de skills y la tabla de AGENTS.md están actualizados.
- **Criterio de terminado:** 8 skills presentes; AGENTS.md actualizado (regla de convivencia).
- **Dependencia:** S2–S8 (las skills documentan lo ya implementado).
- **Rollback:** borrar skills y revertir AGENTS.md.

### S10 — Pruebas de seguridad (unit/integración/e2e) + gate GATE-SEC en AGENTS.md + verificación final

- **Archivos:**
  - Modificar: `backend/tests/test_security.py` (marcador `pytestmark` + tests de S2–S5 ya añadidos), `backend/tests/test_api/test_auth.py` (marcador + test A09), `backend/tests/test_api/test_conversations.py` (marcador A01), `backend/tests/test_agent/test_tools.py` (marcador A05), `backend/tests/test_agent/test_planner.py` y `test_executor.py` (marcadores LLM01/LLM03), `frontend/tests/utils/markdown.test.ts` (marcador `// security: LLM10` + caso `javascript:`), `backend/tests/e2e/test_e2e_smoke.py` (aislamiento 2 usuarios).
  - Modificar: `AGENTS.md` (gate `GATE-SEC` en la lista de gates perpetuos y en comandos).
- **Cambio mínimo:**
  - En cada archivo de test, añadir `pytestmark = pytest.mark.security("<ID>")` (backend) o `// security: <ID>` (frontend) según el catálogo S1.
  - `test_auth.py` — test A09 (usar `caplog`, fixture estándar):
    ```python
    @pytest.mark.security("A09")
    def test_login_does_not_log_or_echo_password(caplog, demo_users) -> None:
        import logging
        client = TestClient(app)
        secret = "super-secret-password"
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/auth/login", json={"username": "testuser1", "password": secret})
        assert resp.status_code == 401
        assert secret not in resp.text
        assert secret not in caplog.text
    ```
  - `markdown.test.ts` — caso extra:
    ```ts
    it('strips javascript: URLs', () => {
      const out = renderMarkdown('[x](javascript:alert(1))')
      expect(out).not.toContain('javascript:')
    })
    ```
  - `test_e2e_smoke.py` — aserción de aislamiento con `E2E_USERNAME2`/`E2E_PASSWORD2` y `pytest.skip` si faltan.
- **Comando de validación:**
  1. `make test-backend` (cobertura ≥90%).
  2. `make lint` + `make typecheck-backend`.
  3. `cd frontend && pnpm typecheck && pnpm test:unit`.
  4. `make security` → exit 0.
  5. `make security-report` → matriz sin huecos.
  6. `scripts/scan_secrets.py` → exit 0.
- **Criterio de terminado:** todos los controles del catálogo ligados a prueba; gates verdes.
- **Dependencia:** S1–S9.
- **Rollback:** revertir marcadores (no afectan el runtime).
