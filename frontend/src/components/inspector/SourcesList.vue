<script setup lang="ts">
import { ref, computed } from 'vue'
import type { SourceChunk } from '../../api/chat'

const props = defineProps<{
  sources: SourceChunk[]
}>()

const expandedIndex = ref<number | null>(null)

const sortedSources = computed(() => {
  return [...props.sources].sort((a, b) => b.similarity - a.similarity)
})

function toggleExpand(idx: number) {
  expandedIndex.value = expandedIndex.value === idx ? null : idx
}
</script>

<template>
  <div class="bg-white border border-stone-200 rounded-2xl p-4 flex flex-col h-full">
    <div class="mb-3">
      <h3 class="text-sm font-bold text-stone-950">Fuentes usadas</h3>
      <p class="text-[10px] text-stone-500 mt-0.5">Ordenadas por relevancia RAG</p>
    </div>

    <div class="flex-1 overflow-y-auto space-y-3">
      <div
        v-for="(source, idx) in sortedSources"
        :key="source.conference_id + idx"
        class="border border-stone-200 rounded-xl p-3 hover:border-stone-300 transition-colors"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <p class="text-[10px] text-stone-400 font-mono mb-0.5">{{ source.conference_date }}</p>
            <p class="text-xs font-bold text-stone-950 truncate">
              {{ source.pregunta_activa || 'Conferencia de prensa' }}
            </p>
          </div>
        </div>

        <div class="mt-2 flex items-center gap-2">
          <span
            class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border"
            :class="{
              'bg-green-100 text-green-700 border-green-200': source.qualitative_label === 'Alta',
              'bg-amber-100 text-amber-700 border-amber-200': source.qualitative_label === 'Media',
              'bg-stone-100 text-stone-600 border-stone-200': !source.qualitative_label || source.qualitative_label === 'Baja',
            }"
          >
            {{ source.similarity.toFixed(2) }} · {{ source.qualitative_label || 'Media' }}
          </span>
        </div>

        <button
          class="mt-2 text-[10px] text-stone-400 hover:text-stone-600 flex items-center gap-1"
          @click="toggleExpand(idx)"
        >
          <span>URL y fragmento colapsados</span>
          <span class="transition-transform" :class="expandedIndex === idx ? 'rotate-180' : ''">▼</span>
        </button>

        <div v-if="expandedIndex === idx" class="mt-2 space-y-2">
          <a
            v-if="source.conference_url"
            :href="source.conference_url"
            target="_blank"
            class="text-[10px] text-blue-600 hover:text-blue-800 underline break-all block"
          >
            {{ source.conference_url }}
          </a>
          <p class="text-[10px] text-stone-600 leading-relaxed bg-stone-50 p-2 rounded-lg">
            {{ source.chunk_text }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
