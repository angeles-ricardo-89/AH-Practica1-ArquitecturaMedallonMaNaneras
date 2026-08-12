import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getClustersLatest, type ClusterDataResponse } from '../api/clusters'

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
  const clusterData = ref<ClusterDataResponse | null>(null)
  const clusterError = ref<string | null>(null)

  const isModalOpen = computed(() => modalCapa.value !== null)

  const sessionClusterColors = ref<Map<number, string>>(new Map())

  const PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
  ]

  function getClusterColor(clusterId: number): string {
    return sessionClusterColors.value.get(clusterId) ?? '#A8A29E'
  }

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

  async function fetchClusters() {
    try {
      const data = await getClustersLatest()
      clusterData.value = data
      clusterError.value = null

      // Preservar colores existentes, asignar nuevos
      for (const cluster of data.clusters) {
        if (!sessionClusterColors.value.has(cluster.cluster_id)) {
          const color = PALETTE[cluster.cluster_id % PALETTE.length]
          sessionClusterColors.value.set(cluster.cluster_id, color!)
        }
      }
    } catch (err) {
      clusterError.value = err instanceof Error ? err.message : 'Error al obtener clusters'
    }
  }

  return {
    selectedResponseId,
    modalCapa,
    autoRefresh,
    clusterData,
    clusterError,
    sessionClusterColors,
    getClusterColor,
    isModalOpen,
    selectResponse,
    openModal,
    closeModal,
    toggleAutoRefresh,
    fetchClusters,
  }
})
