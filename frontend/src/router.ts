import { createRouter, createWebHistory } from 'vue-router'
import DashboardPage from './components/dashboard/DashboardPage.vue'
import LoginView from './components/auth/LoginView.vue'
import { useAuthStore } from './stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/', name: 'dashboard', component: DashboardPage },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) {
    await auth.bootstrap()
  }
  if (to.meta.public) {
    return auth.user ? { name: 'dashboard' } : true
  }
  if (!auth.user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
