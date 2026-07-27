<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  used: number
  max: number
}>()

const percentage = computed(() => Math.min((props.used / props.max) * 100, 100))

const barColor = computed(() => {
  if (percentage.value >= 90) return 'bg-red-500'
  if (percentage.value >= 70) return 'bg-yellow-500'
  return 'bg-green-500'
})

const textColor = computed(() => {
  if (percentage.value >= 90) return 'text-red-700'
  if (percentage.value >= 70) return 'text-yellow-700'
  return 'text-green-700'
})
</script>

<template>
  <div v-if="used > 0" class="w-full px-4 py-2 border-b">
    <div class="flex justify-between text-xs mb-1" :class="textColor">
      <span>{{ used }} / {{ max }} tokens</span>
      <span>{{ percentage.toFixed(0) }}%</span>
    </div>
    <div class="w-full bg-gray-200 rounded-full h-2">
      <div
        class="h-2 rounded-full transition-all duration-300"
        :class="barColor"
        :style="{ width: percentage + '%' }"
      />
    </div>
  </div>
</template>
