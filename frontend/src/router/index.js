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
      { path: 'rules/new', name: 'rule-new', component: () => import('../views/RuleEditView.vue'), meta: { needRules: true } },
      { path: 'rules/:id/edit', name: 'rule-edit', component: () => import('../views/RuleEditView.vue'), meta: { needRules: true } },
      { path: 'datasources', name: 'datasources', component: () => import('../views/DataSourceView.vue'), meta: { provinceOnly: true } },
      { path: 'regions', name: 'regions', component: () => import('../views/RegionView.vue'), meta: { needLocal: true } },
      { path: 'staff', name: 'staff', component: () => import('../views/StaffView.vue'), meta: { needLocal: true } },
      { path: 'bots', name: 'bots', component: () => import('../views/BotView.vue'), meta: { needLocal: true } },
      { path: 'logs', name: 'logs', component: () => import('../views/LogView.vue') },
      { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { provinceOnly: true } },
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
  // 菜单藏起来还不够，直接敲地址也得拦住
  if (to.meta.provinceOnly && !store.isAdmin) return { name: 'dashboard' }
  if (to.meta.needLocal && !store.canManageLocal) return { name: 'dashboard' }
  if (to.meta.needRules && !store.canManageRules) return { name: 'dashboard' }
  return true
})

export default router
