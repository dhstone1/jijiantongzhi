<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">数据文件</h1>
        <p class="page-sub">每天按固定时间扫描目录里的 {前缀}_{YYYYMMDD}.txt，导入本地 SQLite 库并自动注册为全员可见的数据源，可直接配推送规则。</p>
      </div>
    </div>

    <section class="panel" style="margin-bottom: 16px">
      <div class="panel-head">
        <div class="panel-title">扫描配置</div>
      </div>
      <div class="panel-body">
        <div class="config-line">
          <label class="muted">目录</label>
          <el-input v-model="directory" class="config-input" placeholder="例如：D:\数据源（放 {前缀}_{YYYYMMDD}.txt 的文件夹）" />
          <label class="muted">每天扫描</label>
          <el-time-picker v-model="scanTime" format="HH:mm" value-format="HH:mm" placeholder="扫描时间" style="width: 140px" />
          <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
        </div>
        <div class="action-line">
          <el-button :loading="scanning" @click="scan">立即扫描</el-button>
          <el-button type="primary" :loading="importing" @click="importAll">导入全部最新文件</el-button>
        </div>
      </div>
    </section>

    <section class="panel" style="margin-bottom: 16px">
      <div class="panel-head">
        <div class="panel-title">文件类型</div>
        <span class="muted">每种前缀对应一个 SQLite 库（库名 = 前缀），导入时整表覆盖</span>
      </div>
      <div class="panel-body tight">
        <el-table :data="types" v-loading="scanning" style="width: 100%">
          <el-table-column prop="prefix" label="前缀 / 库名" min-width="200" show-overflow-tooltip />
          <el-table-column prop="file_name" label="最新文件" min-width="200" show-overflow-tooltip />
          <el-table-column prop="file_date" label="文件日期" width="105" />
          <el-table-column label="已导入日期" width="105">
            <template #default="{ row }">{{ row.imported_date || '—' }}</template>
          </el-table-column>
          <el-table-column prop="row_count" label="行数" width="80" />
          <el-table-column label="状态" width="105">
            <template #default="{ row }">
              <el-tag
                size="small"
                effect="light"
                :type="row.status === 'current' ? 'success' : row.status === 'imported' ? 'warning' : 'info'"
              >
                {{ statusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <el-button
                text type="primary" size="small"
                :loading="importingPrefix === row.prefix"
                @click="importOne(row.prefix, false)"
              >
                导入
              </el-button>
              <el-button
                text size="small"
                :loading="importingPrefix === row.prefix"
                @click="importOne(row.prefix, true)"
              >
                强制重导
              </el-button>
              <el-button text size="small" @click="goDatasources">数据源</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="!types.length && !scanning" class="empty">
          目录里还没有 {前缀}_{YYYYMMDD}.txt 文件，或尚未扫描
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">导入记录</div>
        <el-select v-model="logPrefix" clearable placeholder="全部前缀" size="small" style="width: 200px" @change="loadLogs">
          <el-option v-for="item in types" :key="item.prefix" :label="item.prefix" :value="item.prefix" />
        </el-select>
      </div>
      <div class="panel-body tight">
        <el-table :data="logs" v-loading="loadingLogs" style="width: 100%">
          <el-table-column prop="created_at" label="时间" width="165" />
          <el-table-column prop="file_name" label="文件" min-width="210" show-overflow-tooltip />
          <el-table-column prop="prefix" label="前缀" min-width="150" show-overflow-tooltip />
          <el-table-column label="状态" width="95">
            <template #default="{ row }">
              <el-tag
                size="small"
                effect="light"
                :type="row.status === 'success' ? 'success' : row.status === 'skipped' ? 'info' : 'danger'"
              >
                {{ logStatusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="row_count" label="行数" width="75" />
          <el-table-column label="耗时" width="95">
            <template #default="{ row }">{{ row.duration_ms }} ms</template>
          </el-table-column>
          <el-table-column prop="error" label="错误" min-width="200" show-overflow-tooltip />
        </el-table>
        <div v-if="!logs.length && !loadingLogs" class="empty">还没有导入记录</div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const router = useRouter()
const directory = ref('')
const scanTime = ref('08:00')
const saving = ref(false)
const scanning = ref(false)
const importing = ref(false)
const importingPrefix = ref('')
const types = ref([])
const logs = ref([])
const loadingLogs = ref(false)
const logPrefix = ref('')

onMounted(async () => {
  try {
    const config = await api.getImportConfig()
    directory.value = config.directory
    scanTime.value = config.scan_time
  } catch {
    scanTime.value = '08:00'
  }
  scan()
  loadLogs()
})

async function saveConfig() {
  if (!directory.value.trim()) return ElMessage.warning('请填写扫描目录')
  saving.value = true
  try {
    await api.saveImportConfig({ directory: directory.value.trim(), scan_time: scanTime.value || '08:00' })
    ElMessage.success('已保存，每日定时任务已更新')
  } finally {
    saving.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const result = await api.scanImports()
    types.value = result.types || []
  } catch {
    types.value = []
  } finally {
    scanning.value = false
  }
}

async function importAll() {
  importing.value = true
  try {
    const result = await api.runImport({ force: false })
    const imported = result.results.filter((item) => item.status === 'success').length
    const failed = result.results.filter((item) => item.status === 'failed').length
    if (failed) ElMessage.warning(`导入完成：成功 ${imported}，失败 ${failed}（见导入记录）`)
    else ElMessage.success(`导入完成：成功 ${imported}，其余跳过`)
  } finally {
    importing.value = false
    scan()
    loadLogs()
  }
}

async function importOne(prefix, force) {
  importingPrefix.value = prefix
  try {
    const result = await api.runImport({ prefix, force })
    const first = result.results[0]
    if (!first) return ElMessage.warning('目录中未找到该前缀的文件')
    if (first.status === 'failed') return ElMessage.error(first.error)
    if (first.status === 'skipped') return ElMessage.success(`「${prefix}」已是最新，跳过（可点强制重导）`)
    ElMessage.success(`「${prefix}」导入完成，共 ${first.row_count} 行`)
  } finally {
    importingPrefix.value = null
    scan()
    loadLogs()
  }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    logs.value = await api.listImportLogs({ prefix: logPrefix.value || '', limit: 100 })
  } finally {
    loadingLogs.value = false
  }
}

function statusText(status) {
  return { current: '已是最新', imported: '有新版本', pending: '未导入' }[status] || status
}

function logStatusText(status) {
  return { success: '成功', skipped: '跳过', failed: '失败' }[status] || status
}

function goDatasources() {
  router.push('/datasources')
}
</script>

<style scoped>
.config-line {
  display: flex;
  align-items: center;
  gap: 10px;
}

.config-input {
  width: 480px;
  max-width: 100%;
}

.action-line {
  margin-top: 14px;
  display: flex;
  gap: 10px;
}
</style>