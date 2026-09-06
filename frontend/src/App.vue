<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const authed = computed(() => auth.user !== null)
const inLogin = computed(() => route.name === 'login')

async function doLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <div v-if="authed && !inLogin" class="h-screen flex flex-col">
    <nav class="h-12 shrink-0 bg-white border-b border-stone-200 flex items-center gap-4 px-6">
      <span class="text-sm font-bold text-stone-950">RAG del pueblo</span>
      <router-link
        to="/"
        class="text-xs text-stone-500 hover:text-stone-800"
        :class="route.name === 'dashboard' ? 'font-semibold text-red-900' : ''"
      >
        Dashboard técnico
      </router-link>
      <div class="flex-1" />
      <span v-if="auth.user" class="text-xs text-stone-500">{{ auth.user.username }}</span>
      <button class="text-xs text-stone-500 hover:text-red-700" @click="doLogout">
        Salir
      </button>
    </nav>
    <main class="flex-1 min-h-0 p-5">
      <router-view />
    </main>
  </div>
  <router-view v-else />
</template>
