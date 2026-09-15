<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">推</div>
        <div>
          <div class="brand-name">运营数据推送</div>
          <div class="brand-sub">Data Push Console</div>
        </div>
      </div>

      <nav class="nav">
        <template v-for="group in visibleGroups" :key="group.label">
          <div v-if="group.label" class="nav-group">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ active: isActive(item.to) }"
          >
            <el-icon :size="16"><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </router-link>
        </template>
      </nav>

      <div class="sidebar-foot">
        <div class="user">
          <div class="user-avatar">{{ userInitial }}</div>
          <div class="user-meta">
            <div class="user-name">{{ store.user?.name }}</div>
            <div class="user-region">{{ store.displayRegion }}</div>
          </div>
        </div>
        <el-button text size="small" class="logout" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon>
          退出
        </el-button>
      </div>
    </aside>

    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'

const store = useUserStore()
const route = useRoute()
const router = useRouter()

const groups = [
  {
    label: '',
    items: [
      { to: '/dashboard', label: '概览', icon: 'Odometer' },
      { to: '/rules', label: '推送规则', icon: 'Promotion' },
      { to: '/logs', label: '发送记录', icon: 'Tickets' },
    ],
  },
  {
    label: '系统配置',
    adminOnly: true,
    items: [
      // 全省级的配置，只有省级管理员能进
      { to: '/datasources', label: '数据源', icon: 'Coin', provinceOnly: true },
      { to: '/bots', label: '钉钉群', icon: 'ChatDotRound' },
      { to: '/regions', label: '归属地字典', icon: 'MapLocation' },
      { to: '/staff', label: '人员信息', icon: 'User' },
      { to: '/settings', label: '系统设置', icon: 'Setting', provinceOnly: true },
    ],
  },
]

// 跟后端 services/scope.py 的 ROLE_MENUS 对应
function canSee(item) {
  if (store.isAdmin) return true
  if (store.isCityAdmin) return !item.provinceOnly
  // 普通人员：只有概览、推送规则、发送记录
  return ['/dashboard', '/rules', '/logs'].includes(item.to)
}

const visibleGroups = computed(() => {
  // 省级管理员看到全部；地市管理员看到本地管理那一组；普通人员只有基础菜单
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter(canSee),
    }))
    .filter((group) => group.items.length)
})

const userInitial = computed(() => (store.user?.name || '?').slice(0, 1))

function isActive(path) {
  if (path === '/rules') {
    return route.path.startsWith('/rules')
  }
  return route.path === path
}

function handleLogout() {
  store.logout()
  router.push({ name: 'login' })
}
</script>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 220px;
  flex: 0 0 220px;
  background: var(--surface);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 18px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 3px 8px rgba(46, 75, 216, 0.28);
}

.brand-name {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.2px;
  line-height: 1.3;
}

.brand-sub {
  font-size: 10px;
  color: var(--ink-400);
  letter-spacing: 0.6px;
  text-transform: uppercase;
}

.nav {
  flex: 1;
  overflow-y: auto;
  padding: 4px 10px 10px;
}

.nav-group {
  font-size: 11px;
  color: var(--ink-400);
  padding: 16px 8px 6px;
  letter-spacing: 0.4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 8px;
  color: var(--ink-700);
  font-size: 13.5px;
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
  margin-bottom: 2px;
}

.nav-item:hover {
  background: var(--line-soft);
  color: var(--ink-900);
}

.nav-item.active {
  background: var(--brand-50);
  color: var(--brand-600);
  font-weight: 600;
}

.sidebar-foot {
  border-top: 1px solid var(--line-soft);
  padding: 12px;
}

.user {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--brand-50);
  color: var(--brand-600);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 32px;
}

.user-meta {
  min-width: 0;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.user-region {
  font-size: 11px;
  color: var(--ink-500);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.logout {
  width: 100%;
  justify-content: center;
  color: var(--ink-500);
}

.main {
  flex: 1;
  min-width: 0;
}
</style>

