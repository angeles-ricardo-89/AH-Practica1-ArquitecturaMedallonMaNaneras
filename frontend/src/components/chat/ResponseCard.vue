<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChatMessage } from '../../stores/chat'
import { renderMarkdown } from '../../utils/markdown'

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

      <div
        class="markdown-body text-sm text-stone-800 leading-relaxed"
        v-html="renderMarkdown(message.content)"
      />

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

<style scoped>
:deep(.markdown-body p) {
  margin-bottom: 0.5em;
}
:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}
:deep(.markdown-body ul),
:deep(.markdown-body ol) {
  margin-left: 1.25em;
  margin-bottom: 0.5em;
  list-style-position: outside;
}
:deep(.markdown-body ul) {
  list-style-type: disc;
}
:deep(.markdown-body ol) {
  list-style-type: decimal;
}
:deep(.markdown-body li) {
  margin-bottom: 0.25em;
}
:deep(.markdown-body strong) {
  font-weight: 700;
  color: #1c1917;
}
:deep(.markdown-body em) {
  font-style: italic;
}
:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3) {
  font-weight: 700;
  margin-top: 0.75em;
  margin-bottom: 0.5em;
  color: #1c1917;
}
:deep(.markdown-body h1) {
  font-size: 1.125rem;
}
:deep(.markdown-body h2) {
  font-size: 1rem;
}
:deep(.markdown-body h3) {
  font-size: 0.875rem;
}
:deep(.markdown-body code) {
  background-color: #f5f5f4;
  padding: 0.125em 0.375em;
  border-radius: 0.25rem;
  font-family: ui-monospace, monospace;
  font-size: 0.875em;
}
:deep(.markdown-body pre) {
  background-color: #f5f5f4;
  padding: 0.75em;
  border-radius: 0.5rem;
  overflow-x: auto;
  margin-bottom: 0.5em;
}
:deep(.markdown-body pre code) {
  background-color: transparent;
  padding: 0;
  font-size: 0.8em;
}
:deep(.markdown-body a) {
  color: #2563eb;
  text-decoration: underline;
}
:deep(.markdown-body blockquote) {
  border-left: 3px solid #d6d3d1;
  padding-left: 0.75em;
  margin-left: 0;
  color: #78716c;
  font-style: italic;
}
</style>
