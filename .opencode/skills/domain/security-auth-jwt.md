# Domain Skill: Autenticacion y Criptografia (A07 + A04)

## Proposito

Gobernar los controles de autenticacion (OWASP A07 Authentication Failures) y criptografia
(OWASP A04 Cryptographic Failures) del API: emision de JWT HS256 con claims minimos en cookie
HttpOnly, hashing de contrasenas con Argon2, mensaje generico de login, rate limit de login y
resolucion de secretos exigente en produccion. Es la duena del ciclo login/logout.

## Cuando usar

- Implementar o revisar login, logout, `/auth/me` o cualquier endpoint protegido.
- Decidir si un endpoint nuevo es publico o autenticado.
- Cambiar secretos JWT/CSRF, duracion, claims, flags de cookie o limites de login.

## Fuente de requisitos

- Spec de seguridad: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md` (secciones 5.3 y 7.1, controles A07/A04).
- Catalogo: `governance/security-controls.yaml` (controles A07 y A04).
- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 9, 13.1, 14, 15.1).

## Archivos que gobierna

- `backend/src/lakehouse/services/security.py` (`create_access_token`, `decode_access_token`, `resolve_jwt_secret`, `hash_password`, `verify_password`)
- `backend/src/lakehouse/api/routers/auth.py` (login/logout, flags de cookie, rate limit)
- `backend/src/lakehouse/api/deps.py` (`get_current_user`)
- `backend/src/lakehouse/schemas/auth.py`
- `backend/src/lakehouse/config.py` (`jwt_secret`, `csrf_secret`, `jwt_expire_minutes`, `login_rate_limit`, `cookie_secure`)
- Pruebas: `backend/tests/test_api/test_auth.py` (marcador A07), `backend/tests/test_security.py` (marcador A04)

## Amenaza y control

- **A07 Authentication Failures:** login fallido devuelve mensaje identico (nunca revela si el
  usuario existe); rate limit de login 5/min por ventana en PostgreSQL atomico
  (`services/rate_limit.py` con `INSERT ... ON CONFLICT`, config `login_rate_limit`); JWT expira a
  los 60 minutos (`jwt_expire_minutes`) y el decode valida `iss`/`aud` con algoritmo fijo HS256.
- **A04 Cryptographic Failures:** secreto JWT de al menos 32 chars; en produccion si falta o es
  corto `resolve_jwt_secret` lanza `RuntimeError` (no existe fallback a dev); contrasenas con
  Argon2 via `pwdlib[argon2]`; cookie `HttpOnly` + `SameSite=Strict` + `Secure`(prod); la IP del
  login se guarda como HMAC, nunca en claro.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Autenticacion JWT | `../tech/autenticacion_jwt.md` | Convenciones de JWT, cookie y usuarios demo |
| Testing de Seguridad | `../tech/security_testing.md` | Marcadores A07/A04 y gate `make security` |

## Invariantes

- `user_id` SIEMPRE se obtiene del JWT validado; nunca del body, query string ni header del cliente.
- Cookie: `HttpOnly`, `Path=/`, sin atributo `Domain`. Produccion: `Secure=true`,
  `SameSite=Strict`. Local: `Secure=false` (HTTP local).
- Claims minimos `sub`, `iat`, `exp`, `iss`, `aud`; decode fijo a HS256 con validacion de `iss`/`aud`.
- Login no distingue usuario inexistente de contrasena incorrecta.
- Sin secreto JWT >= 32 chars en produccion el proceso no arranca la sesion (RuntimeError).
- Superficie publica: SOLO `POST /auth/login` y `GET /health`; todo lo demas exige JWT.
- Ninguna contrasena, JWT o secreto llega a repo, logs o respuestas.

## Flujo de trabajo

1. `POST /auth/login` valida credenciales (Argon2) bajo rate limit y fija la cookie con flags por entorno.
2. El login devuelve en el cuerpo el token CSRF de la sesion (ver `security-csrf.md`).
3. `get_current_user` decodifica el token de la cookie y expone la identidad al resto de la API.
4. Logout (protegido por CSRF) borra la cookie.

## Verificaciones de aceptacion

- [ ] Login valido fija cookie `HttpOnly`; invalido devuelve mensaje identico (A07, `tests/test_api/test_auth.py`: `test_login_success_sets_cookie`, `test_login_invalid_same_message`).
- [ ] 6 intentos de login en un minuto activan `429` (CA-A05).
- [ ] Secreto JWT ausente o corto en produccion lanza `RuntimeError` (A04, `tests/test_security.py`: `test_production_requires_secret`).
- [ ] Token vencido rechazado (A04, `tests/test_security.py`: `test_access_token_expiry`).
- [ ] Endpoint no publico sin cookie devuelve `401` (`test_protected_endpoint_requires_auth`).
- [ ] `make security`: controles A07 y A04 en estado OK.
