# Especificación de diseño — Dominio propio rag-del-pueblo.tsib.dev (Cloud Run)

**Fecha:** 2026-09-07
**Fuente:** petición directa del operador (dominio comprado en Squarespace)
**Estado:** Especificación en revisión (spec-review-loop)
**Alcance:** diseño, no implementación

---

## 1. Problema

El servicio productivo `rag-del-pueblo` se sirve en la URL autogenerada
`https://rag-del-pueblo-iens6os2ba-uc.a.run.app`. El operador quiere una URL fija y de marca
(`rag-del-pueblo.tsib.dev`) sobre el dominio `tsib.dev` comprado en Squarespace.

Nota aclarada al operador: la URL de **servicio** `.run.app` es estable entre despliegues (lo que
cambia es la URL de **revisión**). El dominio propio resuelve la marca y fija la URL de cara al usuario.

**Objetivo:** mapear `rag-del-pueblo.tsib.dev` → servicio Cloud Run `rag-del-pueblo` (us-central1),
con certificado SSL gestionado por Google, manteniendo la infraestructura bajo Terraform.

---

## 2. Estado actual comprobado

- Servicio Cloud Run v2 `rag-del-pueblo` gestionado por `google_cloud_run_v2_service.app` en
  `infra/terraform/main.tf` (región `us-central1`, `var.region`).
- Build single-origin web+API; la app sirve estáticos y API bajo el mismo origen. La CSP de
  producción (`backend/src/lakehouse/api/security_headers.py`) usa exclusivamente `'self'`
  (`connect-src 'self'`, `base-uri 'self'`, etc.): es agnóstica al host, por lo que **no requiere
  cambios de código ni rebuild** para servirse en un dominio propio. Cookies HttpOnly same-origin
  siguen funcionando (mismo origen).
- Dominio `tsib.dev` comprado en Squarespace; **DNS administrado en Squarespace** (no Cloud DNS).
- Verificación de dominio base `tsib.dev` ya completada en Search Console para la cuenta
  `angeles.ricardo.89@gmail.com` (confirmado con `gcloud domains list-user-verified`).

---

## 3. Alcance y no alcance

### 3.1 Alcance

1. Recurso `google_cloud_run_domain_mapping` para `rag-del-pueblo.tsib.dev` en Terraform.
2. `terraform plan`/`apply` para crear el mapping y exponer los registros DNS generados.
3. Guía de pasos manuales en Squarespace (registros A/AAAA) que ejecuta el operador.
4. Verificación final de que el mapping queda `Ready` y el sitio responde por HTTPS.

### 3.2 No alcance

- No se toca código backend/frontend (no requiere rebuild).
- No se mapea el apex `tsib.dev` (solo el subdominio).
- No se usan certificados propios ni Load Balancer (se descarta: cuesta ~USD 18/mes y rompería el
  costo ~$0 de la demo).
- No se migra el DNS a Cloud DNS; los registros se añaden en Squarespace.

---

## 4. Diseño

### 4.1 Recurso Terraform (`infra/terraform/main.tf`)

Añadir tras el recurso del servicio, con el mismo estilo del repo:

```hcl
resource "google_cloud_run_domain_mapping" "app" {
  name     = "rag-del-pueblo.tsib.dev"
  location = var.region
  metadata {
    namespace = var.project
  }
  spec {
    route_name = google_cloud_run_v2_service.app.name
  }
}
```

Referencias: `location` = `us-central1` (región soportada para domain mappings), `namespace` = id del
proyecto GCP, `route_name` = nombre del servicio (`rag-del-pueblo`).

### 4.2 Flujo operativo

1. Verificar `tsib.dev` en Search Console (dominio base; ya hecho por el operador).
2. `terraform plan` / `terraform apply` → crea el mapping; Cloud Run devuelve `resourceRecords`.
3. Operador: leer los registros DNS del mapping y añadirlos en Squarespace (tipo A/AAAA, host
   `rag-del-pueblo`).
4. Esperar emisión de certificado SSL gestionado (~15 min a 24 h). Cuando el mapping esté `Ready`,
   `https://rag-del-pueblo.tsib.dev` sirve la app; la URL `.run.app` sigue operativa en paralelo.

### 4.3 Obtención de registros DNS

- `gcloud beta run domain-mappings describe --domain rag-del-pueblo.tsib.dev` (sección `resourceRecords`),
  o desde el estado de Terraform tras el apply.

---

## 5. Riesgos y notas

- Cloud Run domain mappings está en **preview/limited availability** (Google no lo recomienda para
  producción). Aceptable para la demo; documentado en el reporte.
- La verificación de `tsib.dev` es **por cuenta**: la cuenta que corre Terraform debe ser la misma que
  verificó el dominio en Search Console (ya es el caso).
- Si el dominio ya estuviera mapeado a otro servicio, habría que usar `--force-override`; no aplica hoy.
- El certificado gestionado no permite restringir TLS 1.0/1.1 ni subir cert propio; limitaciones del
  preview, irrelevantes para la demo.

---

## 6. Criterios de aceptación

1. `terraform plan` muestra `1 to add` (solo el domain mapping), `apply` exitoso.
2. El mapping `rag-del-pueblo.tsib.dev` aparece con registros DNS publicados.
3. Tras añadir los registros en Squarespace y propagarse, el mapping queda en estado `Ready`.
4. `curl -sI https://rag-del-pueblo.tsib.dev` responde 200/HTTPS con cert válido.
5. La app responde igual que en `.run.app` (login, conversaciones, turno del agente).
6. Sin cambios en código; `make security`/gates intactos.
