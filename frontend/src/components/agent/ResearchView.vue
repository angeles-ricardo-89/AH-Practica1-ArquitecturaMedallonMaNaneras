<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useConversationStore } from '../../stores/conversations'
import {
  sendAgentMessage,
  getConversation,
  type ToolTrace,
} from '../../api/conversations'
import { renderMarkdown } from '../../utils/markdown'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  traces?: ToolTrace[]
  refusal?: boolean
}

const store = useConversationStore()
const newTitle = ref('')
const input = ref('')
const messages = ref<DisplayMessage[]>([])
const loadingTurn = ref(false)
const error = ref('')

async function createNew() {
  const title = newTitle.value.trim() || 'Nueva investigación'
  const id = await store.create(title)
  if (id) {
    newTitle.value = ''
    await openConversation(id)
  }
}

async function openConversation(id: string) {
  store.activeId = id
  error.value = ''
  messages.value = []
  try {
    const detail = await getConversation(id)
    messages.value = detail.messages.map((m, i) => ({
      id: `${id}_${i}`,
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: m.content,
    }))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'No se pudo abrir la conversación'
  }
}

async function removeConversation(id: string) {
  await store.remove(id)
  if (store.activeId === null) messages.value = []
}

async function submit() {
  const question = input.value.trim()
  if (!question || loadingTurn.value || !store.activeId) return
  input.value = ''
  error.value = ''
  messages.value.push({ id: `user_${Date.now()}`, role: 'user', content: question })
  loadingTurn.value = true
  try {
    const resp = await sendAgentMessage(store.activeId, question)
    messages.value.push({
      id: `assistant_${Date.now()}`,
      role: 'assistant',
      content: resp.answer,
      traces: resp.tool_executions,
      refusal: resp.refusal,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Error al consultar al agente'
  } finally {
    loadingTurn.value = false
  }
}

onMounted(() => {
  store.load()
})
</script>

<template>
  <div class="h-full flex gap-5">
    <!-- Sidebar conversaciones -->
    <aside class="w-[280px] shrink-0 bg-white border border-stone-200 rounded-2xl p-4 flex flex-col gap-3 overflow-hidden">
      <div>
        <h2 class="text-sm font-bold text-stone-950">Conversaciones</h2>
        <p class="text-[11px] text-stone-400">Memoria aislada por conversación (30 días)</p>
      </div>

      <form @submit.prevent="createNew" class="flex gap-2">
        <input
          v-model="newTitle"
          placeholder="Título nuevo..."
          class="flex-1 min-w-0 bg-stone-50 border border-stone-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none"
        />
        <button
          type="submit"
          class="bg-red-900 hover:bg-red-800 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
          title="Crear conversación"
        >
          +
        </button>
      </form>

      <ul class="flex-1 overflow-y-auto space-y-1">
        <li v-for="c in store.conversations" :key="c.id">
          <div
            class="group flex items-center gap-1 rounded-lg px-2 py-1.5 cursor-pointer"
            :class="c.id === store.activeId ? 'bg-red-900 text-white' : 'hover:bg-stone-100 text-stone-700'"
            @click="openConversation(c.id)"
          >
            <span class="flex-1 min-w-0 truncate text-xs">{{ c.title || 'Sin título' }}</span>
            <button
              class="text-[10px] px-1 rounded hover:opacity-70"
              :class="c.id === store.activeId ? 'text-white' : 'text-stone-400'"
              title="Borrar conversación"
              @click.stop="removeConversation(c.id)"
            >
              ✕
            </button>
          </div>
        </li>
        <li v-if="store.conversations.length === 0" class="text-[11px] text-stone-400 px-2 py-2">
          Sin conversaciones. Crea una para comenzar.
        </li>
      </ul>

      <button
        v-if="store.error"
        class="text-[10px] text-red-600 text-left"
      >
        {{ store.error }}
      </button>
    </aside>

    <!-- Panel de chat -->
    <section class="flex-1 min-w-0 bg-white border border-stone-200 rounded-2xl flex flex-col overflow-hidden">
      <header class="px-5 py-3 border-b border-stone-200 flex items-center justify-between">
        <div>
          <h2 class="text-sm font-bold text-stone-950">Agente de investigación</h2>
          <p v-if="store.activeId" class="text-[11px] text-stone-400">
            Conversación activa · máximo 2 herramientas por turno · respuestas con evidencia
          </p>
          <p v-else class="text-[11px] text-stone-400">
            Selecciona o crea una conversación para preguntar.
          </p>
        </div>
      </header>

      <div class="flex-1 overflow-y-auto p-4 space-y-4">
        <div v-if="messages.length === 0" class="text-center py-12">
          <p class="text-sm text-stone-400">Pregunta por una persona, tema o cluster.</p>
        </div>

        <div v-for="m in messages" :key="m.id" class="flex" :class="m.role === 'user' ? 'justify-end' : 'justify-start'">
          <div
            class="max-w-[85%]"
            :class="m.role === 'user' ? 'bg-stone-100 border border-stone-200 rounded-2xl rounded-tr-sm px-4 py-3' : 'w-full bg-white border border-stone-200 rounded-2xl px-4 py-3'"
          >
            <p class="text-sm text-stone-800 whitespace-pre-wrap" v-if="m.role === 'user'">{{ m.content }}</p>
            <div v-else>
              <div class="markdown text-sm text-stone-800 leading-relaxed" v-html="renderMarkdown(m.content)" />
              <p v-if="m.refusal" class="text-[11px] text-stone-500 mt-2 bg-stone-50 rounded-lg px-3 py-2">
                El agente no encontró evidencia suficiente.
              </p>

              <div v-if="m.traces && m.traces.length" class="mt-3 bg-stone-50 rounded-lg p-3">
                <p class="text-[10px] font-semibold text-stone-500 uppercase mb-2">Cómo investigó</p>
                <ul class="space-y-1">
                  <li v-for="(t, i) in m.traces" :key="i" class="text-[11px] text-stone-600">
                    <span class="font-mono font-medium">{{ t.tool_name }}</span>
                    · estado {{ t.status }} · {{ t.result_count }} resultados · {{ t.duration_ms }}ms
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <div v-if="loadingTurn" class="flex justify-start">
          <span class="text-xs text-stone-400 bg-stone-50 rounded-xl px-4 py-2">Investigando...</span>
        </div>
        <div v-if="error" class="text-xs text-red-600 bg-red-50 rounded-xl px-4 py-2">{{ error }}</div>
      </div>

      <form @submit.prevent="submit" class="border-t border-stone-200 p-4 flex gap-2">
        <input
          v-model="input"
          class="flex-1 bg-stone-50 border border-stone-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none disabled:opacity-50"
          placeholder="Ej. ¿qué se declaró sobre la reforma energética?"
          :disabled="loadingTurn || !store.activeId"
        />
        <button
          type="submit"
          class="bg-red-900 hover:bg-red-800 text-white text-sm px-5 py-2.5 rounded-xl disabled:opacity-50"
          :disabled="loadingTurn || !store.activeId || !input.trim()"
        >
          Enviar
        </button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.markdown p { margin-bottom: 0.5em; }
.markdown ul, .markdown ol { margin-left: 1.25em; margin-bottom: 0.5em; list-style-position: outside; }
.markdown ul { list-style-type: disc; }
.markdown ol { list-style-type: decimal; }
.markdown strong { font-weight: 700; }
</style>
