# Design Spec: Layout fluido proporcional al ancho

**Fecha:** 2026-08-03  
**Scope:** UI — DashboardPage.vue  
**Estado:** Aprobado

---

## Resumen

Permitir que el layout del dashboard ocupe el 100% del ancho de la ventana, con la columna de pipeline fija y las columnas de chat + inspector creciendo/reduciendo proporcionalmente.

---

## Motivación

Actualmente el layout tiene `max-w-[1440px] mx-auto`, lo que deja espacio en blanco en monitores anchos. El usuario quiere aprovechar todo el ancho disponible manteniendo proporciones visuales coherentes.

---

## Cambios

### DashboardPage.vue

| Elemento | Antes | Después | Razón |
|----------|-------|---------|-------|
| Contenedor raíz | `max-w-[1440px] mx-auto w-full` | `w-full` | Ocupa 100% del ancho |
| Chat central | `flex-1 min-w-0` | `flex-[1] min-w-0` | Base proporcional 1.0 |
| Inspector derecha | `w-[282px] shrink-0` | `flex-[0.7] min-w-[280px]` | Base proporcional 0.7 |

**Proporción resultante:** chat:inspector = `1 : 0.7` ≈ **59% : 41%** del espacio restante post-pipeline (300px fijos).

### Invariantes
- Pipeline izquierda: **siempre 300px fijo**, `shrink-0`
- Inspector: **nunca menor a 280px** (`min-w-[280px]`)
- Gap entre columnas: **5 unidades Tailwind** (`gap-5`)
- Padding del contenedor: **6 unidades Tailwind** (`p-6`)

---

## Responsive

En viewports estrechos (< ~900px total):
- El inspector se congela en 280px
- El chat absorbe la compresión restante
- No hay breakpoint de reflow a layout vertical (fuera de scope)

---

## Testing

- Verificar visualmente en viewport 1920x1080
- Verificar visualmente en viewport 1280x720
- Verificar que el inspector nunca baja de 280px
- Verificar que el gráfico 3D se re-dimensiona correctamente al cambiar ancho de columna

---

## Dependencias

Ninguna. Cambio puro de clases CSS/Tailwind.
