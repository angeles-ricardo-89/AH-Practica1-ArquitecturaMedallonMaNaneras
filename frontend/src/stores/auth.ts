import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchMe, login as apiLogin, logout as apiLogout } from '../api/auth'
import type { Me } from '../api/auth'
import { useChatStore } from './chat'
import { useConversationStore } from './conversations'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<Me | null>(null)
  const initialized = ref(false)
  const loading = ref(false)
  const error = ref('')

  function resetDomainStores(): void {
    useChatStore().clearMessages()
    useConversationStore().$reset()
  }

  async function bootstrap(): Promise<void> {
    if (initialized.value) return
    try {
      user.value = await fetchMe()
    } catch {
      user.value = null
    } finally {
      initialized.value = true
    }
  }

  async function login(username: string, password: string): Promise<boolean> {
    loading.value = true
    error.value = ''
    try {
      user.value = await apiLogin(username, password)
      resetDomainStores()
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Error de autenticación'
      return false
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    await apiLogout()
    user.value = null
    resetDomainStores()
  }

  return { user, initialized, loading, error, bootstrap, login, logout }
})
