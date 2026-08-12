# Layout Fluido Proporcional al Ancho — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que el dashboard ocupe el 100% del ancho disponible, con columna de pipeline fija y chat + inspector creciendo proporcionalmente.

**Architecture:** Ajuste puro de clases Tailwind en DashboardPage.vue. Flexbox con `flex-[1]` para chat y `flex-[0.7]` para inspector, manteniendo pipeline en `w-[300px] shrink-0`.

**Tech Stack:** Vue 3, Tailwind CSS

---

### Task 1: Ajustar clases del layout en DashboardPage.vue

**Files:**
- Modify: `frontend/src/components/dashboard/DashboardPage.vue:85-114`

- [ ] **Step 1: Eliminar `max-w-[1440px] mx-auto` del contenedor raíz**

```html
<!-- Antes -->
<div class="max-w-[1440px] mx-auto w-full flex flex-col gap-5 h-full">

<!-- Después -->
<div class="w-full flex flex-col gap-5 h-full">
```

- [ ] **Step 2: Cambiar chat central a proporcional**

```html
<!-- Antes -->
<div ref="chatAreaRef" class="flex-1 min-w-0 overflow-hidden">

<!-- Después -->
<div ref="chatAreaRef" class="flex-[1] min-w-0 overflow-hidden">
```

- [ ] **Step 3: Cambiar inspector derecho a proporcional con min-width**

```html
<!-- Antes -->
<div class="w-[282px] shrink-0 flex flex-col gap-4 overflow-hidden">

<!-- Después -->
<div class="flex-[0.7] min-w-[280px] flex flex-col gap-4 overflow-hidden">
```

- [ ] **Step 4: Verificar typecheck y lint**

Run:
```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: PASS (no errores, solo cambios de clase CSS)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/DashboardPage.vue
git commit -m "feat: layout fluido proporcional al ancho de pantalla"
```

---

### Task 2: Verificación visual

**Files:**
- Ninguno — verificación manual del comportamiento

- [ ] **Step 1: Verificar en viewport ancho (1920px+)**

Abrir el dashboard en un navegador con ventana maximizada. Confirmar:
- Layout ocupa todo el ancho sin márgenes laterales blancos
- Pipeline izquierda mide exactamente 300px
- Chat e inspector ocupan el espacio restante en proporción ~59:41
- No hay overflow horizontal

- [ ] **Step 2: Verificar en viewport medio (1280px)**

Redimensionar ventana a ~1280px. Confirmar:
- Inspector no baja de 280px de ancho
- Chat se comprime apropiadamente
- No hay truncamiento de contenido en header

- [ ] **Step 3: Verificar que gráfico 3D se re-dimensiona**

Seleccionar una respuesta del chat para activar el gráfico 3D. Confirmar que al redimensionar la ventana, el canvas 3D se adapta al nuevo ancho de la columna del inspector.

---

## Self-Review Checklist

**Spec coverage:**
- [x] Quitar `max-w-[1440px] mx-auto` → Task 1, Step 1
- [x] Pipeline fija 300px → sin cambios (ya existía)
- [x] Chat proporcional `flex-[1]` → Task 1, Step 2
- [x] Inspector proporcional `flex-[0.7] min-w-[280px]` → Task 1, Step 3
- [x] Verificación visual en distintos viewports → Task 2

**Placeholder scan:**
- [x] Sin TBD/TODO
- [x] Sin referencias ambiguas
- [x] Código completo en cada step

**Type consistency:**
- [x] Solo cambios de clases Tailwind, sin tipos involucrados
