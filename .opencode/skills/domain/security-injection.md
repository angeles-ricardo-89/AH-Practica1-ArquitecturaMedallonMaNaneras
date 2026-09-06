# Domain Skill: Inyeccion y Agencia Acotada (A05 + LLM01 + LLM03)

## Proposito

Gobernar las defensas del agente contra inyeccion: SQL parametrizado (OWASP A05), prompt
injection (OWASP LLM01) y agencia excesiva (OWASP LLM03). Ningun SQL, URL, `user_id` ni nombre
libre de tool proviene del modelo: el plan JSON se valida con Pydantic contra una allowlist de 3
tools de solo lectura y el agente ejecuta como maximo dos tools por mensaje.

## Cuando usar

- Implementar o ajustar planner, validador, executor, tools o synthesizer del agente.
- Anadir o modificar una tool (hoy exactamente 3; ninguna nueva sin pasar Gate S).
- Revisar consultas SQL del backend de datos o del servicio de memoria.

## Fuente de requisitos

- Spec de seguridad: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md` (secciones 5.3 y 7.1, controles A05/LLM01/LLM03).
- Catalogo: `governance/security-controls.yaml` (controles A05, LLM01, LLM03).
- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 6, 7, 13.1, 15.3).

## Archivos que gobierna

- `backend/src/lakehouse/services/agent/planner.py` (plan JSON, reparacion y fallback seguro)
- `backend/src/lakehouse/services/agent/executor.py` (ejecucion, maximo 2 tools, tiempo por tool)
- `backend/src/lakehouse/services/agent/tools.py` (3 tools allowlist de solo lectura)
- `backend/src/lakehouse/services/agent/synthesizer.py` (sintesis con evidencia y negativa)
- `backend/src/lakehouse/schemas/agent.py` (modelos Pydantic del plan)
- Pruebas: `backend/tests/test_agent/test_planner.py` (marcador LLM01), `test_executor.py` (marcadores LLM01/LLM03), `test_tools.py` (marcador A05)

## Amenaza y control

- **A05 Injection:** la fuente de datos es un corpus propio (no hay SQL, URL ni busqueda web del
  modelo). Toda consulta a Postgres usa parametros de psycopg (`%s`); las tools no aceptan SQL ni
  URL y rechazan entradas fuera de su contrato (tipos, rangos, claves inexistentes).
- **LLM01 Prompt Injection:** el corpus recuperado y la transcripcion se tratan como DATO, nunca
  como instruccion. Gemma solo produce un plan JSON que Pydantic valida; si no pasa, un reintento
  con instrucciones de reparacion y, si falla de nuevo, fallback seguro a `buscar_declaraciones`
  (trazable, no simulado).
- **LLM03 Excessive Agency:** el plan admite como maximo 2 ejecuciones de tool por mensaje; cada
  tool declara parametros estrictos (tipos, rangos, top_k acotado) y un limite de filas y de
  segundos por ejecucion.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| FastAPI + Pydantic + Typer | `../tech/fastapi_pydantic_typer.md` | Validacion estricta del plan JSON |
| Testing de Seguridad | `../tech/security_testing.md` | Marcadores A05/LLM01/LLM03 y gate `make security` |

## Invariantes

- El modelo no emite SQL, URLs, `user_id` ni argumentos libres: todo pasa por allowlist + Pydantic.
- Tres tools de solo lectura, cerradas: `buscar_declaraciones`, `explorar_temas`, `consultar_cluster`.
- Maximo DOS ejecuciones de tool por mensaje y maximo 10 segundos por tool.
- Nombre de tool fuera de la allowlist o argumento con tipo/rango no permitido se rechaza ANTES de
  tocar datos; argumentos extra desconocidos se ignoran por el esquema Pydantic (no se ejecutan).
- El corpus es dato: su contenido no cambia instrucciones ni habilita tools.
- Sin evidencia suficiente el agente se niega a concluir (negativa explicita).

## Verificaciones de aceptacion

- [ ] Tool fuera de la allowlist rechazada antes de acceder a datos (LLM01, `tests/test_agent/test_planner.py`: `test_validate_plan_allowlist`).
- [ ] Plan invalido se repara una vez y, si vuelve a fallar, cae al fallback seguro (`test_plan_first_tool_repairs_after_invalid`, `test_plan_first_tool_fallback_after_double_invalid`).
- [ ] Nunca mas de 2 tools por turno (LLM03, `tests/test_agent/test_executor.py`: `test_run_agent_turn_never_exceeds_two_tools`).
- [ ] Entradas invalidas de tools rechazadas (A05, `tests/test_agent/test_tools.py`: `test_consultar_cluster_unknown`).
- [ ] `uv run pytest tests/test_agent/ --cov=src --cov-fail-under=90` verde.
- [ ] `make security`: controles A05, LLM01 y LLM03 en estado OK.
