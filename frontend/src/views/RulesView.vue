<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">推送规则</h1>
        <p class="page-sub">每条规则就是一条自动化的数据通报。点「新建规则」，选表选字段就能配好。</p>
      </div>
      <el-button type="primary" @click="router.push({ name: 'rule-new' })">
        <el-icon><Plus /></el-icon> 新建规则
      </el-button>
    </div>

    <div class="panel">
      <div class="panel-body tight">
        <el-table :data="rules" v-loading="loading" style="width: 100%">
          <el-table-column prop="name" label="规则名称" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="rule-name">
                {{ row.name }}
                <el-tag v-if="row.image && row.image.enabled" size="small" type="warning" effect="plain">
                  图片
                </el-tag>
              </div>
              <div class="rule-sub">{{ row.table_name }}</div>
            </template>
          </el-table-column>
          <el-table-column label="归属地" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.region_name" size="small" type="info">{{ row.region_name }}</el-tag>
              <span v-else class="muted">全部</span>
            </template>
          </el-table-column>
          <el-table-column label="发送群" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.bot_ids.length">{{ botNames(row.bot_ids) }}</span>
              <span v-else class="muted">未配置</span>
            </template>
          </el-table-column>
          <el-table-column label="频率" width="130">
            <template #default="{ row }">{{ scheduleText(row) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" size="small" effect="light">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近发送" width="170">
            <template #default="{ row }">
              <div v-if="row.last_run_at" class="last-run">
                <span>{{ formatTime(row.last_run_at) }}</span>
                <el-tag :type="row.last_status === 'success' ? 'success' : 'danger'" size="small" effect="plain">
                  {{ row.last_status === 'success' ? '成功' : '失败' }}
                </el-tag>
              </div>
              <span v-else class="muted">尚未发送</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="router.push({ name: 'rule-edit', params: { id: row.id } })">
                编辑
              </el-button>
              <el-button text type="primary" size="small" :loading="running === row.id" @click="runNow(row)">
                立即发送
              </el-button>
              <el-button text size="small" @click="toggle(row)">{{ row.enabled ? '停用' : '启用' }}</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty">
              还没有推送规则。<el-link type="primary" @click="router.push({ name: 'rule-new' })">立即创建</el-link>
            </div>
          </template>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="resultVisible" title="发送结果" width="680px">
      <div v-if="runResult">
        <el-alert
          :type="runResult.success ? 'success' : 'error'"
          :title="runResult.message || (runResult.success ? '执行成功' : '执行失败')"
          :description="runResult.error || ''"
          :closable="false"
          show-icon
        />
        <div v-if="runResult.warnings && runResult.warnings.length" class="result-block">
          <div class="result-title">过程提示</div>
          <div v-for="(msg, i) in runResult.warnings" :key="i" class="warn-line">· {{ msg }}</div>
        </div>
        <div v-if="runResult.rendered" class="result-block">
          <div class="result-title">消息内容</div>
          <pre class="message-preview">{{ runResult.rendered }}</pre>
        </div>
      </div>
      <template #footer>
        <el-button @click="resultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { useUserStore } from '../stores/user'

const router = useRouter()
const store = useUserStore()

const rules = ref([])
const bots = ref([])
const loading = ref(false)
const running = ref(null)
const resultVisible = ref(false)
const runResult = ref(null)

const WEEK = { mon: '周一', tue: '周二', wed: '周三', thu: '周四', fri: '周五', sat: '周六', sun: '周日' }

onMounted(load)

async function load() {
  loading.value = true
  try {
    const [ruleList, botList] = await Promise.all([
      api.listRules(store.user?.mobile),
      api.listBots(store.user?.mobile),
    ])
    rules.value = ruleList
    bots.value = botList
  } finally {
    loading.value = false
  }
}

function botNames(ids) {
  return ids
    .map((id) => bots.value.find((b) => b.id === id)?.name)
    .filter(Boolean)
    .join('、')
}

function scheduleText(row) {
  const cfg = row.schedule || {}
  if (row.schedule_type === 'hourly') return `每 ${cfg.interval_hours || 1} 小时`
  if (row.schedule_type === 'daily') {
    return `每天 ${String(cfg.hour ?? 8).padStart(2, '0')}:${String(cfg.minute ?? 30).padStart(2, '0')}`
  }
  if (row.schedule_type === 'weekly') {
    const time = `${String(cfg.hour ?? 8).padStart(2, '0')}:${String(cfg.minute ?? 30).padStart(2, '0')}`
    return `每${WEEK[cfg.day_of_week] || '周一'} ${time}`
  }
  return '仅手动'
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

async function runNow(row) {
  running.value = row.id
  try {
    runResult.value = await api.runRule(row.id)
    resultVisible.value = true
    load()
  } finally {
    running.value = null
  }
}

async function toggle(row) {
  const result = await api.toggleRule(row.id)
  row.enabled = result.enabled
  ElMessage.success(result.enabled ? '已启用' : '已停用')
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除规则「${row.name}」？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await api.deleteRule(row.id)
  ElMessage.success('已删除')
  load()
}
</script>

<style scoped>
.rule-name {
  font-weight: 600;
  color: var(--ink-900);
}

.rule-sub {
  font-size: 11.5px;
  color: var(--ink-400);
  margin-top: 2px;
}

.last-run {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
}

.result-block {
  margin-top: 16px;
}

.result-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-700);
  margin-bottom: 8px;
}

.warn-line {
  font-size: 12px;
  color: #b54708;
  line-height: 1.8;
}
</style>

