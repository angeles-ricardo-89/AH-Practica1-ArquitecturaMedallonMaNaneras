# Tech Skill: Costo de Infraestructura GCP (determinista, meta $0)

## Proposito

Gobernar el calculo y monitoreo del costo de la infraestructura productiva para que las decisiones de
despliegue mantengan el costo minimo ($0) mientras sea posible. Define una herramienta determinista de
calculo y su uso. La herramienta se construye en P0.6 (no en la fase de especificacion).

## Cuando usar

- Antes de aprobar cualquier cambio de despliegue que pueda alterar costo (instancias, region, modelos, almacenamiento).
- En el checkpoint de despliegue P0.6 y en la revision final de la demo.

## Fuente de requisitos

- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (seccion 20 presupuesto ~USD 0, no garantizado; seccion 19 riesgo de exceder nivel gratuito).

## Archivos que gobierna

- `scripts/gcp_cost.py` (nuevo; se construye en P0.6)
- `scripts/gcp_cost.example.json` (config de ejemplo)
- Snapshot de precios congelado (fecha + fuente) embebido en el script

## Invariantes

- Determinista: pura funcion de los recursos + constantes de precios documentadas (fecha + fuente). NO llama a APIs de precios ni a red.
- Meta: costo mensual estimado ~USD 0 dentro del nivel gratuito; el script marca cualquier componente que exceda su free tier.
- Alertas de presupuesto GCP informan pero NO son corte automatico; los controles efectivos son la cuota diaria de app y `max-instances=1`.
- No prometer costo exactamente cero: reportar estimacion, suposiciones y version del snapshot.

## Componentes a evaluar

| Recurso | Free tier objetivo |
| --- | --- |
| Cloud Run | CPU/memoria/solicitudes mensuales gratis (facturacion por peticion) |
| Neon | plan gratuito, escala a cero; vigilar cuota de computo |
| Gemini Flash-Lite | nivel gratuito (aviso de datos aceptado) |
| Gemini Embeddings | nivel gratuito |
| Secret Manager | <= 6 versiones activas, 10,000 accesos/mes |

## Flujo de trabajo

1. Definir config JSON con recursos (instancias, region, modelo, dimensiones, almacenamiento).
2. Ejecutar `uv run python scripts/gcp_cost.py --config scripts/gcp_cost.example.json`.
3. Revisar salida JSON: costo mensual por componente + flags de free-tier excedido.
4. Si algun componente excede $0, detener y reconsiderar antes de aplicar Terraform.

## Verificaciones de aceptacion

- [ ] `uv run python scripts/gcp_cost.py --config ...` produce costo determinista (misma entrada -> misma salida).
- [ ] La salida marca explicitamente si se excede el nivel gratuito.
- [ ] La config de la demo reporta costo estimado ~$0 y lo documenta con la fecha del snapshot de precios.
