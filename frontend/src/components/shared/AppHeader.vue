<script setup lang="ts">
import { computed } from 'vue'
import { useObservabilityStore } from '../../stores/observability'
import { useDashboardStore } from '../../stores/dashboard'
import type { ModalCapa } from '../../stores/dashboard'

const obsStore = useObservabilityStore()
const dashboardStore = useDashboardStore()

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

const layerOrder: ModalCapa[] = ['bronze', 'silver', 'gold']

const layerMeta: Record<ModalCapa, { label: string; medalClass: string }> = {
  bronze: {
    label: 'Bronze',
    medalClass: 'bg-gradient-to-br from-amber-50 to-amber-100 border-amber-200 text-amber-700',
  },
  silver: {
    label: 'Silver',
    medalClass: 'bg-gradient-to-br from-stone-100 to-stone-200 border-stone-300 text-stone-500',
  },
  gold: {
    label: 'Gold',
    medalClass: 'bg-gradient-to-br from-yellow-50 to-yellow-100 border-yellow-200 text-yellow-700',
  },
}

function layerData(capa: ModalCapa) {
  const l = obsStore.layers?.layers.find((layer) => layer.capa.toLowerCase() === capa)
  if (!l) return null
  const isError = ['error', 'failed', 'Falló'].includes(l.status)
  const isRunning = ['running', 'En curso'].includes(l.status)
  const chipClass = isError
    ? 'bg-red-50 text-red-700 border-red-200'
    : isRunning
      ? 'bg-blue-50 text-blue-700 border-blue-200'
      : 'bg-green-50 text-green-700 border-green-200'
  return {
    recordsOut: l.records_out,
    chipClass,
    capa,
  }
}

function handleRefresh() {
  obsStore.manualRefresh()
}

function openLayerModal(capa: ModalCapa) {
  dashboardStore.openModal(capa)
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

        <!-- Medallones pipeline -->
        <span class="w-px h-3 bg-stone-300" />
        <div class="flex items-center gap-2">
          <template v-for="(capa, idx) in layerOrder" :key="capa">
            <button
              class="flex items-center gap-1.5 rounded-lg px-2 py-1 border transition-colors hover:opacity-80"
              :class="layerMeta[capa].medalClass"
              @click="openLayerModal(capa)"
              :title="layerMeta[capa].label"
            >
              <!-- Medalla SVG -->
              <svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.5" fill="none" opacity="0.3"/>
                <path d="M12 6l1.5 3.5H17l-3 2.5 1 3.5-3-2-3 2 1-3.5-3-2.5h3.5z" fill="currentColor" opacity="0.8"/>
              </svg>
              <span class="text-[10px] font-semibold">{{ layerMeta[capa].label }}</span>
              <span
                v-if="layerData(capa)"
                class="text-[10px] font-medium px-1.5 py-0.5 rounded-full border"
                :class="layerData(capa)!.chipClass"
              >
                +{{ layerData(capa)!.recordsOut }}
              </span>
            </button>
            <span
              v-if="idx < layerOrder.length - 1"
              class="text-stone-300 text-xs select-none"
            >
              →
            </span>
          </template>
        </div>
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
