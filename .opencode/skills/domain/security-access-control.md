# Domain Skill: Control de Acceso por Propietario (A01)

## Proposito

Gobernar el control de acceso vertical y horizontal (OWASP A01 Broken Access Control): la memoria
y las conversaciones de un usuario son invisibles para cualquier otro. La identidad SIEMPRE deriva
del JWT, toda consulta filtra por `user_id` + `conversation_id`, una conversacion ajena responde
`404` (no `403`) y los identificadores publicos son HMAC deterministas, nunca UUID.

## Cuando usar

- Implementar o revisar endpoints de conversaciones (crear/listar/retomar/borrar).
- Escribir consultas de memoria o del agente que crucen usuarios.
- Cambiar la derivacion del `user_id`, el aislamiento o el esquema de ids publicos.

## Fuente de requisitos

- Spec de seguridad: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md` (secciones 5.3 y 7.1, control A01).
- Catalogo: `governance/security-controls.yaml` (control A01).
- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 13.1, 15.2, 16).

## Archivos que gobierna

- `backend/src/lakehouse/api/deps.py` (`get_current_user`: `user_id`, `username`, `role`, `iat` del JWT)
- `backend/src/lakehouse/api/routers/conversations.py` (filtros y 404 en recursos ajenos)
- `backend/src/lakehouse/services/memory.py` (consultas siempre con `user_id` + `conversation_id`)
- `backend/src/lakehouse/services/security.py` (`generate_public_id`, `hmac_digest`)
- Prueba: `backend/tests/test_api/test_conversations.py` (marcador A01)

## Amenaza y control

- **A01 Broken Access Control:** leer/borrar el recurso de otro usuario explotando el id. Control:
  el `user_id` se inyecta como dependencia desde el JWT y las consultas de memoria lo combinan
  SIEMPRE con el `conversation_id`; si el par no existe o no pertenece al usuario, la API responde
  `404` para no confirmar la existencia del recurso ajeno. El frontend envia solo la pregunta y el
  `conversation_id`; nunca el historial ni un `user_id`.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Autenticacion JWT | `../tech/autenticacion_jwt.md` | Origen del `user_id` (JWT) y superficie protegida |
| DuckDB + pgvector | `../tech/duckdb_pgvector.md` | Consultas parametrizadas por propietario |
| Testing de Seguridad | `../tech/security_testing.md` | Marcador A01 y gate `make security` |

## Invariantes

- Ninguna consulta de memoria lee sin `user_id` + `conversation_id` en la misma sentencia.
- Conversacion ajena o inexistente -> `404`. Nunca `403` ni `200`.
- Listar/retomar/continuar/borrar solo sobre conversaciones propias no vencidas.
- El `user_id` nunca viaja en el body ni como parametro de cliente.
- Identificadores publicos opacos y deterministas (HMAC de id interno + secreto); prohibido UUID4/Snowflake.
- El borrado en cascada solo elimina recursos del propietario autenticado.

## Matriz de aislamiento (regla)

2 usuarios x 2 conversaciones x leer/continuar/borrar: ningun cruce de usuario 2 sobre recursos de
usuario 1, y viceversa; el cruce por identificador devuelve `404`.

## Verificaciones de aceptacion

- [ ] Usuario 2 no lista/lee/continua/borra conversaciones del usuario 1 (A01, `tests/test_api/test_conversations.py`: `test_cross_user_isolation`).
- [ ] Crear, listar y borrar en cascada de un usuario no afecta al otro (`test_create_and_list_conversations`, `test_delete_cascades`).
- [ ] Intento cruzado por identificador devuelve `404` (CA-M04).
- [ ] Matriz 2x2 de aislamiento pasa (PRD seccion 16).
- [ ] `make security`: control A01 en estado OK.
