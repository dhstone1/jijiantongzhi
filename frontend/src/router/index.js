import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('../components/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
      { path: 'rules', name: 'rules', component: () => import('../views/RulesView.vue') },
      { path: 'rules/new', name: 'rule-new', component: () => import('../views/RuleEditView.vue') },
      { path: 'rules/:id/edit', name: 'rule-edit', component: () => import('../views/RuleEditView.vue') },
      { path: 'datasources', name: 'datasources', component: () => import('../views/DataSourceView.vue') },
      { path: 'regions', name: 'regions', component: () => import('../views/RegionView.vue') },
      { path: 'staff', name: 'staff', component: () => import('../views/StaffView.vue') },
      { path: 'bots', name: 'bots', component: () => import('../views/BotView.vue') },
      { path: 'logs', name: 'logs', component: () => import('../views/LogView.vue') },
      { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to) => {
  const store = useUserStore()
  if (!to.meta.public && !store.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && store.isLoggedIn) {
    return { name: 'dashboard' }
  }
  return true
})

export default router

