# Spec: UI — Colores de Clusters Persistentes y Filtrado 3D por Fuente

**Versión:** 1.0  
**Fecha:** 2026-08-03  
**Estado:** Aprobada por usuario

## Resumen

Cambios en la UI del Dashboard para:
1. Asignar colores a clusters de forma determinista y preservarlos durante toda la sesión.
2. Mostrar en la gráfica 3D **únicamente** los chunks citados por una respuesta seleccionada, con su color y etiqueta de cluster.
3. Deseleccionar respuesta al hacer click fuera de una tarjeta, o al enviar una nueva pregunta.
4. Cachear el universo completo de chunks en el frontend para evitar re-fetches innecesarios.

## Motivación

Actualmente, los colores de cluster se recalculan cada vez que llegan datos nuevos del backend, provocando que los puntos "saltan" de color. Además, al seleccionar una respuesta, la gráfica resalta **todos** los chunks citados en rojo (#7F1D1D), perdiendo la información visual de cluster. Se requiere que la gráfica muestre exclusivamente los chunks de la respuesta seleccionada, con su color y etiqueta correspondiente, para que el usuario identifique inmediatamente a qué cluster pertenece cada fuente usada.

## Alcance

**Incluido:**
- Store `dashboard.ts`: colores de sesión, estado de selección.
- Componente `Embeddings3D.vue`: recibir puntos filtrados, mostrar colores y etiquetas.
- Componente `ResponseCard.vue`: emitir selección sin propagar click al contenedor.
- Componente `ChatWindow.vue`: deseleccionar al enviar pregunta; click en contenedor deselecciona.
- Componente `DashboardPage.vue`: calcular puntos visibles, cache de universo.

**Excluido:**
- Cambios en el backend (`SourceChunk` ya incluye `embedding_3d` y `cluster_id`).
- Nuevos endpoints o schemas.

## Diseño Detallado

### 1. Colores de Clusters Persistentes en Sesión

#### 1.1 Estado

En `frontend/src/stores/dashboard.ts`:

- Reemplazar `clusterColorMap` (computed) por `sessionClusterColors: ref<Map<number, string>>`.
- Inicializar como `new Map()`.

#### 1.2 Lógica de Asignación

Al llegar `clusterData` (ya sea en `fetchClusters()` o en cualquier otro futuro refetch):

```
PARA cada cluster en clusterData.clusters:
  SI sessionClusterColors NO tiene cluster.cluster_id:
    color = palette[cluster.cluster_id % palette.length]
    sessionClusterColors.set(cluster.cluster_id, color)
```

La paleta es la misma de 10 colores actual:
```
['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
 '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
```

#### 1.3 Getter de Color

Añadir función `getClusterColor(clusterId: number): string` que devuelva el color de `sessionClusterColors` o un color fallback (`#A8A29E`) si no existe.

#### 1.4 Impacto en Componentes

- `Embeddings3D.vue` deja de usar `dashboardStore.clusterColorMap` y usa `dashboardStore.getClusterColor()`.
- `SourcesList.vue` puede usar el color del cluster para el badge (opcional, fuera de scope actual).

### 2. Gráfica 3D: Mostrar Solo Chunks de Respuesta Seleccionada

#### 2.1 Cambio en `Embeddings3D.vue`

- Eliminar prop `highlightedChunks: string[]`.
- Añadir prop `points: Embedding3DPoint[]` (puntos a renderizar, ya filtrados o completos).
- Añadir prop opcional `mode: 'full' | 'filtered' = 'full'` para decidir qué leyenda mostrar.
- El componente **no calcula** qué mostrar; solo renderiza lo que recibe.

#### 2.2 Cálculo de Puntos Visibles en `DashboardPage.vue`

Nuevo `computed` `visiblePoints`:

```typescript
const visiblePoints = computed(() => {
  if (!dashboardStore.selectedResponseId) {
    // Sin selección: universo completo
    return embeddingsPoints.value
  }
  // Con selección: construir puntos 3D desde selectedSources
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

#### 2.3 Datos de Cluster en Modo Filtrado

`Embeddings3D.vue` necesita `cluster_id` y `pertenencia` para cada punto en modo filtrado. Opciones:

**Opción A (recomendada):** El backend ya incluye `cluster_id` en `SourceChunk`. Añadimos `cluster_id` al tipo `Embedding3DPoint` o usamos un tipo interno con `cluster_id` opcional.

**Opción B:** Lookup en `dashboardStore.clusterData.points` por `chunk_key`.

Se adopta **Opción B** para no modificar schemas del backend.

En `Embeddings3D.vue`, para cada punto recibido:
```typescript
const cp = clusterPointMap.value.get(p.chunk_key)
```

Donde `clusterPointMap` ya existe y se construye desde `dashboardStore.clusterData.points`.

#### 2.4 Estilo en Modo Filtrado

Para cada punto:
- Color: `dashboardStore.getClusterColor(cp.cluster_id)` si `cp` existe, else neutro.
- Opacidad: `1.0` (siempre visibles en modo filtrado).
- Nombre: label del cluster + pertenencia (igual que ahora).
- Tamaño: `8` (ligeramente mayor para destacar).

En modo `full`:
- Mantener comportamiento actual: noise a 0.3 opacidad, clusters a 0.7, neutros a 0.6.

#### 2.5 Leyenda Adaptativa

- Modo `full`: leyenda actual (neutros, citados, ruido).
- Modo `filtered`: leyenda con los clusters presentes en la selección + color de cada uno.

### 3. Click Fuera Deselecciona

#### 3.1 `ResponseCard.vue`

En el div raíz de la tarjeta asistente:
```vue
@click.stop="handleClick"
```

Así, el click no llega al contenedor padre.

#### 3.2 `ChatWindow.vue`

En el contenedor de mensajes (el div con `ref="messagesContainer"`):
```vue
@click.self="dashboardStore.selectResponse(null)"
```

Esto garantiza que solo clicks **directamente** en el fondo del contenedor deseleccionan, no clicks en tarjetas (que tienen `.stop`) ni en botones internos.

### 4. Auto-Deselect al Enviar Pregunta

En `ChatWindow.vue`, `handleSubmit`:
```typescript
async function handleSubmit() {
  const query = input.value.trim()
  if (!query) return
  input.value = ''
  dashboardStore.selectResponse(null) // <-- NUEVO
  await store.sendMessage(query)
  // ... scroll
}
```

### 5. Cache del Universo de Chunks

`embeddingsPoints` en `DashboardPage.vue` es un `ref<Embedding3DPoint[]>` que solo se pobla en `onMounted` mediante `fetchEmbeddings()`. No se re-fetchea nunca salvo recarga de página.

Al deseleccionar (`selectedResponseId = null`), `visiblePoints` devuelve `embeddingsPoints.value` directamente, sin nueva petición de red.

## Edge Cases

| Escenario | Comportamiento |
|---|---|
| `SourceChunk` sin `embedding_3d` | No aparece en la gráfica 3D; sí en SourcesList. |
| `SourceChunk` sin `cluster_id` | Aparece en gráfica con color neutro y sin etiqueta de cluster. |
| Respuesta seleccionada pero sources vacíos | Gráfica 3D muestra 0 puntos; SourcesList vacío. |
| Click en user message | No hace nada (solo asistentes son seleccionables). |
| Click en botón "Detalle técnico" dentro de ResponseCard | `.stopPropagation()` ya está presente en `@click` del botón; no afecta. |
| Re-fetch de clusters mientras hay selección | Colores de clusters existentes se preservan; nuevos clusters obtienen color nuevo. |

## Archivos Modificados

| Archivo | Cambio |
|---|---|
| `frontend/src/stores/dashboard.ts` | `sessionClusterColors`, `getClusterColor()`, preservación de colores en `fetchClusters` |
| `frontend/src/components/inspector/Embeddings3D.vue` | Recibir `points` y `mode`, eliminar `highlightedChunks`, leyenda adaptativa |
| `frontend/src/components/dashboard/DashboardPage.vue` | `visiblePoints` computed, cache de `embeddingsPoints`, pasar `visiblePoints` y `mode` al 3D |
| `frontend/src/components/chat/ResponseCard.vue` | `@click.stop` en tarjeta asistente |
| `frontend/src/components/chat/ChatWindow.vue` | `selectResponse(null)` en submit; `@click.self` en contenedor de mensajes |

## Criterios de Aceptación

- [ ] Los colores de cluster no cambian al hacer re-fetch de clusters.
- [ ] Al seleccionar una respuesta, la gráfica 3D muestra **solo** los chunks de sus sources, con color y etiqueta de cluster.
- [ ] Al hacer click en el fondo del chat (no en una tarjeta), se deselecciona la respuesta y la gráfica vuelve al universo completo.
- [ ] Al enviar una nueva pregunta, se deselecciona automáticamente.
- [ ] No se hacen peticiones de red adicionales al deseleccionar.
- [ ] `pnpm typecheck` pasa sin errores.
- [ ] `pnpm lint` pasa sin errores.

## Dependencias

- Backend ya expone `embedding_3d` y `cluster_id` en `SourceChunk` (confirmado en `backend/src/lakehouse/schemas/chat.py`).
- Componente `Embeddings3D.vue` ya usa `echarts` y `echarts-gl`.

## Notas de Implementación

- No se modifica el backend.
- No se añaden nuevas dependencias npm.
- El estado `selectedResponseId` sigue siendo un `string | null`; al seleccionar otra respuesta, simplemente se sobreescribe (comportamiento actual, ya preservado).
