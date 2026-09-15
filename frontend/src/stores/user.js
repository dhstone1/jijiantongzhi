import { defineStore } from 'pinia'

const STORAGE_KEY = 'jijiantongzhi.user'

// 跟后端 services/scope.py 保持一致
export const ROLE_PROVINCE = 'province_admin'
export const ROLE_CITY = 'city_admin'
export const ROLE_USER = 'user'

export const ROLE_OPTIONS = [
  { value: ROLE_PROVINCE, label: '省级管理员', hint: '全省范围，所有权限' },
  { value: ROLE_CITY, label: '地市管理员', hint: '只能管本地市的规则、记录、人员、归属地、钉钉群' },
  { value: ROLE_USER, label: '普通人员', hint: '只能看本地市的规则和发送记录' },
]

function readStored() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
  } catch {
    return null
  }
}

export const useUserStore = defineStore('user', {
  state: () => ({
    user: readStored(),
  }),
  getters: {
    isLoggedIn: (state) => !!state.user,
    role: (state) => state.user?.role || ROLE_USER,
    // 省级管理员
    isAdmin: (state) => state.user?.role === ROLE_PROVINCE,
    isProvinceAdmin: (state) => state.user?.role === ROLE_PROVINCE,
    // 地市管理员
    isCityAdmin: (state) => state.user?.role === ROLE_CITY,
    // 能进「归属地字典 / 人员信息 / 钉钉群」这类本地管理页
    canManageLocal: (state) =>
      state.user?.role === ROLE_PROVINCE || state.user?.role === ROLE_CITY,
    // 能建 / 改规则
    canManageRules: (state) =>
      state.user?.role === ROLE_PROVINCE || state.user?.role === ROLE_CITY,
    roleLabel: (state) => state.user?.role_label || '普通人员',
    // 后端的可见归属地集合；null 表示不限
    scopeRegions: (state) => state.user?.scope_regions ?? null,
    displayRegion: (state) => state.user?.region_name || '全部归属地',
  },
  actions: {
    setUser(user) {
      this.user = user
      localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    },
    logout() {
      this.user = null
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})
