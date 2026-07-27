<script setup lang="ts">
import type { ChatMessage } from '../../stores/chat'

defineProps<{
  message: ChatMessage
}>()
</script>

<template>
  <div class="flex" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
    <div
      class="max-w-[80%] rounded-lg px-4 py-2"
      :class="
        message.role === 'user'
          ? 'bg-blue-500 text-white'
          : 'bg-gray-100 text-gray-900'
      "
    >
      <p class="whitespace-pre-wrap">{{ message.content }}</p>
      <span class="text-xs opacity-70 mt-1 block">
        {{ new Date(message.timestamp).toLocaleTimeString() }}
      </span>
    </div>
  </div>
</template>
