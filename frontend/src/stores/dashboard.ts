import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type ModalCapa = 'bronze' | 'silver' | 'gold'

export interface ResponseMetrics {
  similarity: number
  numSources: number
  coverage: number
  reranking?: string
  tokens?: number
  latency?: number
  model?: string
}

export const useDashboardStore = defineStore('dashboard', () => {
  const selectedResponseId = ref<string | null>(null)
  const modalCapa = ref<ModalCapa | null>(null)
  const autoRefresh = ref(true)

  const isModalOpen = computed(() => modalCapa.value !== null)

  function selectResponse(id: string | null) {
    selectedResponseId.value = id
  }

  function openModal(capa: ModalCapa) {
    modalCapa.value = capa
  }

  function closeModal() {
    modalCapa.value = null
  }

  function toggleAutoRefresh() {
    autoRefresh.value = !autoRefresh.value
  }

  return {
    selectedResponseId,
    modalCapa,
    autoRefresh,
    isModalOpen,
    selectResponse,
    openModal,
    closeModal,
    toggleAutoRefresh,
  }
})
