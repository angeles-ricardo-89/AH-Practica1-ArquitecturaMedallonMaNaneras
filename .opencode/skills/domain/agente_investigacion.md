# Domain Skill: Agente de Investigacion (plan JSON + 3 tools de solo lectura)

## Proposito

Gobernar el ciclo agentico acotado: plan JSON validado por Pydantic, ejecucion de como maximo dos
tools internas de solo lectura, sintesis con evidencia y negativa explicita cuando no hay respaldo.
NO usar LangChain, LangGraph, Google ADK ni PydanticAI.

## Cuando usar

- Implementar o ajustar el planificador, validador, ejecutor o sintetizador del agente.
- Anadir o modificar una tool (hoy exactamente 3; ninguna nueva sin pasar Gate S).

## Fuente de requisitos

- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 6, 7, 15.3, 21).

## Archivos que gobierna

- `backend/src/lakehouse/services/agent/` (planner, executor, tools) (nuevo)
- `backend/src/lakehouse/schemas/agent.py` (modelos de plan y resultados) (nuevo)
- `backend/src/lakehouse/api/routers/conversations.py` (turno del agente)
- `backend/tests/test_agent/` (nuevo)

## Las tres tools (allowlist cerrada, solo lectura)

| Tool | Entradas | Salida | Regla |
| --- | --- | --- | --- |
| `buscar_declaraciones` | consulta; `fecha_inicio`?; `fecha_fin`?; `participante`?; `top_k` 1..8 | evidencia (id, texto, fecha, participante, conferencia, URL, similitud) | filtros relacionales ANTES del ranking vectorial |
| `explorar_temas` | texto opcional; limite 1..5 | cluster (id, etiqueta, terminos, tamano, cohesion, rango fechas) | sin consulta, por tamano/calidad; nunca presentar ruido como tema |
| `consultar_cluster` | `cluster_id` validado; limite 1..8 | metadatos + evidencias representativas | cluster = agrupacion algoritmica, nunca "hecho" |

## Invariantes

- Ningun SQL, URL, `user_id` o nombre libre de tool proviene del modelo: todo pasa por allowlist + Pydantic.
- Maximo DOS ejecuciones de tool por mensaje. Maximo 10 segundos por tool. Limite de filas por tool.
- El agente local funciona completamente OFFLINE (no llama a Gemini ni a la red).
- Gemma produce un plan JSON que Pydantic valida; si falla -> UN reintento con instrucciones de reparacion -> fallback seguro a `buscar_declaraciones` (trazable, no simulado).
- El agente se NIEGA a concluir sin evidencia suficiente (umbral definido en el PRD).
- La salida del modelo nunca se ejecuta; los resultados se sanean y validan antes de renderizar (ver PRD 13.2 LLM10).

## Ciclo

`Pregunta autenticada -> cargar memoria propia -> plan JSON validado -> ejecutar tool -> (opcional 1 tool mas) -> responder con evidencia -> guardar turno y traza`.

## Verificaciones de aceptacion

- [ ] Pregunta sobre persona/tema invoca `buscar_declaraciones` (CA-T01); temas generales `explorar_temas` (CA-T02); seguimiento de cluster `consultar_cluster` (CA-T03).
- [ ] Nunca mas de 2 tools (CA-T04). Tool/argumento no permitido rechazado antes de acceder a datos (CA-T05).
- [ ] Inyeccion dentro de una transcripcion no cambia instrucciones ni habilita tools (CA-T06).
- [ ] Sin evidencia suficiente -> negativa explicita (CA-T07).
- [ ] Cada respuesta muestra tool, filtros, cantidad, latencia y evidencias (CA-T08).
- [ ] `uv run pytest tests/test_agent/ --cov=src --cov-fail-under=90` y prueba offline sin red hacia Gemini (PRD seccion 16).
