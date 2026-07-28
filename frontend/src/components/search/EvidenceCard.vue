<script setup lang="ts">
import type { SourceChunk } from '../../api/chat'

defineProps<{
  source: SourceChunk
}>()

function truncatedText(text: string, max = 150): string {
  return text.length > max ? text.slice(0, max) + '...' : text
}
</script>

<template>
  <div class="border rounded-lg p-3 hover:bg-gray-50 cursor-pointer transition-colors">
    <div class="flex justify-between items-center mb-1">
      <span class="text-sm font-medium text-gray-700">{{ source.participant }}</span>
      <span class="text-xs text-gray-500">{{ source.conference_date }}</span>
    </div>
    <p class="text-sm text-gray-600">{{ truncatedText(source.chunk_text) }}</p>
    <div class="mt-1 flex items-center gap-2">
      <a
        v-if="source.conference_url"
        :href="source.conference_url"
        target="_blank"
        class="text-xs text-blue-500 hover:text-blue-700 underline"
      >
        Ver fuente
      </a>
      <span class="text-xs text-gray-400">
        Similaridad: {{ (source.similarity * 100).toFixed(1) }}%
      </span>
    </div>
  </div>
</template>
