# Domain Skill: Configuracion, Headers y Limites (A02 + A10/A09/A03 + SEC)

## Proposito

Gobernar el endurecimiento transversal del API: headers de seguridad y desactivacion de docs en
produccion (OWASP A02), condiciones excepcionales y consumo acotado (A10), logging sin secretos
(A09) y cadena de suministro (A03). Tambien cubre el diseno
fail-closed (A06): ante configuracion ausente se niega, no se permite.

## Cuando usar

- Tocar el middleware de headers, CORS, docs, limite de body o timeouts de BD/modelo.
- Configurar entornos (`app_env`, origenes CORS, tamaños y timeouts).
- Revisar logging, lockfiles o el escaneo de secretos antes de publicar.

## Fuente de requisitos

- Spec de seguridad: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md` (secciones 2.2, 5.3, 7.1 y 8.1-8.6).
- Catalogo: `governance/security-controls.yaml` (controles A02, A10, A09, A03 y SEC).
- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 10, 13.1).

## Archivos que gobierna

- `backend/src/lakehouse/api/security_headers.py` (`SecurityHeadersMiddleware`)
- `backend/src/lakehouse/api/body_limit.py` (`BodySizeLimitMiddleware`)
- `backend/src/lakehouse/main.py` (`create_app`: orden de middlewares, CORS, docs en prod, handler de errores)
- `backend/src/lakehouse/db/connection.py` (`pg_connect`, `pg_conn_str_with_timeouts`)
- `backend/src/lakehouse/config.py` (`app_env`, `cors_allowed_origins`, `max_request_body_bytes`, `db_connect_timeout`, `db_statement_timeout_ms`, `model_request_timeout`)
- `backend/src/lakehouse/services/rate_limit.py` (limites en PostgreSQL atomico)
- `scripts/scan_secrets.py` (escaner de secretos rastreados por git)
- `backend/scripts/security_check.py` (inspector GATE-SEC)
- Prueba: `backend/tests/test_security.py` (marcadores A02 y A10) + chequeos `lockfiles` y `secrets-scan` del catalogo

## Amenaza y control

- **A02 Misconfiguration:** headers `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  no-referrer` y `X-Frame-Options: DENY` SIEMPRE; `Strict-Transport-Security` y CSP solo en
  produccion; `/docs`, `/redoc` y `/openapi.json` deshabilitados en prod; CORS de origen exacto con
  lista vacia por defecto (fail-closed, sin `*`).
- **A10 Mishandling of Exceptional Conditions:** body limit 64 KB con `413` en POST/PUT/PATCH;
  `connect_timeout=5` y `statement_timeout=10000` ms de BD centralizados en `db/connection.py`;
  timeout de modelo `model_request_timeout` (10 s) configurable.
- **A09 Logging Failures:** sin contrasenas, tokens, secretos ni contenido completo en logs; la IP se guarda como HMAC.
- **A03 Supply Chain:** lockfiles presentes (`backend/uv.lock`, `frontend/pnpm-lock.yaml`) y dependencias fijadas.
- **SEC Secret Scanning:** `scripts/scan_secrets.py` determinista (regex sobre archivos de `git ls-files`) corre antes de publicar.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Security Headers | `../tech/security_headers.md` | Implementacion del middleware, CORS, docs y body |
| Testing de Seguridad | `../tech/security_testing.md` | Marcadores A02/A10 y chequeos del catalogo |

La higiene de logging (A09: sin secretos ni contenido en logs, niveles por entorno) se gobierna en
esta skill; `observabilidad_pull.md` solo gobierna los endpoints de estado y el polling del dashboard.

## Invariantes

- Headers de seguridad se anaden incluso a respuestas cortas (404 de docs, 413 de body, 401/403).
- CORS con lista vacia no emite `Access-Control-Allow-Origin` a ningun origen.
- En produccion no existe `/docs`, `/redoc` ni `/openapi.json`.
- Body > `max_request_body_bytes` en POST/PUT/PATCH -> `413`.
- Toda conexion a Postgres usa `db/connection.py` con timeouts; prohibido `psycopg.connect` a pelo.
- Ningun secreto aparece en el repo rastreado (el template `.env` solo tiene placeholders).

## Verificaciones de aceptacion

- [ ] Headers presentes en cualquier respuesta; HSTS/CSP solo en prod (A02, `tests/test_security.py`: `test_security_headers_always_present`, `test_hsts_and_csp_only_in_production`, `test_no_hsts_csp_in_local`).
- [ ] `/docs` y `/openapi.json` -> `404` en prod (A02, `test_docs_disabled_in_production`).
- [ ] CORS: origen no permitido sin `Access-Control-Allow-Origin`; permitido lo recibe exacto (A02, `test_cors_exact_origin`, `test_cors_fail_closed_by_default`).
- [ ] Body grande -> `413`; timeouts de BD aplicados (A10, `test_body_size_limit_returns_413`, `test_pg_connect_applies_timeouts`).
- [ ] `make security`: controles A02/A10/A09/A03/SEC en estado OK.
