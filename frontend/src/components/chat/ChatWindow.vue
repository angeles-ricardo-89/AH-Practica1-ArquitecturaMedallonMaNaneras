<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useChatStore } from '../../stores/chat'
import { MAX_CONTEXT_TOKENS } from '../../stores/chat'
import ChatMessage from './ChatMessage.vue'
import TokenBar from './TokenBar.vue'

const store = useChatStore()
const input = ref('')
const messagesContainer = ref<HTMLElement>()

async function handleSubmit() {
  const query = input.value.trim()
  if (!query) return
  input.value = ''
  await store.sendMessage(query)
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}
</script>

<template>
  <div class="flex flex-col h-full">
    <TokenBar
      :used="store.tokenUsage?.total_tokens ?? 0"
      :max="MAX_CONTEXT_TOKENS"
    />
    <div
      ref="messagesContainer"
      class="flex-1 overflow-y-auto space-y-4 p-4"
    >
      <ChatMessage
        v-for="msg in store.messages"
        :key="msg.id"
        :message="msg"
      />
      <div v-if="store.isLoading" class="flex justify-start">
        <div class="bg-gray-100 rounded-lg px-4 py-2">
          <span class="text-gray-500">Escribiendo...</span>
        </div>
      </div>
    </div>
    <div class="border-t p-4">
      <form @submit.prevent="handleSubmit" class="flex gap-2">
        <input
          v-model="input"
          type="text"
          placeholder="Escribe tu pregunta..."
          class="flex-1 border rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          :disabled="store.isLoading"
        />
        <button
          type="submit"
          class="bg-blue-500 text-white rounded-lg px-6 py-2 hover:bg-blue-600 disabled:opacity-50"
          :disabled="store.isLoading || !input.trim()"
        >
          Enviar
        </button>
      </form>
    </div>
  </div>
</template>
