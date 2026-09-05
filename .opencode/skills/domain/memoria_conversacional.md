# Domain Skill: Memoria Conversacional Aislada

## Proposito

Gobernar la persistencia, aislamiento, retencion y borrado de la memoria conversacional. La memoria
existe SOLO dentro de una conversacion; no hay recuerdos compartidos entre conversaciones ni perfil
persistente del usuario. Es distinta de la ventana de tokens (ver `memoria_rag_tokens.md`).

## Cuando usar

- Implementar o revisar endpoints de conversaciones (crear/listar/retomar/borrar) o persistencia de mensajes.
- Cargar historial autorizado en el turno del agente.
- Implementar retencion (30 dias) o borrado en cascada.

## Fuente de requisitos

- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 8, 15.2, 21).

## Archivos que gobierna

- `backend/src/lakehouse/schemas/conversation.py` (nuevo)
- `backend/src/lakehouse/api/routers/conversations.py` (nuevo)
- `backend/src/lakehouse/db/migrations/` (tablas `app_user`, `conversation`, `message`, `tool_execution`)
- `backend/src/lakehouse/services/memory.py` (nuevo)
- `backend/tests/test_api/test_conversations.py` (nuevo)

## Modelo de datos minimo

- `app_user`: hash Argon2, estado, fechas.
- `conversation`: propietario, titulo, creacion, `last_activity_at`, `expires_at`.
- `message`: conversacion, propietario redundante (control), rol, contenido, tokens, modelo, fecha.
- `tool_execution`: conversacion, turno, tool, argumentos saneados, cantidad de resultados, duracion, estado, fecha.

## Invariantes

- Todo acceso incluye SIEMPRE `conversation_id` + `user_id` (derivado del JWT) en la misma consulta.
- Conversacion ajena devuelve `404` (nunca `403`) para no confirmar su existencia.
- El frontend NO envia el historial; envia solo la pregunta + `conversation_id`. El servidor carga el historial autorizado.
- Identificadores publicos de conversacion opacos y deterministas (HMAC de id interno + secreto servidor); NO UUID4 aleatorios.
- Borrado en cascada; el borrado elimina mensajes y trazas de inmediato; nada del contenido borrado queda en logs de aplicacion.
- Retencion: 30 dias desde `last_activity_at`; cada turno valido renueva `last_activity_at` y `expires_at`.

## Flujo de trabajo

1. Crear conversacion -> devolver id opaco al cliente.
2. Turno del agente -> cargar historial propio (`conversation_id` + `user_id`), ejecutar, persistir mensajes + traza.
3. Listar/retomar -> solo conversaciones propias no vencidas.
4. Borrar -> cascada; limpieza programada/oportunista elimina las vencidas.

## Verificaciones de aceptacion

- [ ] Un usuario crea 2 conversaciones y retoma cada una con su historial correcto (CA-M01).
- [ ] Referencia mencionada solo en A no aparece al preguntar en B (CA-M02).
- [ ] Usuario 2 no puede listar/leer/continuar/borrar una conversacion del usuario 1 (CA-M03).
- [ ] Intento cruzado por identificador devuelve `404` (CA-M04).
- [ ] Borrar elimina mensajes y trazas y desaparece del listado (CA-M05).
- [ ] >30 dias de inactividad -> se elimina o deja de estar disponible (CA-M06).
- [ ] Matriz 2 usuarios x 2 conversaciones x leer/continuar/borrar pasa (PRD seccion 16).
