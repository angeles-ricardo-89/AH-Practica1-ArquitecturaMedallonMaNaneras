import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatResponse, SourceChunk } from '../api/chat'
import { sendChatMessage } from '../api/chat'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: SourceChunk[]
  timestamp: number
}

export const MAX_CONTEXT_TOKENS = 8192

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
      addMessage({
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
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

  return { messages, isLoading, tokenUsage, error, sendMessage, clearMessages }
})
