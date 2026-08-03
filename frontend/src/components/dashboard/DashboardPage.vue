<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useObservabilityStore } from '../../stores/observability'
import { useChatStore } from '../../stores/chat'
import { useDashboardStore } from '../../stores/dashboard'
import { getEmbeddings3D } from '../../api/embeddings'
import type { Embedding3DPoint } from '../../api/embeddings'
import AppHeader from '../shared/AppHeader.vue'
import PipelineTimeline from '../pipeline/PipelineTimeline.vue'
import EvidenceModal from '../pipeline/EvidenceModal.vue'
import ChatWindow from '../chat/ChatWindow.vue'
import Embeddings3D from '../inspector/Embeddings3D.vue'
import SourcesList from '../inspector/SourcesList.vue'

const obsStore = useObservabilityStore()
const chatStore = useChatStore()
const dashboardStore = useDashboardStore()

const embeddingsPoints = ref<Embedding3DPoint[]>([])
const embeddingsError = ref<string | null>(null)

const selectedMessage = computed(() => {
  if (!dashboardStore.selectedResponseId) return null
  return chatStore.messages.find(
    (m) => m.id === dashboardStore.selectedResponseId && m.role === 'assistant',
  )
})

const selectedSources = computed(() => selectedMessage.value?.sources ?? [])

const highlightedChunks = computed(() => {
  if (!selectedSources.value.length) return []
  return selectedSources.value
    .map((s) => s.conference_id)
    .filter(Boolean)
})

async function fetchEmbeddings() {
  try {
    const response = await getEmbeddings3D()
    embeddingsPoints.value = response.points
    embeddingsError.value = null
  } catch (err) {
    embeddingsError.value = err instanceof Error ? err.message : 'Error al obtener embeddings'
    embeddingsPoints.value = []
  }
}

onMounted(() => {
  obsStore.startPolling()
  fetchEmbeddings()
})

onUnmounted(() => {
  obsStore.stopPolling()
})
</script>

<template>
  <div class="h-screen bg-stone-50 p-6 flex flex-col">
    <div class="max-w-[1440px] mx-auto w-full flex flex-col gap-5 h-full">
      <!-- Header -->
      <AppHeader />

      <!-- Main 3-column layout -->
      <div class="flex gap-5 flex-1 min-h-0 overflow-hidden">
        <!-- Columna izquierda: Pipeline -->
        <div class="w-[300px] shrink-0 overflow-y-auto">
          <div class="bg-white border border-stone-200 rounded-2xl p-4 min-h-full">
            <PipelineTimeline
              v-if="obsStore.layers?.layers && obsStore.layers.layers.length > 0"
              :layers="obsStore.layers.layers"
            />
            <div v-else-if="obsStore.layersError" class="text-xs text-red-600">
              Error: {{ obsStore.layersError }}
            </div>
            <div v-else class="text-xs text-stone-400">
              Sin datos del pipeline
            </div>
          </div>
        </div>

        <!-- Columna central: Chat RAG -->
        <div class="flex-1 min-w-0 overflow-hidden">
          <ChatWindow class="h-full" />
        </div>

        <!-- Columna derecha: Inspector -->
        <div class="w-[282px] shrink-0 flex flex-col gap-4 overflow-hidden">
          <div v-if="embeddingsError" class="bg-white border border-stone-200 rounded-2xl p-4 shrink-0">
            <h3 class="text-sm font-bold text-stone-950 mb-1">Embeddings 3D</h3>
            <p class="text-xs text-stone-500">sin datos</p>
          </div>
          <Embeddings3D
            v-else
            :points="embeddingsPoints"
            :highlighted-chunks="highlightedChunks"
            class="shrink-0"
          />

          <div v-if="!selectedMessage" class="bg-white border border-stone-200 rounded-2xl p-4 flex-1 min-h-0 overflow-hidden">
            <h3 class="text-sm font-bold text-stone-950 mb-1">Fuentes usadas</h3>
            <p class="text-xs text-stone-500">
              Selecciona una respuesta del chat para ver fuentes usadas.
            </p>
          </div>

          <SourcesList
            v-else
            :sources="selectedSources"
            class="flex-1 min-h-0 overflow-hidden"
          />
        </div>
      </div>
    </div>

    <!-- Modal de evidencia -->
    <EvidenceModal />
  </div>
</template>
