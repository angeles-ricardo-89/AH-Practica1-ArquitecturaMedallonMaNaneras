<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string
  label?: string
}>()

const colorMap: Record<string, string> = {
  ok: 'bg-green-500',
  running: 'bg-yellow-500',
  error: 'bg-red-500',
  interrupted: 'bg-amber-500',
  unknown: 'bg-gray-400',
}

const dotColor = computed(() => colorMap[props.status] ?? colorMap.unknown)

const statusLabel = computed(() => {
  if (props.label) return props.label
  const labelMap: Record<string, string> = {
    ok: 'OK',
    running: 'Ejecutando',
    error: 'Error',
    interrupted: 'Interrumpido',
    unknown: 'Desconocido',
  }
  return labelMap[props.status] ?? props.status
})
</script>

<template>
  <div class="flex items-center gap-2">
    <span class="inline-block w-4 h-4 rounded-full" :class="dotColor" />
    <span class="text-sm font-medium text-gray-700">{{ statusLabel }}</span>
  </div>
</template>
