<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useObservabilityStore } from '../../stores/observability'
import { useChatStore } from '../../stores/chat'
import { useDashboardStore } from '../../stores/dashboard'
import { useConversationStore } from '../../stores/conversations'
import { getEmbeddings3D } from '../../api/embeddings'
import { getConversation } from '../../api/conversations'
import type { Embedding3DPoint } from '../../api/embeddings'
import AppHeader from '../shared/AppHeader.vue'
import EvidenceModal from '../pipeline/EvidenceModal.vue'
import ChatWindow from '../chat/ChatWindow.vue'
import Embeddings3D from '../inspector/Embeddings3D.vue'
import SourcesList from '../inspector/SourcesList.vue'

const obsStore = useObservabilityStore()
const chatStore = useChatStore()
const dashboardStore = useDashboardStore()
const conversationStore = useConversationStore()

const embeddingsPoints = ref<Embedding3DPoint[]>([])
const embeddingsError = ref<string | null>(null)
const chatAreaRef = ref<HTMLElement>()
const inspectorRef = ref<HTMLElement>()
const embeddingsHeight = ref(240)
const isResizing = ref(false)

function startResize(_e: MouseEvent) {
  isResizing.value = true
  document.body.style.cursor = 'ns-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('mousemove', onResize)
  window.addEventListener('mouseup', stopResize)
}

function onResize(e: MouseEvent) {
  if (!isResizing.value || !inspectorRef.value) return
  const rect = inspectorRef.value.getBoundingClientRect()
  const topOffset = e.clientY - rect.top
  const minH = 150
  const maxH = rect.height - 150 - 24 // 24 = resizer height + gaps
  embeddingsHeight.value = Math.max(minH, Math.min(maxH, topOffset))
}

function stopResize() {
  isResizing.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('mousemove', onResize)
  window.removeEventListener('mouseup', stopResize)
}

const selectedMessage = computed(() => {
  if (!dashboardStore.selectedResponseId) return null
  return chatStore.messages.find(
    (m) => m.id === dashboardStore.selectedResponseId && m.role === 'assistant',
  )
})

const selectedSources = computed(() => selectedMessage.value?.sources ?? [])

function handleOutsideClick(e: MouseEvent) {
  const t = e.target as Node
  const isInInspector = inspectorRef.value?.contains(t) ?? false
  if (!chatAreaRef.value?.contains(t) && !isInInspector) {
    dashboardStore.selectResponse(null)
  }
}

const posToChunkKey = computed(() => {
  const map = new Map<string, string>()
  for (const p of embeddingsPoints.value) {
    const key = `${p.x.toFixed(6)}_${p.y.toFixed(6)}_${p.z.toFixed(6)}`
    map.set(key, p.chunk_key)
  }
  return map
})

const activeChunkKeys = computed(() => {
  if (!dashboardStore.selectedResponseId) return new Set<string>()
  const set = new Set<string>()
  for (const src of selectedSources.value) {
    if (src.embedding_3d && src.embedding_3d.length === 3) {
      const key = `${src.embedding_3d[0].toFixed(6)}_${src.embedding_3d[1].toFixed(6)}_${src.embedding_3d[2].toFixed(6)}`
      const ck = posToChunkKey.value.get(key)
      if (ck) set.add(ck)
    }
  }
  return set
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

async function createConversation() {
  const id = await conversationStore.create('Nueva conversación')
  if (id) {
    conversationStore.activeId = id
  }
}

async function openConversation(id: string) {
  conversationStore.activeId = id
  chatStore.clearMessages()
  try {
    const detail = await getConversation(id)
    for (const m of detail.messages) {
      chatStore.addMessage({
        role: m.role === 'assistant' ? 'assistant' : 'user',
        content: m.content,
      })
    }
  } catch (err) {
    console.error('Error cargando conversación:', err)
  }
}

async function removeConversation(id: string) {
  await conversationStore.remove(id)
}

onMounted(() => {
  obsStore.startPolling()
  fetchEmbeddings()
  dashboardStore.fetchClusters()
  document.addEventListener('click', handleOutsideClick)
  conversationStore.load()
})

onUnmounted(() => {
  obsStore.stopPolling()
  document.removeEventListener('click', handleOutsideClick)
})
</script>

<template>
  <div class="h-full bg-stone-50 p-6 flex flex-col">
    <div class="w-full flex flex-col gap-5 h-full">
      <!-- Header -->
      <AppHeader />

      <!-- Main 3-column layout -->
      <div class="flex gap-5 flex-1 min-h-0 overflow-hidden">
        <!-- Columna izquierda: Conversaciones -->
        <div class="w-[300px] shrink-0 overflow-y-auto">
          <div class="bg-white border border-stone-200 rounded-2xl p-4 min-h-full flex flex-col gap-3">
            <div class="flex items-center justify-between">
              <div>
                <h2 class="text-sm font-bold text-stone-950">Conversaciones</h2>
                <p class="text-[11px] text-stone-400">Memoria aislada por conversación</p>
              </div>
              <button
                class="bg-red-900 hover:bg-red-800 text-white text-xs px-2.5 py-1.5 rounded-lg transition-colors"
                title="Crear conversación"
                @click="createConversation"
              >
                +
              </button>
            </div>

            <ul class="flex-1 overflow-y-auto space-y-1">
              <li v-for="c in conversationStore.conversations" :key="c.id">
                <div
                  class="group flex items-center gap-1 rounded-lg px-2 py-1.5 cursor-pointer"
                  :class="c.id === conversationStore.activeId ? 'bg-red-900 text-white' : 'hover:bg-stone-100 text-stone-700'"
                  @click="openConversation(c.id)"
                >
                  <span class="flex-1 min-w-0 truncate text-xs">{{ c.title || 'Sin título' }}</span>
                  <button
                    class="text-[10px] px-1 rounded hover:opacity-70"
                    :class="c.id === conversationStore.activeId ? 'text-white' : 'text-stone-400'"
                    title="Borrar conversación"
                    @click.stop="removeConversation(c.id)"
                  >
                    ✕
                  </button>
                </div>
              </li>
              <li v-if="conversationStore.conversations.length === 0" class="text-[11px] text-stone-400 px-2 py-2">
                Sin conversaciones. Crea una para comenzar.
              </li>
            </ul>

            <div v-if="conversationStore.error" class="text-[10px] text-red-600">
              {{ conversationStore.error }}
            </div>
          </div>
        </div>

        <!-- Columna central: Chat RAG -->
        <div ref="chatAreaRef" class="flex-[1] min-w-0 overflow-hidden">
          <ChatWindow class="h-full" />
        </div>

        <!-- Columna derecha: Inspector -->
        <div ref="inspectorRef" class="flex-[0.7] min-w-[280px] flex flex-col gap-2 overflow-hidden">
          <!-- Embeddings 3D -->
          <div
            v-if="embeddingsError"
            class="bg-white border border-stone-200 rounded-2xl p-4 shrink-0"
            :style="{ height: embeddingsHeight + 'px' }"
          >
            <h3 class="text-sm font-bold text-stone-950 mb-1">Embeddings 3D</h3>
            <p class="text-xs text-stone-500">sin datos</p>
          </div>
          <div
            v-else
            class="shrink-0 overflow-hidden"
            :style="{ height: embeddingsHeight + 'px' }"
          >
            <Embeddings3D
              :points="embeddingsPoints"
              :active-chunk-keys="activeChunkKeys"
              class="h-full"
            />
          </div>

          <!-- Slider / Resizer -->
          <div
            class="h-4 shrink-0 flex items-center justify-center cursor-ns-resize group"
            @mousedown.prevent="startResize"
          >
            <div
              class="w-12 h-1 rounded-full transition-colors"
              :class="isResizing ? 'bg-red-700' : 'bg-stone-300 group-hover:bg-stone-400'"
            />
          </div>

          <!-- Fuentes usadas -->
          <div
            v-if="!selectedMessage"
            class="bg-white border border-stone-200 rounded-2xl p-4 flex-1 min-h-0 overflow-hidden"
          >
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
