import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
} from '../api/conversations'
import type { ConversationSummary } from '../api/conversations'

export const useConversationStore = defineStore('conversations', () => {
  const conversations = ref<ConversationSummary[]>([])
  const activeId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    try {
      conversations.value = await listConversations()
      error.value = ''
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'No se pudieron cargar las conversaciones'
    }
  }

  async function create(title: string): Promise<string | null> {
    try {
      const id = await createConversation(title)
      await load()
      return id
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'No se pudo crear la conversación'
      return null
    }
  }

  async function remove(id: string): Promise<void> {
    await deleteConversation(id)
    if (activeId.value === id) {
      activeId.value = null
    }
    await load()
  }

  async function fetchDetail(id: string) {
    return getConversation(id)
  }

  return { conversations, activeId, loading, error, load, create, remove, fetchDetail }
})
