<script setup lang="ts">
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import type { ModalCapa } from '../../stores/dashboard'
import type { LayerRun } from '../../api/observability'
import PipelineCard from './PipelineCard.vue'

const props = defineProps<{
  layers: LayerRun[]
}>()

const dashboardStore = useDashboardStore()

const orderedLayers = computed(() => {
  const order: ModalCapa[] = ['bronze', 'silver', 'gold']
  return order
    .map((capa) => props.layers.find((l) => l.capa.toLowerCase() === capa))
    .filter(Boolean) as LayerRun[]
})

function handleCardClick(capa: ModalCapa) {
  dashboardStore.openModal(capa)
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-base font-bold text-stone-950 mb-1">Pipeline medallón</h2>
      <p class="text-xs text-stone-500">Timeline Bronze → Silver → Gold</p>
    </div>

    <div class="relative pl-4">
      <!-- Línea vertical sutil -->
      <div class="absolute left-4 top-4 bottom-4 w-px bg-stone-200" />

      <div class="space-y-6">
        <div
          v-for="(layer, idx) in orderedLayers"
          :key="layer.capa"
          class="relative pl-6"
        >
          <!-- Punto del timeline -->
          <div
            class="absolute left-0 top-4 w-2 h-2 rounded-full border-2 bg-white"
            :class="{
              'border-blue-600': layer.status === 'running' || layer.status === 'En curso',
              'border-green-600': layer.status === 'ok' || layer.status === 'complete' || layer.status === 'Completo',
              'border-red-600': layer.status === 'error' || layer.status === 'failed' || layer.status === 'Falló',
              'border-amber-500': layer.status === 'interrupted',
              'border-stone-300': !['running', 'En curso', 'ok', 'complete', 'Completo', 'error', 'failed', 'Falló', 'interrupted'].includes(layer.status),
            }"
          />

          <PipelineCard
            :layer="layer"
            @click="handleCardClick(layer.capa.toLowerCase() as ModalCapa)"
          />

          <!-- Hint card debajo de la última capa -->
          <div
            v-if="idx === orderedLayers.length - 1"
            class="mt-4 bg-red-50 border border-red-100 rounded-2xl p-4"
          >
            <p class="text-xs font-bold text-red-900 mb-1">Click en capa</p>
            <p class="text-xs text-red-700 leading-relaxed">
              abre modal de evidencia con checks propios, métricas de corrida y enlace a logs técnicos.
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
