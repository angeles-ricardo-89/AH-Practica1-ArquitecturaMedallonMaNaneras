<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChatMessage } from '../../stores/chat'

const props = defineProps<{
  message: ChatMessage
  isSelected: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
}>()

const expanded = ref(false)

const isAssistant = computed(() => props.message.role === 'assistant')

const metrics = computed(() => props.message.metrics)

function handleClick() {
  if (isAssistant.value && props.message.id) {
    emit('select', props.message.id)
  }
}

function toggleDetail(e: Event) {
  e.stopPropagation()
  expanded.value = !expanded.value
}
</script>

<template>
  <div
    class="w-full"
    :class="message.role === 'user' ? 'flex justify-end' : 'flex justify-start'"
  >
    <!-- User message -->
    <div
      v-if="message.role === 'user'"
      class="max-w-[85%] bg-stone-100 border border-stone-200 rounded-2xl rounded-tr-sm px-4 py-3"
    >
      <p class="text-sm text-stone-800 whitespace-pre-wrap">{{ message.content }}</p>
      <span class="text-[10px] text-stone-400 mt-1 block text-right">
        {{ new Date(message.timestamp).toLocaleTimeString() }}
      </span>
    </div>

    <!-- Assistant message (response card) -->
    <div
      v-else
      class="max-w-[90%] w-full bg-white border rounded-2xl px-4 py-4 cursor-pointer transition-all"
      :class="isSelected
        ? 'border-red-900 ring-1 ring-red-900'
        : 'border-stone-200 hover:border-stone-300'"
      @click.stop="handleClick"
    >
      <div v-if="isSelected" class="mb-2">
        <span class="text-xs font-bold text-red-900">Respuesta seleccionada</span>
      </div>

      <p class="text-sm text-stone-800 whitespace-pre-wrap leading-relaxed">{{ message.content }}</p>

      <!-- Chips de métricas -->
      <div v-if="metrics" class="flex flex-wrap gap-2 mt-3">
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border bg-green-50 text-green-700 border-green-200">
          similitud {{ metrics.similarity.toFixed(2) }}
        </span>
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border bg-blue-50 text-blue-700 border-blue-200">
          {{ metrics.numSources }} fuentes
        </span>
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border bg-stone-50 text-stone-600 border-stone-200">
          cobertura citas {{ metrics.coverage }}%
        </span>
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border bg-stone-50 text-stone-600 border-stone-200">
          modelo: {{ metrics.model }}
        </span>
      </div>

      <!-- Detalle técnico colapsado -->
      <div class="mt-3">
        <button
          class="w-full text-left text-xs text-stone-400 hover:text-stone-600 bg-stone-50 rounded-lg px-3 py-2 flex items-center justify-between"
          @click="toggleDetail"
        >
          <span>Detalle técnico colapsado: reranking · latency · tokens · modelo usado</span>
          <span class="transition-transform" :class="expanded ? 'rotate-180' : ''">▼</span>
        </button>
        <div v-if="expanded && metrics" class="mt-2 grid grid-cols-2 gap-2 text-[10px] text-stone-500 bg-stone-50 p-3 rounded-lg">
          <div class="flex justify-between">
            <span class="text-stone-400">Reranking</span>
            <span class="font-mono">{{ message.sources && message.sources.length > 0 ? ' sí' : 'no' }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-stone-400">Latency</span>
            <span class="font-mono">{{ metrics.latency }}ms</span>
          </div>
          <div class="flex justify-between">
            <span class="text-stone-400">Tokens</span>
            <span class="font-mono">{{ metrics.tokens }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-stone-400">Modelo</span>
            <span class="font-mono">{{ metrics.model }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
