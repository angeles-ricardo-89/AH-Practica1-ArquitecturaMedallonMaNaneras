# UI — Colores de Clusters Persistentes y Filtrado 3D por Fuente

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modificar la UI del Dashboard para que los colores de clusters sean persistentes en sesión, la gráfica 3D muestre solo los chunks de la respuesta seleccionada, y el click fuera/nueva pregunta deseleccionen la respuesta activa.

**Architecture:** Se modifica el store `dashboard.ts` para persistir colores de clusters en un `Map` durante la sesión. Se refactoriza `Embeddings3D.vue` para ser un componente "tonto" que solo renderiza los puntos que recibe. Se añade lógica de filtrado en `DashboardPage.vue` mediante un `computed` que decide entre el universo completo (cacheado) o los chunks de la respuesta seleccionada. Se añaden eventos de click en `ChatWindow.vue` y `ResponseCard.vue` para manejar selección/deselección.

**Tech Stack:** Vue 3 (Composition API), Pinia, TypeScript, ECharts 3D, Tailwind CSS

---

## Archivos Afectados

| File | Responsibility |
|---|---|
| `frontend/src/stores/dashboard.ts` | Estado de colores persistentes, getter de color por cluster, fetchClusters con preservación |
| `frontend/src/components/inspector/Embeddings3D.vue` | Renderizado de puntos 3D, leyenda adaptativa, eliminar lógica de highlightedChunks |
| `frontend/src/components/dashboard/DashboardPage.vue` | Cálculo de `visiblePoints`, cache de `embeddingsPoints`, binding al 3D |
| `frontend/src/components/chat/ResponseCard.vue` | `@click.stop` en tarjeta asistente |
| `frontend/src/components/chat/ChatWindow.vue` | Deselección en submit, `@click.self` en contenedor de mensajes |

---

### Task 1: Colores Persistentes de Clusters en `dashboard.ts`

**Files:**
- Modify: `frontend/src/stores/dashboard.ts`
- Test: manual (verificar en navegador que colores no cambian)

- [ ] **Step 1: Reemplazar `clusterColorMap` por `sessionClusterColors`**

Eliminar `clusterColorMap` (computed) y añadir:

```typescript
const sessionClusterColors = ref<Map<number, string>>(new Map())

const PALETTE = [
  '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]

function getClusterColor(clusterId: number): string {
  return sessionClusterColors.value.get(clusterId) ?? '#A8A29E'
}
```

- [ ] **Step 2: Modificar `fetchClusters` para preservar colores**

Reemplazar el cuerpo de `fetchClusters`:

```typescript
async function fetchClusters() {
  try {
    const data = await getClustersLatest()
    clusterData.value = data
    clusterError.value = null

    // Preservar colores existentes, asignar nuevos
    for (const cluster of data.clusters) {
      if (!sessionClusterColors.value.has(cluster.cluster_id)) {
        const color = PALETTE[cluster.cluster_id % PALETTE.length]
        sessionClusterColors.value.set(cluster.cluster_id, color!)
      }
    }
  } catch (err) {
    clusterError.value = err instanceof Error ? err.message : 'Error al obtener clusters'
  }
}
```

- [ ] **Step 3: Actualizar el return del store**

En el objeto return, reemplazar `clusterColorMap` por:

```typescript
sessionClusterColors,
getClusterColor,
```

- [ ] **Step 4: Verificar typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: No errors in `dashboard.ts`.

---

### Task 2: Refactorizar `Embeddings3D.vue` para Recibir Puntos Filtrados

**Files:**
- Modify: `frontend/src/components/inspector/Embeddings3D.vue`
- Test: manual (verificar renderizado en navegador)

- [ ] **Step 1: Actualizar props**

Reemplazar las props actuales por:

```typescript
const props = defineProps<{
  points: Embedding3DPoint[]
  mode: 'full' | 'filtered'
}>()
```

Eliminar `highlightedChunks`.

- [ ] **Step 2: Eliminar computed `chartData` existente y reescribir**

Reemplazar todo el bloque `chartData` por:

```typescript
const noiseColor = 'rgba(168, 162, 158, 0.3)'

const chartData = computed(() => {
  return props.points.map((p) => {
    const cp = clusterPointMap.value.get(p.chunk_key)

    let color: string
    let opacity: number
    let size: number

    if (props.mode === 'filtered') {
      // Modo filtrado: colores de cluster, siempre visibles
      if (cp && cp.cluster_id >= 0) {
        color = dashboardStore.getClusterColor(cp.cluster_id)
        opacity = 1.0
      } else if (cp && cp.cluster_id === -1) {
        color = noiseColor
        opacity = 0.5
      } else {
        color = '#A8A29E'
        opacity = 1.0
      }
      size = 8
    } else {
      // Modo full: comportamiento original
      if (cp) {
        if (cp.cluster_id === -1) {
          color = noiseColor
          opacity = 0.3
        } else {
          color = dashboardStore.getClusterColor(cp.cluster_id)
          opacity = 0.7
        }
      } else {
        color = '#A8A29E'
        opacity = 0.6
      }
      size = 6
    }

    let name = p.chunk_key
    if (cp && cp.cluster_id >= 0) {
      const label = dashboardStore.clusterData?.clusters.find(c => c.cluster_id === cp.cluster_id)?.label
      name = label ? `${label} (${cp.pertenencia.toFixed(2)})` : `Cluster ${cp.cluster_id} (${cp.pertenencia.toFixed(2)})`
    } else if (cp && cp.cluster_id === -1) {
      name = 'Ruido'
    }

    return {
      value: [p.x, p.y, p.z],
      itemStyle: { color, opacity },
      symbolSize: size,
      name,
    }
  })
})
```

Nota: `symbolSize` debe ir en el objeto de data de serie o en `itemStyle`. En ECharts 3D, `symbolSize` se define en el nivel de serie o en cada data point. Aquí lo ponemos en cada data point.

- [ ] **Step 3: Actualizar `updateChart` para usar `symbolSize` dinámico**

En `updateChart`, en el objeto `series`:

```typescript
series: [{
  type: 'scatter3D',
  data: chartData.value,
  symbolSize: 6, // fallback, pero cada punto puede sobreescribir
  itemStyle: { borderWidth: 0 },
  emphasis: { itemStyle: { color: '#7F1D1D' } },
}],
```

En realidad, `symbolSize` en ECharts puede ser una función o un valor por punto. Si ponemos `symbolSize` en cada punto del data array, ECharts lo respeta. Verificar en la documentación que `symbolSize` en cada punto funciona para `scatter3D`. Si no, usar una función:

```typescript
symbolSize: (data: any, params: any) => {
  return chartData.value[params?.dataIndex]?.symbolSize ?? 6
},
```

Pero por simplicidad, podemos dejar `symbolSize: 6` en la serie y usar `itemStyle` para el resto. El tamaño 8 en modo filtered es un nice-to-have; si ECharts 3D no lo soporta fácilmente, omitir el cambio de tamaño.

- [ ] **Step 4: Leyenda adaptativa**

Reemplazar el bloque de leyenda del template por:

```vue
<div class="flex items-center gap-3 mt-2 text-[10px] text-stone-500 flex-wrap">
  <template v-if="mode === 'full'">
    <div class="flex items-center gap-1">
      <span class="w-2 h-2 rounded-full bg-stone-400" />
      <span>chunks neutros</span>
    </div>
    <div class="flex items-center gap-1">
      <span class="w-2 h-2 rounded-full bg-red-900" />
      <span>chunks citados</span>
    </div>
    <div v-if="dashboardStore.clusterData && dashboardStore.clusterData.noise_count > 0" class="flex items-center gap-1">
      <span class="w-2 h-2 rounded-full opacity-30" style="background-color: rgba(168, 162, 158, 0.3);" />
      <span>ruido ({{ dashboardStore.clusterData.noise_count }})</span>
    </div>
  </template>
  <template v-else>
    <div
      v-for="cluster in visibleClusters"
      :key="cluster.cluster_id"
      class="flex items-center gap-1"
    >
      <span class="w-2 h-2 rounded-full" :style="{ backgroundColor: dashboardStore.getClusterColor(cluster.cluster_id) }" />
      <span>{{ cluster.label || `Cluster ${cluster.cluster_id}` }}</span>
    </div>
    <div v-if="visibleNoiseCount > 0" class="flex items-center gap-1">
      <span class="w-2 h-2 rounded-full opacity-30" style="background-color: rgba(168, 162, 158, 0.3);" />
      <span>ruido ({{ visibleNoiseCount }})</span>
    </div>
  </template>
</div>
```

- [ ] **Step 5: Añadir computed `visibleClusters` y `visibleNoiseCount`**

```typescript
const visibleClusters = computed(() => {
  if (props.mode !== 'filtered' || !dashboardStore.clusterData) return []
  const presentIds = new Set<number>()
  for (const p of props.points) {
    const cp = clusterPointMap.value.get(p.chunk_key)
    if (cp && cp.cluster_id >= 0) {
      presentIds.add(cp.cluster_id)
    }
  }
  return dashboardStore.clusterData.clusters.filter(c => presentIds.has(c.cluster_id))
})

const visibleNoiseCount = computed(() => {
  if (props.mode !== 'filtered') return 0
  return props.points.filter(p => {
    const cp = clusterPointMap.value.get(p.chunk_key)
    return cp && cp.cluster_id === -1
  }).length
})
```

- [ ] **Step 6: Actualizar watchers**

Eliminar `watch(() => props.highlightedChunks, ...)` y asegurar que solo hay:

```typescript
watch(() => props.points, updateChart, { deep: true })
watch(() => props.mode, updateChart)
watch(() => dashboardStore.clusterData, updateChart, { deep: true })
```

- [ ] **Step 7: Verificar typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: No errors.

---

### Task 3: Lógica de Puntos Visibles en `DashboardPage.vue`

**Files:**
- Modify: `frontend/src/components/dashboard/DashboardPage.vue`
- Test: manual (verificar comportamiento en navegador)

- [ ] **Step 1: Eliminar `highlightedChunks` computed**

Eliminar:

```typescript
const highlightedChunks = computed(() => {
  if (!selectedSources.value.length) return []
  return selectedSources.value
    .map((s) => s.conference_id)
    .filter(Boolean)
})
```

- [ ] **Step 2: Añadir `visiblePoints` y `chartMode` computed**

Añadir después de `selectedSources`:

```typescript
const chartMode = computed(() => {
  return dashboardStore.selectedResponseId ? 'filtered' : 'full'
})

const visiblePoints = computed(() => {
  if (!dashboardStore.selectedResponseId) {
    return embeddingsPoints.value
  }
  const pts: Embedding3DPoint[] = []
  for (const src of selectedSources.value) {
    if (src.embedding_3d && src.embedding_3d.length === 3) {
      pts.push({
        chunk_key: src.conference_id,
        x: src.embedding_3d[0],
        y: src.embedding_3d[1],
        z: src.embedding_3d[2],
        conference_date: src.conference_date,
      })
    }
  }
  return pts
})
```

- [ ] **Step 3: Actualizar binding de `Embeddings3D`**

Reemplazar:

```vue
<Embeddings3D
  v-else
  :points="embeddingsPoints"
  :highlighted-chunks="highlightedChunks"
  class="shrink-0"
/>
```

Por:

```vue
<Embeddings3D
  v-else
  :points="visiblePoints"
  :mode="chartMode"
  class="shrink-0"
/>
```

- [ ] **Step 4: Verificar typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: No errors.

---

### Task 4: Eventos de Selección en `ResponseCard.vue`

**Files:**
- Modify: `frontend/src/components/chat/ResponseCard.vue`
- Test: manual (verificar click en navegador)

- [ ] **Step 1: Añadir `@click.stop` en tarjeta asistente**

En el div raíz de la tarjeta asistente (el que tiene `v-else` y las clases dinámicas de borde), añadir:

```vue
@click.stop="handleClick"
```

El div ya tiene `@click="handleClick"` implícito? No, actualmente no tiene ningún `@click` en el div raíz de la tarjeta. Solo existe `handleClick` que se llama... espera, revisando el código actual de `ResponseCard.vue`:

```vue
<div
  v-else
  class="max-w-[90%] w-full bg-white border rounded-2xl px-4 py-4 cursor-pointer transition-all"
  :class="isSelected..."
>
```

No tiene `@click`. Pero `handleClick` está definido y nunca se usa. Esto es un bug existente. Debemos añadir `@click.stop="handleClick"` al div raíz de la tarjeta asistente.

- [ ] **Step 2: Verificar que el div raíz tenga el evento**

Código final del div raíz asistente:

```vue
<div
  v-else
  class="max-w-[90%] w-full bg-white border rounded-2xl px-4 py-4 cursor-pointer transition-all"
  :class="isSelected
    ? 'border-red-900 ring-1 ring-red-900'
    : 'border-stone-200 hover:border-stone-300'"
  @click.stop="handleClick"
>
```

- [ ] **Step 3: Verificar typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: No errors.

---

### Task 5: Deselección en `ChatWindow.vue`

**Files:**
- Modify: `frontend/src/components/chat/ChatWindow.vue`
- Test: manual (verificar en navegador)

- [ ] **Step 1: Deseleccionar al enviar pregunta**

En `handleSubmit`, añadir antes de `store.sendMessage`:

```typescript
async function handleSubmit() {
  const query = input.value.trim()
  if (!query) return
  input.value = ''
  dashboardStore.selectResponse(null) // NUEVO
  await store.sendMessage(query)
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}
```

- [ ] **Step 2: Añadir `@click.self` en contenedor de mensajes**

En el div con `ref="messagesContainer"`, añadir:

```vue
@click.self="dashboardStore.selectResponse(null)"
```

El div actual es:

```vue
<div
  ref="messagesContainer"
  class="flex-1 overflow-y-auto space-y-4 p-4"
>
```

Cambiar a:

```vue
<div
  ref="messagesContainer"
  class="flex-1 overflow-y-auto space-y-4 p-4"
  @click.self="dashboardStore.selectResponse(null)"
>
```

- [ ] **Step 3: Verificar typecheck**

Run:
```bash
cd frontend && pnpm typecheck
```
Expected: No errors.

- [ ] **Step 4: Verificar lint**

Run:
```bash
cd frontend && pnpm lint
```
Expected: No errors.

---

### Task 6: Verificación Integral en Navegador

**Files:** N/A (manual verification)

- [ ] **Step 1: Levantar stack**

```bash
docker compose up -d
```

- [ ] **Step 2: Abrir dashboard**

Navegar a `http://localhost:5173` (o el puerto correspondiente del frontend).

- [ ] **Step 3: Verificar colores persistentes**

1. Cargar página.
2. Observar colores de clusters en la gráfica 3D.
3. Esperar a que el polling de clusters se ejecute (o recargar datos manualmente si hay un botón).
4. Verificar que los puntos de cada cluster mantienen el mismo color.

- [ ] **Step 4: Verificar filtrado 3D por respuesta**

1. Enviar una pregunta en el chat.
2. Hacer click en la respuesta del asistente.
3. Verificar que:
   - La gráfica 3D muestra **solo** los puntos correspondientes a las fuentes de esa respuesta.
   - Cada punto tiene el color de su cluster.
   - La leyenda muestra los clusters presentes (no la leyenda de "chunks neutros/citados").
   - `SourcesList` muestra las fuentes correspondientes.

- [ ] **Step 5: Verificar click fuera**

1. Con una respuesta seleccionada, hacer click en el fondo del área de mensajes (entre tarjetas, o en el espacio vacío debajo del último mensaje).
2. Verificar que:
   - La respuesta se deselecciona.
   - La gráfica 3D vuelve a mostrar el universo completo.
   - La leyenda vuelve a modo `full`.
   - `SourcesList` muestra el mensaje "Selecciona una respuesta...".

- [ ] **Step 6: Verificar auto-deselect al enviar pregunta**

1. Seleccionar una respuesta.
2. Escribir una nueva pregunta y enviar.
3. Verificar que la respuesta anterior se deselecciona automáticamente antes de que llegue la nueva respuesta.

- [ ] **Step 7: Verificar cache del universo**

1. Abrir DevTools → Network.
2. Seleccionar una respuesta, luego deseleccionar.
3. Verificar que no hay nuevas peticiones a `/embeddings/3d` al deseleccionar.

---

## Spec Coverage Check

| Spec Section | Task(s) que lo implementan |
|---|---|
| 1.1 Estado `sessionClusterColors` | Task 1, Step 1 |
| 1.2 Lógica de asignación/preservación | Task 1, Step 2 |
| 1.3 Getter `getClusterColor` | Task 1, Step 1 |
| 2.1 Props `points` y `mode` en Embeddings3D | Task 2, Step 1 |
| 2.2 `visiblePoints` computed | Task 3, Step 2 |
| 2.3 Lookup de cluster por chunk_key | Task 2, Step 2 (usa `clusterPointMap` existente) |
| 2.4 Estilo en modo filtered vs full | Task 2, Step 2 |
| 2.5 Leyenda adaptativa | Task 2, Steps 4-5 |
| 3.1 `@click.stop` en ResponseCard | Task 4, Step 1 |
| 3.2 `@click.self` en ChatWindow | Task 5, Step 2 |
| 4. Auto-deselect en submit | Task 5, Step 1 |
| 5. Cache del universo | Task 3 (visiblePoints usa embeddingsPoints.value directamente) |

## Placeholder Scan

- No hay TBDs, TODOs, o referencias a "implementar luego".
- No hay referencias a funciones no definidas.
- Todos los pasos incluyen código o comandos concretos.

## Type Consistency Check

- `sessionClusterColors` es `ref<Map<number, string>>` en Task 1.
- `getClusterColor` recibe `number` y devuelve `string`.
- `Embeddings3D` recibe `points: Embedding3DPoint[]` y `mode: 'full' | 'filtered'`.
- `visiblePoints` devuelve `Embedding3DPoint[]`.
- `chartMode` devuelve `'full' | 'filtered'`.
- Todo consistente entre tasks.

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-03-ui-clusters-3d-filtrado.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach?