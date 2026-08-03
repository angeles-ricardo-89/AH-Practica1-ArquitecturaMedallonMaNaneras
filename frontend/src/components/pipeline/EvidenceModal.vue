<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useObservabilityStore } from '../../stores/observability'
import type { LayerRun } from '../../api/observability'

const dashboardStore = useDashboardStore()
const obsStore = useObservabilityStore()

const activeTab = ref<'metrics' | 'history'>('metrics')

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

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  try {
    const d = new Date(value)
    return d.toLocaleString('es-MX', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return value
  }
}

function statusLabel(s: string): string {
  if (s === 'running' || s === 'En curso') return 'En curso'
  if (s === 'ok' || s === 'complete' || s === 'Completo') return 'Completo'
  if (s === 'error' || s === 'failed' || s === 'Falló') return 'Falló'
  if (s === 'interrupted') return 'Interrumpido'
  return s || 'sin datos'
}

function statusClass(s: string): string {
  if (s === 'running' || s === 'En curso') return 'bg-blue-100 text-blue-700 border-blue-200'
  if (s === 'ok' || s === 'complete' || s === 'Completo') return 'bg-green-100 text-green-700 border-green-200'
  if (s === 'error' || s === 'failed' || s === 'Falló') return 'bg-red-100 text-red-700 border-red-200'
  if (s === 'interrupted') return 'bg-amber-100 text-amber-700 border-amber-200'
  return 'bg-stone-100 text-stone-500 border-stone-200'
}

const historyRuns = computed<LayerRun[]>(() => {
  return obsStore.layerHistory?.runs ?? []
})

watch(
  () => dashboardStore.isModalOpen,
  (open) => {
    if (open && capa.value) {
      activeTab.value = 'metrics'
      obsStore.fetchLayerHistory(capa.value)
    }
  },
)
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
      <div class="relative bg-white rounded-[18px] border border-stone-200 w-full max-w-[700px] mx-4 p-6 shadow-lg flex flex-col max-h-[85vh]">
        <div class="flex items-center justify-between mb-4 shrink-0">
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

        <!-- Tabs -->
        <div class="flex gap-1 mb-4 border-b border-stone-200 shrink-0">
          <button
            class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors"
            :class="activeTab === 'metrics'
              ? 'text-stone-950 bg-stone-100 border-b-2 border-red-900'
              : 'text-stone-500 hover:text-stone-700 hover:bg-stone-50'"
            @click="activeTab = 'metrics'"
          >
            Checks y métricas
          </button>
          <button
            class="px-4 py-2 text-sm font-medium rounded-t-lg transition-colors"
            :class="activeTab === 'history'
              ? 'text-stone-950 bg-stone-100 border-b-2 border-red-900'
              : 'text-stone-500 hover:text-stone-700 hover:bg-stone-50'"
            @click="activeTab = 'history'"
          >
            Histórico de corridas
          </button>
        </div>

        <!-- Tab 1: Checks y métricas -->
        <div v-if="activeTab === 'metrics'" class="overflow-y-auto">
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
              <div class="flex justify-between gap-2">
                <span class="text-stone-400 shrink-0">Run ID</span>
                <span
                  class="font-mono text-stone-700 truncate max-w-[200px]"
                  :title="layerData?.run_id ?? undefined"
                >
                  {{ layerData?.run_id ?? 'sin datos' }}
                </span>
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

        <!-- Tab 2: Histórico de corridas -->
        <div v-else class="flex flex-col min-h-0">
          <div v-if="obsStore.layerHistoryError" class="text-xs text-red-600 mb-2">
            Error: {{ obsStore.layerHistoryError }}
          </div>
          <div v-else-if="historyRuns.length === 0" class="text-xs text-stone-500 py-8 text-center">
            Sin corridas registradas para esta capa.
          </div>
          <div v-else class="overflow-auto flex-1">
            <table class="w-full text-xs border-collapse">
              <thead class="sticky top-0 bg-white z-10">
                <tr class="border-b border-stone-200 text-stone-500">
                  <th class="text-left py-2 pr-3 font-medium">Run ID</th>
                  <th class="text-left py-2 pr-3 font-medium">Inicio</th>
                  <th class="text-left py-2 pr-3 font-medium">Fin</th>
                  <th class="text-left py-2 pr-3 font-medium">Status</th>
                  <th class="text-right py-2 pl-3 font-medium">Registros agregados</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="run in historyRuns"
                  :key="run.run_id"
                  class="border-b border-stone-100 hover:bg-stone-50 transition-colors"
                >
                  <td class="py-2 pr-3">
                    <span
                      class="font-mono text-stone-700 truncate inline-block max-w-[140px]"
                      :title="run.run_id"
                    >
                      {{ run.run_id }}
                    </span>
                  </td>
                  <td class="py-2 pr-3 text-stone-600">
                    {{ formatDateTime(run.started_at) }}
                  </td>
                  <td class="py-2 pr-3 text-stone-600">
                    {{ formatDateTime(run.finished_at) }}
                  </td>
                  <td class="py-2 pr-3">
                    <span
                      class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border"
                      :class="statusClass(run.status)"
                    >
                      {{ statusLabel(run.status) }}
                    </span>
                  </td>
                  <td class="py-2 pl-3 text-right font-mono text-stone-700">
                    {{ run.records_out > 0 ? '+' + run.records_out : run.records_out }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
