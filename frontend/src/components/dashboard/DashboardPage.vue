<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useObservabilityStore } from '../../stores/observability'
import SemaforoEstado from './SemaforoEstado.vue'
import LogViewer from './LogViewer.vue'
import ChatWindow from '../chat/ChatWindow.vue'

const obsStore = useObservabilityStore()

onMounted(() => {
  obsStore.startPolling()
})

onUnmounted(() => {
  obsStore.stopPolling()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50 p-6">
    <header class="mb-6">
      <h1 class="text-2xl font-bold text-gray-900">Lakehouse Mañaneras</h1>
      <p class="text-sm text-gray-500">Dashboard de Observabilidad</p>
    </header>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2 space-y-6">
        <div class="bg-white rounded-lg shadow p-4">
          <h2 class="text-lg font-semibold text-gray-800 mb-3">
            Estado del Pipeline
          </h2>
          <div v-if="obsStore.status" class="space-y-2">
            <SemaforoEstado
              :status="obsStore.status.status"
              :label="
                obsStore.status.status === 'ok'
                  ? 'OK'
                  : obsStore.status.status === 'running'
                    ? 'Ejecutando'
                    : obsStore.status.status === 'error'
                      ? 'Error'
                      : 'Desconocido'
              "
            />
            <div class="text-sm text-gray-600">
              <p>Última ejecución: {{ obsStore.status.last_run || 'N/A' }}</p>
              <p>Último éxito: {{ obsStore.status.last_success || 'N/A' }}</p>
              <p>Registros: {{ obsStore.status.records_count }}</p>
            </div>
          </div>
          <p v-else-if="obsStore.statusError" class="text-sm text-red-500">
            Error: {{ obsStore.statusError }}
          </p>
          <p v-else class="text-sm text-gray-400">Cargando...</p>
        </div>

        <div class="bg-white rounded-lg shadow p-4">
          <h2 class="text-lg font-semibold text-gray-800 mb-3">
            Logs del Pipeline
          </h2>
          <LogViewer :lines="obsStore.logs" />
          <p
            v-if="obsStore.logsError"
            class="text-sm text-red-500 mt-2"
          >
            Error: {{ obsStore.logsError }}
          </p>
        </div>
      </div>

      <div class="bg-white rounded-lg shadow flex flex-col h-[600px]">
        <div class="p-4 border-b">
          <h2 class="text-lg font-semibold text-gray-800">Chat RAG</h2>
        </div>
        <ChatWindow />
      </div>
    </div>
  </div>
</template>
