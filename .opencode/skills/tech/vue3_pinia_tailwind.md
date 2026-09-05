# Tech Skill: Vue 3 + Pinia + TailwindCSS

## Proposito

Definir las mejores practicas para el frontend del dashboard Lakehouse Mañaneras usando Vue 3 Composition API, Pinia para estado global, y TailwindCSS para estilos.

## Estructura del Proyecto

```
frontend/
    src/
        api/              # Cliente HTTP (fetch/axios hacia FastAPI)
            client.ts
            search.ts
            chat.ts
            observability.ts
        components/
            chat/
                ChatWindow.vue
                ChatMessage.vue
                TokenBar.vue
            dashboard/
                SemaforoEstado.vue
                LogViewer.vue
            search/
                SearchBar.vue
                EvidenceCard.vue
            shared/
                AppHeader.vue
                AppLayout.vue
        stores/
            chat.ts         # Pinia store del chat
            observability.ts  # Pinia store de logs/semaforos
        App.vue
        main.ts
    index.html
    vite.config.ts
    tailwind.config.ts
    tsconfig.json
    package.json
```

## Patron `<script setup>` con TypeScript Estricto

```vue
<script setup lang="ts">
import { ref, computed } from "vue";
import { useChatStore } from "@/stores/chat";
import ChatMessage from "./ChatMessage.vue";
import type { ChatMessage as ChatMessageType } from "@/api/chat";

const chatStore = useChatStore();
const inputText = ref("");

const mensajesVisibles = computed<ChatMessageType[]>(() =>
  chatStore.messages.filter((m) => m.visible),
);

const tokenUsagePercent = computed<number>(() => {
  const max = chatStore.maxContextTokens;
  if (max <= 0) return 0;
  return Math.min(100, Math.round((chatStore.currentTokens / max) * 100));
});

async function enviarMensaje() {
  if (!inputText.value.trim()) return;
  await chatStore.sendMessage(inputText.value);
  inputText.value = "";
}
</script>

<template>
  <div class="flex flex-col h-full bg-gray-900 text-gray-100">
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <ChatMessage
        v-for="msg in mensajesVisibles"
        :key="msg.id"
        :message="msg"
      />
    </div>
    <!-- TokenBar -->
    <div class="px-4 py-2 border-t border-gray-700">
      <div class="flex items-center gap-2">
        <div class="flex-1 h-2 bg-gray-700 rounded overflow-hidden">
          <div
            class="h-full transition-all duration-300 rounded"
            :class="tokenUsagePercent > 90 ? 'bg-red-500' : 'bg-emerald-500'"
            :style="{ width: tokenUsagePercent + '%' }"
          />
        </div>
        <span class="text-xs font-mono tabular-nums">
          {{ chatStore.currentTokens }} / {{ chatStore.maxContextTokens }}
        </span>
      </div>
    </div>
    <!-- Input -->
    <div class="p-4 border-t border-gray-700">
      <form @submit.prevent="enviarMensaje" class="flex gap-2">
        <input
          v-model="inputText"
          type="text"
          placeholder="Escribe tu pregunta..."
          class="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
        />
        <button
          type="submit"
          class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm font-medium transition-colors"
        >
          Enviar
        </button>
      </form>
    </div>
  </div>
</template>
```

## Pinia Store (chat.ts)

```typescript
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { ChatMessage } from "@/api/chat";
import { searchAPI } from "@/api/search";

export const useChatStore = defineStore("chat", () => {
  const messages = ref<ChatMessage[]>([]);
  const currentTokens = ref(0);
  const maxContextTokens = ref(10000);
  const isStreaming = ref(false);

  const tokenUsagePercent = computed(() => {
    if (maxContextTokens.value <= 0) return 0;
    return Math.round((currentTokens.value / maxContextTokens.value) * 100);
  });

  async function sendMessage(text: string): Promise<void> {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: Date.now(),
      evidence: [],
    };
    messages.value.push(userMsg);

    isStreaming.value = true;
    try {
      const response = await searchAPI.search({ query: text, top_k: 8 });
      // ... manejar respuesta y actualizar tokens
    } finally {
      isStreaming.value = false;
    }
  }

  function clearContext(): void {
    messages.value = [];
    currentTokens.value = 0;
  }

  return {
    messages,
    currentTokens,
    maxContextTokens,
    isStreaming,
    tokenUsagePercent,
    sendMessage,
    clearContext,
  };
});
```

## TailwindCSS — Reglas

- Usar clases utilitarias. No CSS custom a menos que sea estrictamente necesario.
- Tema oscuro por defecto (bg-gray-900, text-gray-100).
- Acentos en emerald-500/600 para acciones positivas.
- Rojo (red-500) para alertas y bloqueos.
- Layout responsivo mobile-first con breakpoints `sm`, `md`, `lg`.

## Herramientas

- **Vite**: Bundler y dev server.
- **Vue 3 + Composition API**: `<script setup lang="ts">`.
- **Pinia**: Estado global reactivo.
- **TailwindCSS v3/v4**: Estilos utilitarios.
- **TypeScript**: `strict: true` en tsconfig.json.

## Checklist de Verificacion

- [ ] `pnpm typecheck` pasa sin errores.
- [ ] `pnpm lint` pasa sin errores.
- [ ] `pnpm build` genera dist/ sin warnings.
- [ ] Stores usan Composition API (`defineStore("name", () => { ... })`).
- [ ] No hay CSS custom en `<style>` — todo via Tailwind utilitario.
- [ ] Todo componente usa `<script setup lang="ts">`.
- [ ] TokenBar muestra alerta visual cuando > 90% de MAX_CONTEXT_TOKENS.
- [ ] EvidenceCard muestra fuente, fecha, participante y fragmento.
