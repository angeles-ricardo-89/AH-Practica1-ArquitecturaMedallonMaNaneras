<script setup lang="ts">
import { computed } from 'vue'
import type { LayerRun } from '../../api/observability'

const props = defineProps<{
  layer: LayerRun
}>()

const emit = defineEmits<{
  click: []
}>()

const statusLabel = computed(() => {
  const s = props.layer.status
  if (s === 'running' || s === 'En curso') return 'En curso'
  if (s === 'ok' || s === 'complete' || s === 'Completo') return 'Completo'
  if (s === 'error' || s === 'failed' || s === 'Falló') return 'Falló'
  if (s === 'interrupted') return 'Interrumpido'
  return s || 'sin datos'
})

const statusClass = computed(() => {
  const s = props.layer.status
  if (s === 'running' || s === 'En curso') return 'bg-blue-100 text-blue-700 border-blue-200'
  if (s === 'ok' || s === 'complete' || s === 'Completo') return 'bg-green-100 text-green-700 border-green-200'
  if (s === 'error' || s === 'failed' || s === 'Falló') return 'bg-red-100 text-red-700 border-red-200'
  if (s === 'interrupted') return 'bg-amber-100 text-amber-700 border-amber-200'
  return 'bg-stone-100 text-stone-500 border-stone-200'
})

const duracionFmt = computed(() => {
  const d = props.layer.duracion_seg
  if (d === null || d === undefined) return '—'
  const m = Math.floor(d / 60)
  const s = d % 60
  return `${m}m ${s.toString().padStart(2, '0')}s`
})

const agregados = computed(() => {
  const out = props.layer.records_out
  if (out === null || out === undefined) return '—'
  return `+${out}`
})
</script>

<template>
  <div
    class="bg-white border border-stone-200 rounded-2xl p-4 cursor-pointer hover:border-stone-300 transition-colors"
    @click="emit('click')"
  >
    <div class="flex items-center justify-between mb-2">
      <h3 class="text-sm font-bold text-stone-950">{{ props.layer.capa.charAt(0).toUpperCase() + props.layer.capa.slice(1) }}</h3>
      <span
        class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border"
        :class="statusClass"
      >
        {{ statusLabel }}
      </span>
    </div>

    <p class="text-xs text-stone-500 mb-3">
      <span v-if="props.layer.capa === 'bronze'">Ingesta cruda</span>
      <span v-else-if="props.layer.capa === 'silver'">Validación + limpieza</span>
      <span v-else-if="props.layer.capa === 'gold'">Embeddings + búsqueda vectorial</span>
      <span v-else>{{ props.layer.capa }}</span>
    </p>

    <div class="space-y-1.5 text-xs text-stone-600">
      <div class="flex justify-between gap-2">
        <span class="text-stone-400 font-medium shrink-0">Run ID</span>
        <span
          class="font-mono text-stone-700 truncate max-w-[140px]"
          :title="props.layer.run_id || undefined"
        >
          {{ props.layer.run_id || '—' }}
        </span>
      </div>
      <div class="flex justify-between">
        <span class="text-stone-400 font-medium">Duración</span>
        <span>{{ duracionFmt }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-stone-400 font-medium">Agregados</span>
        <span class="font-semibold text-green-700">{{ agregados }}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-stone-400 font-medium">Cuarentena / RQL</span>
        <span class="font-mono text-stone-700">{{ props.layer.dlq_count ?? 0 }}</span>
      </div>
    </div>
  </div>
</template>
