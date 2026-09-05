# Tech Skill: Autenticacion JWT (cookie HttpOnly + CSRF + usuarios demo)

## Proposito

Gobernar la autenticacion del producto: JWT firmado HS256 en cookie `HttpOnly`, proteccion CSRF
para operaciones con estado, hashing de contrasenas con Argon2 y la provision idempotente de los
dos usuarios demo. Es la unica duena del control de acceso por propietario.

## Cuando usar

- Crear o modificar login, logout, `/auth/me`, route guards o cualquier endpoint protegido.
- Decidir si un endpoint nuevo es publico o autenticado (+CSRF).
- Cambiar el manejo de cookies, el secreto JWT o la creacion de usuarios demo.

## Fuente de requisitos

- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 9, 13.1, 14, 15.1, 21).

## Archivos que gobierna

- `backend/src/lakehouse/api/routers/auth.py` (nuevo)
- `backend/src/lakehouse/api/deps.py` (dependencia `get_current_user`)
- `backend/src/lakehouse/services/security.py` (nuevo)
- `backend/src/lakehouse/schemas/auth.py` (nuevo)
- `backend/tests/test_api/test_auth.py`, `tests/test_security.py` (nuevos)

## Invariantes

- `user_id` SIEMPRE se obtiene del JWT validado; nunca del body, query string ni header dictado por el cliente.
- No se guarda JWT en `localStorage`. Cookie: `HttpOnly`, `Path=/`, sin atributo `Domain`.
- Produccion: `Secure=true`, `SameSite=Strict`. Local: `Secure=false` (HTTP local).
- Contrasenas con Argon2 via `pwdlib[argon2]`. JWT HS256 con secreto de al menos 256 bits.
- Claims minimos: `sub`, `iat`, `exp`, `iss`, `aud`. Duracion 60 minutos, sin refresh token en el MVP.
- Las respuestas de login NO distinguen usuario inexistente vs contrasena incorrecta (mensaje identico).
- Dos usuarios demo creados de forma IDEMPOTENTE desde variables protegidas; nunca en Git ni logs.
- Superficie publica: SOLO login y `GET /health`. Todo el resto protegido (ver PRD 9.3).

## Limites

- Login: 5 intentos por minuto por combinacion IP+usuario, con bloqueo progresivo (ver PRD seccion 10).
- No implementar registro publico, refresh tokens, revocacion avanzada ni OAuth en P0.

## Flujo de trabajo

1. Login valida credenciales (Argon2) y emite JWT + token CSRF vinculado a la sesion.
2. La cookie JWT se fija con flags segun entorno; el token CSRF se entrega en el cuerpo del login.
3. `get_current_user` valida firma, `exp` y `aud`, e inyecta la identidad para el resto de la API.
4. Toda operacion con estado exige origen valido + token CSRF en header. `SameSite` es defensa adicional, no la unica.
5. Logout borra la cookie y devuelve cuerpo minimo.

## Verificaciones de aceptacion

- [ ] `POST /auth/login` valido fija cookie `HttpOnly`; invalido devuelve mensaje identico (CA-A01).
- [ ] En produccion la cookie incluye `Secure` y `SameSite=Strict` (CA-A02).
- [ ] Endpoint no publico sin cookie devuelve `401` (CA-A03).
- [ ] 6 intentos de login en un minuto activan `429` (CA-A05).
- [ ] Ninguna contrasena/JWT/API key aparece en repo, respuestas o logs (CA-A06).
- [ ] Tests: `uv run pytest tests/test_api/test_auth.py tests/test_security.py --cov=src --cov-fail-under=90`.
