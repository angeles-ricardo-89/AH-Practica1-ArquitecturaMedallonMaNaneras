import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatResponse, SourceChunk } from '../api/chat'
import type { ToolTrace } from '../api/conversations'
import { sendChatMessage } from '../api/chat'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: SourceChunk[]
  traces?: ToolTrace[]
  timestamp: number
  metrics?: {
    similarity: number
    numSources: number
    coverage: number
    latency: number
    tokens: number
    model: string
  }
}

export const MAX_CONTEXT_TOKENS = 10000

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isLoading = ref(false)
  const tokenUsage = ref<Record<string, number>>({})
  const error = ref<string | null>(null)

  function addMessage(msg: Omit<ChatMessage, 'id' | 'timestamp'>) {
    const id = `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    messages.value.push({ ...msg, id, timestamp: Date.now() })
  }

  async function sendMessage(query: string) {
    if (!query.trim() || isLoading.value) return
    error.value = null

    addMessage({ role: 'user', content: query })

    isLoading.value = true
    try {
      const response: ChatResponse = await sendChatMessage(query)
      tokenUsage.value = response.token_usage
      const numSources = response.sources?.length ?? 0
      const avgSim =
        numSources > 0
          ? response.sources!.reduce((s, src) => s + src.similarity, 0) / numSources
          : 0
      addMessage({
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
        metrics: {
          similarity: avgSim,
          numSources,
          coverage: numSources > 0 ? 100 : 0,
          latency: response.latency_ms,
          tokens: response.token_usage?.total ?? 0,
          model: response.model_used,
        },
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error desconocido'
      error.value = message
      addMessage({ role: 'assistant', content: `Error: ${message}` })
    } finally {
      isLoading.value = false
    }
  }

  function clearMessages() {
    messages.value = []
    tokenUsage.value = {}
    error.value = null
  }

  function setLoading(loading: boolean) {
    isLoading.value = loading
  }

  function setTokenUsage(usage: Record<string, number>) {
    tokenUsage.value = usage
  }

  return { messages, isLoading, tokenUsage, error, sendMessage, clearMessages, addMessage, setLoading, setTokenUsage }
})
