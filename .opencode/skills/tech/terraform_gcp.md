# Tech Skill: Despliegue GCP con Terraform (IaC)

## Proposito

Gobernar la infraestructura como codigo del despliegue productivo en GCP usando Terraform: Cloud Run,
enlace/provision de Neon, Secret Manager, APIs de Gemini y service accounts. No cubre la configuracion
de runtime (ver `config_runtime_gcp.md`).

## Cuando usar

- Crear o editar `*.tf` (providers, recursos, backend de estado) o definir secretos/identidades GCP.
- Anadir un recurso, variable o version de Terraform.

## Fuente de requisitos

- PRD 3.0: `docs/prd/PRD_3_0_AGENTE_INVESTIGACION_MANANERAS.md` (secciones 11.2, 19, 20, 21).

## Archivos que gobierna

- `infra/terraform/` (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, `backend.tf`) (nuevo)
- `infra/terraform/terraform.tfvars.example` (nuevo; `terraform.tfvars` NO se commitea)
- `.gitignore` (entrada para `*.tfvars` y `.terraform/`)

## Invariantes

- Estado remoto en bucket GCS (no estado local), con versionado y bloqueo.
- Secretos SOLO en Secret Manager (maximo 6 versiones activas para nivel gratuito); NUNCA en `*.tf`, `tfvars` commiteado, Git o logs.
- `DATABASE_URL`, `GEMINI_API_KEY`, secreto JWT y credenciales demo -> Secret Manager.
- Service account de Cloud Run con privilegios minimos (roles concretos; nunca `roles/owner`/`roles/editor`).
- Recursos con etiquetas de costo y region fija. Terraform como unica via de aprovisionamiento en P0.

## Limites

- Cloud Run: `max-instances=1`, escala a cero, facturacion por solicitud (ver `config_runtime_gcp.md`).
- Sin dominio personalizado en P0; la URL `run.app` es la entrega. Dominio -> P1.

## Flujo de trabajo

1. `terraform init` (backend remoto), `terraform plan`, `terraform apply` solo tras revision del plan.
2. Activar APIs necesarias (Cloud Run, Secret Manager, generativelanguage/aiplatform) y enlazar Neon.
3. Desplegar el build unico web+API como servicio Cloud Run con secretos montados.
4. `terraform output` expone la URL `run.app` y los ids minimos requeridos.

## Verificaciones de aceptacion

- [ ] `terraform validate` y `terraform plan` limpios.
- [ ] `terraform apply` crea el servicio Cloud Run con `max-instances=1` y escala a cero.
- [ ] Ningun secreto en `git status`, `git diff` ni en `*.tf`/`*.tfvars` commiteados.
- [ ] La URL `run.app` abre login, autentica, conversa, retoma y borra (CA-D04).
