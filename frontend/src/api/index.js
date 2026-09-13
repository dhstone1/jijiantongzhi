import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const detail = error?.response?.data?.detail
    const message = typeof detail === 'string' ? detail : error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  },
)

export const api = {
  // 身份
  login: (mobile) => http.post('/session/login', { mobile }),

  // 归属地
  listRegions: () => http.get('/regions'),
  createRegion: (data) => http.post('/regions', data),
  updateRegion: (id, data) => http.put(`/regions/${id}`, data),
  deleteRegion: (id) => http.delete(`/regions/${id}`),
  checkRegions: (values) => http.post('/regions/check', { values }),

  // 人员
  listStaff: () => http.get('/staff'),
  createStaff: (data) => http.post('/staff', data),
  updateStaff: (id, data) => http.put(`/staff/${id}`, data),
  deleteStaff: (id) => http.delete(`/staff/${id}`),
  importStaff: (file) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/staff/import', form)
  },

  // 钉钉
  listBots: (mobile) => http.get('/bots', { params: { mobile } }),
  createBot: (data) => http.post('/bots', data),
  updateBot: (id, data) => http.put(`/bots/${id}`, data),
  deleteBot: (id) => http.delete(`/bots/${id}`),
  testBot: (id) => http.post(`/bots/${id}/test`, {}),

  // 数据源
  listDatasources: (mobile) => http.get('/datasources', { params: { mobile } }),
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
  deleteRule: (id) => http.delete(`/rules/${id}`),
  toggleRule: (id) => http.post(`/rules/${id}/toggle`),
  runRule: (id) => http.post(`/rules/${id}/run`),
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

  // 记录
  listLogs: (params) => http.get('/logs', { params }),
  getLog: (id) => http.get(`/logs/${id}`),
  resendLog: (id) => http.post(`/logs/${id}/resend`),
  stats: (mobile) => http.get('/stats', { params: { mobile } }),
}

export default http
