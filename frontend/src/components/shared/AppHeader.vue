<script setup lang="ts">
import { computed } from 'vue'
import { useObservabilityStore } from '../../stores/observability'

const obsStore = useObservabilityStore()

const ambiente = computed(() => obsStore.config?.ambiente ?? 'sin datos')
const version = computed(() => obsStore.config?.version ?? 'sin datos')
const ultimaCorrida = computed(() => {
  if (obsStore.layers?.ultima_corrida_global) {
    return obsStore.layers.ultima_corrida_global
  }
  return 'sin datos'
})

const health = computed(() => {
  const h = obsStore.layers?.health_global ?? 'sin datos'
  if (h === 'Healthy') return { label: 'Healthy', class: 'bg-green-100 text-green-700 border-green-200' }
  if (h === 'Degraded') return { label: 'Degraded', class: 'bg-amber-100 text-amber-700 border-amber-200' }
  if (h === 'Failed') return { label: 'Failed', class: 'bg-red-100 text-red-700 border-red-200' }
  return { label: h, class: 'bg-stone-100 text-stone-500 border-stone-200' }
})

function handleRefresh() {
  obsStore.manualRefresh()
}
</script>

<template>
  <header class="h-16 bg-white border border-stone-200 rounded-2xl px-6 flex items-center justify-between shrink-0">
    <div class="flex items-center gap-6">
      <div>
        <h1 class="text-base font-bold text-stone-950">Dashboard técnico</h1>
        <p class="text-xs text-stone-500">pipeline · RAG · fuentes · embeddings</p>
      </div>

      <div class="hidden md:flex items-center gap-3 text-xs">
        <span class="text-stone-500">
          <span class="font-semibold text-stone-700">Ambiente:</span> {{ ambiente }}
        </span>
        <span class="w-px h-3 bg-stone-300" />
        <span class="text-stone-500">
          <span class="font-semibold text-stone-700">App</span> {{ version }}
        </span>
        <span class="w-px h-3 bg-stone-300" />
        <span
          class="text-stone-500 truncate max-w-[200px]"
          :title="ultimaCorrida"
        >
          <span class="font-semibold text-stone-700">Última corrida:</span> {{ ultimaCorrida }}
        </span>
        <span class="w-px h-3 bg-stone-300" />
        <span
          class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border"
          :class="health.class"
        >
          {{ health.label }}
        </span>
      </div>
    </div>

    <div class="flex items-center gap-3">
      <span class="text-xs text-stone-400 bg-stone-50 px-2 py-1 rounded-full border border-stone-200">
        Auto-refresh 30s
      </span>
      <button
        class="bg-red-900 hover:bg-red-800 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
        @click="handleRefresh"
      >
        Refresh
      </button>
    </div>
  </header>
</template>
