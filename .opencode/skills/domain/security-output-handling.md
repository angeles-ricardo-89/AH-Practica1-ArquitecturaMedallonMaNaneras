# Domain Skill: Manejo de Salida del Modelo (LLM05 + LLM02)

## Proposito

Gobernar el tratamiento de la salida del modelo: nunca se ejecuta ni se inyecta HTML crudo
(OWASP LLM05 Improper Output Handling) y los errores internos nunca filtran detalle al cliente
(OWASP LLM02 Sensitive Information Disclosure). La salida se sanea en el frontend con DOMPurify y el
backend responde errores genericos mientras el detalle queda solo en logging.

## Cuando usar

- Cambiar el renderizado de markdown/HTML proveniente del agente en el frontend.
- Tocar el handler global de errores, excepciones o el formato de las respuestas de error del API.
- Ajustar el logging de excepciones sin exponer secretos ni contenido completo.

## Fuente de requisitos

- Spec de seguridad: `docs/superpowers/specs/2026-09-05-security-hardening-gate-design.md` (secciones 5.3, 7.1 y 8.4, controles LLM05/LLM02).
- Catalogo: `governance/security-controls.yaml` (controles LLM05 y LLM02).
- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 13.2, 13.3).

## Archivos que gobierna

- `frontend/src/utils/markdown.ts` (`renderMarkdown`: `marked.parse` + `DOMPurify.sanitize`)
- `frontend/tests/utils/markdown.test.ts` (marcador `// security: LLM05`)
- `backend/src/lakehouse/main.py` (`exception_handler` de `RuntimeError` en `create_app`)
- `backend/src/lakehouse/log_config.py` (configuracion de niveles y salida de logs)
- Prueba: `backend/tests/test_security.py` (marcador LLM02)

## Amenaza y control

- **LLM05 Improper Output Handling:** la salida del modelo puede contener HTML o markdown
  malicioso que, inyectado sin sanear, ejecuta en el navegador del usuario. Control: el texto se
  parsea con `marked` y se pasa por `DOMPurify.sanitize` ANTES de insertarlo en el DOM; el
  frontend nunca pinta HTML sin sanear y los resultados del agente se validan antes de renderizar.
- **LLM02 Sensitive Information Disclosure:** un error interno puede devolver `str(exc)`, el tipo de la
  excepcion o trazas que revelan arquitectura o datos. Control: el handler global de `RuntimeError`
  en `main.py` responde `503` con cuerpo fijo `{"detail": "Internal server error"}` en cualquier
  entorno, sin incluir el texto ni el tipo de la excepcion; el detalle se registra solo via
  `logging.getLogger("lakehouse").exception(...)`.

## Tech Skills de Referencia

| Tech Skill | Archivo | Como la usa |
|------------|---------|-------------|
| Vue 3 + Pinia + Tailwind | `../tech/vue3_pinia_tailwind.md` | Renderizado del markdown saneado en componentes |
| Testing de Seguridad | `../tech/security_testing.md` | Marcadores LLM05/LLM02 y gate `make security` |

## Invariantes

- Toda salida del modelo que llegue al DOM pasa por DOMPurify; prohibido `v-html` con HTML sin sanear.
- El servidor nunca devuelve `str(exc)`, tipo de excepcion ni stack trace al cliente.
- Cuerpo de error generico identico en local y produccion (el detalle vive solo en los logs).
- Los logs no contienen contrasenas, JWTs, tokens CSRF ni contenido completo de conversaciones.
- El error saneado mantiene los headers de seguridad en la respuesta (se decoran incluso respuestas cortas).

## Verificaciones de aceptacion

- [ ] `<script>`, handlers `onerror` y URLs de esquema `javascript:` quedan eliminadas de la salida saneada (LLM05, marcador `// security: LLM05` en `frontend/tests/utils/markdown.test.ts`; hoy cubre `strips script tags` y `strips img onerror handlers`).
- [ ] Un `RuntimeError` interno devuelve `503` sin el texto de la excepcion (LLM02, `tests/test_security.py`: `test_runtime_error_does_not_leak_internals`).
- [ ] `cd frontend && pnpm test:unit` verde.
- [ ] `make security`: controles LLM05 y LLM02 en estado OK.
