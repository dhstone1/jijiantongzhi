import axios from 'axios'
import { ElMessage } from 'element-plus'

// 站点可能挂在子路径下（vite base），接口地址要跟着走：
// base=/ -> /api ；base=/jijiantongzhi/ -> /jijiantongzhi/api
const APP_BASE = import.meta.env.BASE_URL || '/'
const API_BASE = `${APP_BASE.replace(/\/$/, '')}/api`

const http = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
})

// 后端没有登录态，所有 /api 请求都要带一个已登记的手机号，否则一律 401。
// 放在拦截器里统一注入，免得某个调用点忘了传。
const USER_KEY = 'jijiantongzhi.user'

function currentMobile() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')?.mobile || ''
  } catch {
    return ''
  }
}

http.interceptors.request.use((config) => {
  const mobile = currentMobile()
  if (!mobile) return config
  // 登录接口自己带 body，不需要查询参数
  if (config.url === '/session/login') return config
  config.params = { mobile, ...(config.params || {}) }
  return config
})

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 身份失效（被删号 / 换了浏览器）时退回登录页，别让人对着错误发呆
    if (error?.response?.status === 401) {
      localStorage.removeItem(USER_KEY)
      if (!window.location.hash.startsWith('#/login')) {
        window.location.hash = '#/login'
      }
    }
    const detail = error?.response?.data?.detail
    const message = typeof detail === 'string' ? detail : error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

function withMe(params = {}) {
  return { mobile: currentMobile(), ...params }
}

// 模板下载要走浏览器原生下载，用 axios 反而拿不到 Content-Disposition 里的文件名
export function downloadTemplate(kind) {
  const params = new URLSearchParams({ mobile: currentMobile() })
  window.location.href = `${API_BASE}/templates/${kind}?${params.toString()}`
}

export const api = {
  // 身份
  login: (mobile) => http.post('/session/login', { mobile }),

  // 归属地
  listRegions: () => http.get('/regions', { params: withMe() }),
  createRegion: (data) => http.post('/regions', data, { params: withMe() }),
  updateRegion: (id, data) => http.put(`/regions/${id}`, data, { params: withMe() }),
  deleteRegion: (id) => http.delete(`/regions/${id}`, { params: withMe() }),
  checkRegions: (values) => http.post('/regions/check', { values }),

  // 人员
  listStaff: () => http.get('/staff', { params: withMe() }),
  createStaff: (data) => http.post('/staff', data, { params: withMe() }),
  updateStaff: (id, data) => http.put(`/staff/${id}`, data, { params: withMe() }),
  deleteStaff: (id) => http.delete(`/staff/${id}`, { params: withMe() }),
  importStaff: (file) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/staff/import', form, { params: withMe() })
  },
  importRegions: (file) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/regions/import', form, { params: withMe() })
  },

  // 钉钉
  listBots: (mobile) => http.get('/bots', { params: withMe({ mobile: mobile ?? currentMobile() }) }),
  createBot: (data) => http.post('/bots', data, { params: withMe() }),
  updateBot: (id, data) => http.put(`/bots/${id}`, data, { params: withMe() }),
  deleteBot: (id) => http.delete(`/bots/${id}`, { params: withMe() }),
  testBot: (id) => http.post(`/bots/${id}/test`, {}),

  // 数据源
  listDatasources: (mobile) => http.get('/datasources', { params: withMe({ mobile: mobile ?? currentMobile() }) }),
  createDatasource: (data) => http.post('/datasources', data),
  updateDatasource: (id, data) => http.put(`/datasources/${id}`, data),
  deleteDatasource: (id) => http.delete(`/datasources/${id}`),
  testDatasource: (id) => http.post(`/datasources/${id}/test`),
  listTables: (id, keyword = '') => http.get(`/datasources/${id}/tables`, { params: { keyword } }),
  listColumns: (id, table) => http.get(`/datasources/${id}/columns`, { params: { table } }),
  previewTable: (id, table, limit = 20) =>
    http.get(`/datasources/${id}/preview`, { params: { table, limit } }),
  refreshSchema: (id) => http.post(`/datasources/${id}/refresh`),
  getSchema: (id) => http.get(`/datasources/${id}/schema`),

  // 资源可见权限（数据源 / 钉钉群分别对哪些人可见）
  listPermissions: (resourceType, resourceId) =>
    http.get('/permissions', {
      params: { resource_type: resourceType, resource_id: resourceId },
    }),
  grantPermissions: (data) => http.post('/permissions', data),

  // 规则
  listRules: (mobile) => http.get('/rules', { params: { mobile } }),
  getRule: (id) => http.get(`/rules/${id}`),
  createRule: (data, mobile) => http.post('/rules', data, { params: { mobile } }),
  updateRule: (id, data, mobile) => http.put(`/rules/${id}`, data, { params: { mobile } }),
  deleteRule: (id) => http.delete(`/rules/${id}`, { params: withMe() }),
  toggleRule: (id) => http.post(`/rules/${id}/toggle`, {}, { params: withMe() }),
  runRule: (id) => http.post(`/rules/${id}/run`, {}, { params: withMe() }),
  previewRule: (data) => http.post('/rules/preview', data),
  suggestTemplate: (data) => http.post('/rules/suggest-template', data),
  parseSample: (file, dataSourceId) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/samples/parse', form, {
      params: dataSourceId ? { data_source_id: dataSourceId } : {},
    })
  },

  // 系统设置
  getSettings: () => http.get('/settings'),
  updateSettings: (data) => http.put('/settings', data),
  testImageHost: () => http.post('/settings/test-image-host'),

  // 数据文件导入
  getImportConfig: () => http.get('/imports/config'),
  saveImportConfig: (data) => http.put('/imports/config', data),
  scanImports: () => http.post('/imports/scan'),
  runImport: (data) => http.post('/imports/import', data),
  listImportLogs: (params) => http.get('/imports/logs', { params }),

  // 记录
  listLogs: (params) => http.get('/logs', { params: withMe(params) }),
  getLog: (id) => http.get(`/logs/${id}`, { params: withMe() }),
  resendLog: (id) => http.post(`/logs/${id}/resend`, {}, { params: withMe() }),
  stats: (mobile) => http.get('/stats', { params: { mobile } }),
}

export default http
