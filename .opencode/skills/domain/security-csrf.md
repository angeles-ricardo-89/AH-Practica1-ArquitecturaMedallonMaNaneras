# Domain Skill: CSRF (token HMAC en header X-CSRF-Token)

## Proposito

Gobernar la proteccion CSRF de toda operacion con estado. El control no tiene id OWASP unico, por
lo que el catalogo lo identifica como `CSRF`. El token es un HMAC derivado de `user_id:iat` con
secreto de servidor, viaja en el header `X-CSRF-Token` y `SameSite=Strict` es solo defensa en
profundidad, nunca el control unico.

## Cuando usar

- Implementar o revisar endpoints que mutan estado (crear/continuar/borrar conversacion, logout).
- Decidir si un endpoint nuevo con estado necesita CSRF (SIEMPRE lo necesita).
- Cambiar el header, el secreto CSRF o la derivacion del token.

## Fuente de requisitos

- Spec de seguridad: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md` (secciones 5.3 y 7.1, control CSRF).
- Catalogo: `governance/security-controls.yaml` (control CSRF).
- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 13.1, 15.1).

## Archivos que gobierna

- `backend/src/lakehouse/services/security.py` (`create_csrf_token`, `verify_csrf_token`)
- `backend/src/lakehouse/api/deps.py` (dependencia `require_csrf`)
- `backend/src/lakehouse/api/routers/auth.py` (logout protegido; emite el token en el login)
- `backend/src/lakehouse/api/routers/conversations.py` (endpoints con `dependencies=[Depends(require_csrf)]`)
- `backend/src/lakehouse/config.py` (`csrf_secret`, `csrf_header_name`)
- Prueba: `backend/tests/test_api/test_auth.py` (marcador CSRF)

## Amenaza y control

- **CSRF:** un sitio ajeno dispara un request con estado reutilizando la cookie de sesion. Control:
  el login entrega `csrf_token = HMAC-SHA256("user_id:iat", secreto_servidor)` en el cuerpo; todo
  endpoint con estado exige ese token en el header `X-CSRF-Token` via `require_csrf`, que lo
  recalcula contra el `user_id` y el `iat` del JWT y lo compara con `hmac.compare_digest`
  (tiempo constante). `SameSite=Strict` en la cookie reduce la superficie pero no la elimina.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Autenticacion JWT | `../tech/autenticacion_jwt.md` | Sesion HttpOnly, origen del `user_id` y del `iat` |
| Testing de Seguridad | `../tech/security_testing.md` | Marcador CSRF y gate `make security` |

## Invariantes

- El token CSRF es determinista (HMAC de `user_id:iat`), nunca aleatorio y nunca persistido aparte.
- Secreto CSRF >= 32 chars en produccion (sin fallback a dev; ver `resolve_csrf_secret`).
- `require_csrf` se aplica a crear/borrar conversacion y a logout; tambien a cualquier endpoint nuevo con estado.
- El frontend envia el token en el header `X-CSRF-Token` (nombre de `config.csrf_header_name`).
- Token ausente o incorrecto devuelve `403`, nunca `401` ni `200`.
- `SameSite` nunca sustituye la verificacion del header.

## Flujo de trabajo

1. Login exitoso devuelve `csrf_token` vinculado a la sesion en el cuerpo de la respuesta.
2. El frontend lo almacena en memoria y lo envia como header en cada mutacion.
3. `require_csrf` verifica el header contra `user_id` + `iat` del JWT actual.
4. Mismatch o ausencia -> `403`.

## Verificaciones de aceptacion

- [ ] Crear/borrar conversacion o logout sin token devuelve `403` (`tests/test_api/test_auth.py` marcador CSRF; tambien `test_create_requires_csrf` y `test_delete_requires_csrf` en `test_conversations.py`).
- [ ] Logout con token valido pasa (`test_logout_with_csrf`).
- [ ] Token con otro `user_id` o `iat` no verifica (A04, `tests/test_security.py`: `test_csrf_token_roundtrip`).
- [ ] `make security`: control CSRF en estado OK.
