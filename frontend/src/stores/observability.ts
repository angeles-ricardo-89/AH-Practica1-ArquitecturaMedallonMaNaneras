import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getPipelineStatus, getPipelineLogs } from '../api/observability'
import type { PipelineStatus } from '../api/observability'
import type { PipelineLogs } from '../api/observability'

export const POLL_INTERVAL = 10000

export const useObservabilityStore = defineStore('observability', () => {
  const status = ref<PipelineStatus | null>(null)
  const logs = ref<string[]>([])
  const statusError = ref<string | null>(null)
  const logsError = ref<string | null>(null)
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

  function startPolling() {
    fetchStatus()
    fetchLogs()
    pollTimer = setInterval(() => {
      fetchStatus()
      fetchLogs()
    }, POLL_INTERVAL)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    status,
    logs,
    statusError,
    logsError,
    fetchStatus,
    fetchLogs,
    startPolling,
    stopPolling,
  }
})
