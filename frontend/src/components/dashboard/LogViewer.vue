<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{
  lines: string[]
}>()

const logContainer = ref<HTMLElement>()

watch(
  () => props.lines.length,
  async () => {
    await nextTick()
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  },
)
</script>

<template>
  <div
    ref="logContainer"
    class="bg-gray-900 text-green-400 font-mono text-xs p-4 rounded-lg h-64 overflow-y-auto"
  >
    <div v-if="lines.length === 0" class="text-gray-500 italic">
      Sin logs disponibles
    </div>
    <div v-for="(line, idx) in lines" :key="idx" class="whitespace-pre-wrap">
      {{ line }}
    </div>
  </div>
</template>
