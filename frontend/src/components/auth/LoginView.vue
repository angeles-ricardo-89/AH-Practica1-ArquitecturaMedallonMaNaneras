<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const submitting = ref(false)

async function onSubmit() {
  if (!username.value.trim() || !password.value) return
  submitting.value = true
  const ok = await auth.login(username.value.trim(), password.value)
  submitting.value = false
  if (ok) {
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.push(redirect)
  }
}
</script>

<template>
  <div class="min-h-screen bg-stone-50 flex items-center justify-center p-6">
    <div class="w-full max-w-sm bg-white border border-stone-200 rounded-2xl p-8 shadow-sm">
      <h1 class="text-xl font-bold text-stone-950">RAG del pueblo</h1>
      <p class="text-xs text-stone-500 mt-1 mb-6">
        Acceso restringido. Usa las credenciales demo entregadas en el PDF de la entrega.
      </p>

      <form @submit.prevent="onSubmit" class="flex flex-col gap-3">
        <label class="flex flex-col gap-1">
          <span class="text-xs text-stone-600 font-medium">Usuario</span>
          <input
            v-model="username"
            autocomplete="username"
            class="bg-stone-50 border border-stone-200 rounded-xl px-4 py-2.5 text-sm text-stone-800 focus:outline-none focus:border-stone-300"
          />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-xs text-stone-600 font-medium">Contraseña</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="bg-stone-50 border border-stone-200 rounded-xl px-4 py-2.5 text-sm text-stone-800 focus:outline-none focus:border-stone-300"
          />
        </label>

        <p v-if="auth.error" class="text-xs text-red-600 mt-1">{{ auth.error }}</p>

        <button
          type="submit"
          class="mt-2 bg-red-900 hover:bg-red-800 text-white text-sm font-medium px-5 py-2.5 rounded-xl transition-colors disabled:opacity-50"
          :disabled="submitting || !username.trim() || !password"
        >
          {{ submitting ? 'Entrando...' : 'Entrar' }}
        </button>
      </form>

      <p class="text-[10px] text-stone-400 mt-6 leading-relaxed">
        En producción el nivel gratuito de Gemini puede usar los datos enviados para mejorar
        productos de Google: no introduzcas investigaciones confidenciales.
      </p>
    </div>
  </div>
</template>
