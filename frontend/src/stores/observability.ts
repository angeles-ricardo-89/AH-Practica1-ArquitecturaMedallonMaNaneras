import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getPipelineStatus, getPipelineLogs, getPipelineLayers, getLayerHistory } from '../api/observability'
import type { PipelineStatus, PipelineLogs, PipelineLayersResponse, LayerHistoryResponse } from '../api/observability'
import { getConfig } from '../api/config'
import type { ConfigResponse } from '../api/config'

export const POLL_INTERVAL = 30000

export const useObservabilityStore = defineStore('observability', () => {
  const status = ref<PipelineStatus | null>(null)
  const logs = ref<string[]>([])
  const layers = ref<PipelineLayersResponse | null>(null)
  const layerHistory = ref<LayerHistoryResponse | null>(null)
  const config = ref<ConfigResponse | null>(null)
  const statusError = ref<string | null>(null)
  const logsError = ref<string | null>(null)
  const layersError = ref<string | null>(null)
  const layerHistoryError = ref<string | null>(null)
  const configError = ref<string | null>(null)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  async function fetchStatus() {
    try {
      status.value = await getPipelineStatus()
      statusError.value = null
    } catch (err) {
      statusError.value = err instanceof Error ? err.message : 'Error al obtener status'
    }
  }

  async function fetchLogs() {
    try {
      const result: PipelineLogs = await getPipelineLogs(50)
      logs.value = result.lines
      logsError.value = null
    } catch (err) {
      logsError.value = err instanceof Error ? err.message : 'Error al obtener logs'
    }
  }

  async function fetchLayers() {
    try {
      layers.value = await getPipelineLayers()
      layersError.value = null
    } catch (err) {
      layersError.value = err instanceof Error ? err.message : 'Error al obtener capas'
    }
  }

  async function fetchConfig() {
    try {
      config.value = await getConfig()
      configError.value = null
    } catch (err) {
      configError.value = err instanceof Error ? err.message : 'Error al obtener config'
    }
  }

  async function fetchLayerHistory(layer: string) {
    try {
      layerHistory.value = await getLayerHistory(layer)
      layerHistoryError.value = null
    } catch (err) {
      layerHistoryError.value = err instanceof Error ? err.message : 'Error al obtener historial'
      layerHistory.value = null
    }
  }

  function startPolling() {
    fetchStatus()
    fetchLogs()
    fetchLayers()
    fetchConfig()
    pollTimer = setInterval(() => {
      fetchStatus()
      fetchLogs()
      fetchLayers()
    }, POLL_INTERVAL)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function manualRefresh() {
    fetchStatus()
    fetchLogs()
    fetchLayers()
  }

  return {
    status,
    logs,
    layers,
    layerHistory,
    config,
    statusError,
    logsError,
    layersError,
    layerHistoryError,
    configError,
    fetchStatus,
    fetchLogs,
    fetchLayers,
    fetchLayerHistory,
    fetchConfig,
    startPolling,
    stopPolling,
    manualRefresh,
  }
})
