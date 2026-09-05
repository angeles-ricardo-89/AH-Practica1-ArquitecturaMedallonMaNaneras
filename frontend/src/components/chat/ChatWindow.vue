<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import { useChatStore, MAX_CONTEXT_TOKENS } from '../../stores/chat'
import { useDashboardStore } from '../../stores/dashboard'
import { useConversationStore } from '../../stores/conversations'
import { sendAgentMessage, createConversation } from '../../api/conversations'
import ResponseCard from './ResponseCard.vue'
import TokenBar from './TokenBar.vue'

const store = useChatStore()
const dashboardStore = useDashboardStore()
const conversationStore = useConversationStore()
const input = ref('')
const messagesContainer = ref<HTMLElement>()
const localError = ref('')

const assistantMessages = computed(() =>
  store.messages.filter((m) => m.role === 'assistant'),
)

async function handleSubmit() {
  const query = input.value.trim()
  if (!query || store.isLoading) return
  input.value = ''
  dashboardStore.selectResponse(null)
  localError.value = ''

  let conversationId = conversationStore.activeId
  if (!conversationId) {
    const title = query.length > 30 ? query.slice(0, 30) + '…' : query
    try {
      conversationId = await createConversation(title)
      if (!conversationId) {
        localError.value = 'No se pudo crear la conversación'
        return
      }
      conversationStore.activeId = conversationId
      await conversationStore.load()
    } catch (err) {
      localError.value = err instanceof Error ? err.message : 'No se pudo crear la conversación'
      return
    }
  }

  store.addMessage({ role: 'user', content: query })
  store.setLoading(true)

  try {
    const response = await sendAgentMessage(conversationId, query)
    const numSources = response.sources?.length ?? 0
    const avgSim =
      numSources > 0
        ? response.sources.reduce((s, src) => s + src.similarity, 0) / numSources
        : 0
    store.addMessage({
      role: 'assistant',
      content: response.answer,
      sources: response.sources,
      traces: response.tool_executions,
      metrics: {
        similarity: avgSim,
        numSources,
        coverage: numSources > 0 ? 100 : 0,
        latency: response.latency_ms,
        tokens: response.token_usage?.total ?? 0,
        model: response.model_used,
      },
    })
    store.setTokenUsage(response.token_usage)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Error desconocido'
    localError.value = message
    store.addMessage({ role: 'assistant', content: `Error: ${message}` })
  } finally {
    store.setLoading(false)
  }

  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function selectResponse(id: string) {
  dashboardStore.selectResponse(id)
}

function isSelected(id: string) {
  return dashboardStore.selectedResponseId === id
}

function handleContainerClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.cursor-pointer')) {
    dashboardStore.selectResponse(null)
  }
}
</script>

<template>
  <div class="flex flex-col h-full bg-white border border-stone-200 rounded-2xl overflow-hidden">
    <!-- Header -->
    <div class="px-5 py-4 border-b border-stone-200 flex items-center justify-between shrink-0">
      <div>
        <h2 class="text-base font-bold text-stone-950">Chat RAG</h2>
        <p class="text-xs text-stone-500">
          Preguntas sobre conferencias matutinas; click en una respuesta para ver fuentes.
        </p>
      </div>
      <div v-if="store.tokenUsage?.total" class="flex items-center gap-2">
        <span class="text-[10px] text-stone-400 bg-stone-50 px-2 py-0.5 rounded-full border border-stone-200">
          {{ assistantMessages.length > 0 ? assistantMessages[assistantMessages.length - 1].metrics?.numSources ?? 0 : 0 }} fuentes
        </span>
        <span class="text-[10px] text-stone-400 bg-stone-50 px-2 py-0.5 rounded-full border border-stone-200">
          latency {{ assistantMessages.length > 0 ? assistantMessages[assistantMessages.length - 1].metrics?.latency ?? 0 : 0 }}ms
        </span>
        <span class="text-[10px] text-stone-400 bg-stone-50 px-2 py-0.5 rounded-full border border-stone-200">
          tokens {{ store.tokenUsage.total ?? 0 }}k
        </span>
      </div>
    </div>

    <TokenBar
      :used="store.tokenUsage?.total ?? 0"
      :max="MAX_CONTEXT_TOKENS"
    />

    <!-- Messages -->
    <div
      ref="messagesContainer"
      class="flex-1 overflow-y-auto space-y-4 p-4"
      @click="handleContainerClick"
    >
      <div v-if="store.messages.length === 0 && !conversationStore.activeId" class="text-center py-12">
        <p class="text-sm text-stone-400">Selecciona o crea una conversación para comenzar</p>
        <p class="text-xs text-stone-300 mt-1">O escribe directamente para crear una nueva</p>
      </div>

      <div v-else-if="store.messages.length === 0" class="text-center py-12">
        <p class="text-sm text-stone-400">Historial visible tipo conversación</p>
        <p class="text-xs text-stone-300 mt-1">Escribe una pregunta para comenzar</p>
      </div>

      <ResponseCard
        v-for="msg in store.messages"
        :key="msg.id"
        :message="msg"
        :is-selected="isSelected(msg.id)"
        @select="selectResponse"
      />

      <div v-if="store.isLoading" class="flex justify-start">
        <div class="bg-stone-50 border border-stone-200 rounded-2xl px-4 py-2">
          <span class="text-xs text-stone-400">Generando respuesta...</span>
        </div>
      </div>

      <div v-if="store.error || localError" class="flex justify-start">
        <div class="bg-red-50 border border-red-200 rounded-2xl px-4 py-2">
          <span class="text-xs text-red-700">{{ store.error || localError }}</span>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="border-t border-stone-200 p-4 shrink-0">
      <form @submit.prevent="handleSubmit" class="flex gap-2">
        <input
          v-model="input"
          type="text"
          placeholder="Escribe una pregunta sobre mañaneras..."
          class="flex-1 bg-stone-50 border border-stone-200 rounded-xl px-4 py-2.5 text-sm text-stone-800 placeholder-stone-400 focus:outline-none focus:border-stone-300 focus:ring-1 focus:ring-stone-300"
          :disabled="store.isLoading"
        />
        <button
          type="submit"
          class="bg-red-900 hover:bg-red-800 text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-colors disabled:opacity-50"
          :disabled="store.isLoading || !input.trim()"
        >
          Enviar
        </button>
      </form>
    </div>
  </div>
</template>
