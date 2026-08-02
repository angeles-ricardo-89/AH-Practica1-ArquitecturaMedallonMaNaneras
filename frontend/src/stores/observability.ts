import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getPipelineStatus, getPipelineLogs, getPipelineLayers } from '../api/observability'
import type { PipelineStatus, PipelineLogs, PipelineLayersResponse } from '../api/observability'
import { getConfig } from '../api/config'
import type { ConfigResponse } from '../api/config'

export const POLL_INTERVAL = 30000

export const useObservabilityStore = defineStore('observability', () => {
  const status = ref<PipelineStatus | null>(null)
  const logs = ref<string[]>([])
  const layers = ref<PipelineLayersResponse | null>(null)
  const config = ref<ConfigResponse | null>(null)
  const statusError = ref<string | null>(null)
  const logsError = ref<string | null>(null)
  const layersError = ref<string | null>(null)
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
    config,
    statusError,
    logsError,
    layersError,
    configError,
    fetchStatus,
    fetchLogs,
    fetchLayers,
    fetchConfig,
    startPolling,
    stopPolling,
    manualRefresh,
  }
})
