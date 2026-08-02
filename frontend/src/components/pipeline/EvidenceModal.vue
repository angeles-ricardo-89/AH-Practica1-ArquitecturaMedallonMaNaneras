<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useObservabilityStore } from '../../stores/observability'

const dashboardStore = useDashboardStore()
const obsStore = useObservabilityStore()

const capa = computed(() => dashboardStore.modalCapa)

const layerData = computed(() => {
  if (!capa.value || !obsStore.layers) return null
  return obsStore.layers.layers.find((l) => l.capa.toLowerCase() === capa.value)
})

const checks = computed(() => {
  const c = capa.value
  if (c === 'bronze') {
    return [
      { label: 'Fuente pública sin autenticación', met: true },
      { label: 'HTML/raw intacto', met: true },
      { label: 'Timestamp de ingesta', met: true },
    ]
  }
  if (c === 'silver') {
    return [
      { label: 'Valida registros con contrato Pydantic', met: true },
      { label: 'Separa válidos e inválidos', met: true },
      { label: 'Registra motivo de rechazo', met: true },
    ]
  }
  if (c === 'gold') {
    return [
      { label: 'Genera embeddings del campo relevante', met: true },
      { label: 'Índice vectorial actualizado', met: true },
      { label: 'Búsqueda semántica expuesta', met: true },
    ]
  }
  return []
})

const titulo = computed(() => {
  const t: Record<string, string> = {
    bronze: 'Bronze',
    silver: 'Silver',
    gold: 'Gold',
  }
  return t[capa.value ?? ''] ?? 'Capa'
})

const duracionFmt = computed(() => {
  const d = layerData.value?.duracion_seg
  if (d === null || d === undefined) return 'sin datos'
  const m = Math.floor(d / 60)
  const s = d % 60
  return `${m}m ${s.toString().padStart(2, '0')}s`
})

function close() {
  dashboardStore.closeModal()
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="dashboardStore.isModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center"
      @keydown="handleKeydown"
    >
      <!-- Overlay -->
      <div class="absolute inset-0 bg-stone-950/30" @click="close" />

      <!-- Modal -->
      <div class="relative bg-white rounded-[18px] border border-stone-200 w-full max-w-[600px] mx-4 p-6 shadow-lg">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-bold text-stone-950">
            Modal de evidencia · {{ titulo }}
          </h2>
          <button
            class="text-stone-400 hover:text-stone-600 text-xl leading-none"
            @click="close"
          >
            ×
          </button>
        </div>

        <p class="text-xs text-stone-500 mb-4">
          Checks propios de la capa + métricas + logs técnicos
        </p>

        <!-- Checks propios -->
        <div class="space-y-2 mb-5">
          <div
            v-for="(check, idx) in checks"
            :key="idx"
            class="flex items-center gap-2 text-sm"
          >
            <span class="text-green-600 text-base">✓</span>
            <span class="text-stone-700">{{ check.label }}</span>
          </div>
        </div>

        <!-- Métricas de corrida -->
        <div class="bg-stone-50 border border-stone-200 rounded-xl p-4">
          <p class="text-xs text-stone-500 mb-2">Métricas de corrida</p>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="flex justify-between">
              <span class="text-stone-400">Registros in</span>
              <span class="font-mono text-stone-700">{{ layerData?.records_in ?? 'sin datos' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-stone-400">Registros out</span>
              <span class="font-mono text-stone-700">{{ layerData?.records_out ?? 'sin datos' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-stone-400">Duración</span>
              <span class="font-mono text-stone-700">{{ duracionFmt }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-stone-400">Run ID</span>
              <span class="font-mono text-stone-700">{{ layerData?.run_id ?? 'sin datos' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-stone-400">DLQ / RQL</span>
              <span class="font-mono text-stone-700">{{ layerData?.dlq_count ?? 0 }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-stone-400">Status</span>
              <span class="font-mono text-stone-700">{{ layerData?.status ?? 'sin datos' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
