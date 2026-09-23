<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">发送记录</h1>
        <p class="page-sub">每次发送的时间、群、内容快照和错误原因都在这里，失败可以一键重发。</p>
      </div>
      <el-button @click="load">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>

    <div class="panel">
      <div class="panel-body tight">
        <div class="filters">
          <el-input v-model="filters.rule_id" placeholder="规则 ID" clearable style="width: 130px" @change="load" />
          <el-select v-model="filters.status" placeholder="全部结果" clearable style="width: 140px" @change="load">
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-select v-model="filters.limit" style="width: 120px" @change="load">
            <el-option :value="20" label="最近 20 条" />
            <el-option :value="50" label="最近 50 条" />
            <el-option :value="200" label="最近 200 条" />
          </el-select>
        </div>

        <el-table :data="items" v-loading="loading" style="width: 100%">
          <el-table-column prop="rule_name" label="规则" min-width="190" show-overflow-tooltip />
          <el-table-column prop="bot_names" label="发送群" min-width="140" show-overflow-tooltip />
          <el-table-column label="触发" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ triggerLabel(row.trigger) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag :type="row.success ? 'success' : 'danger'" size="small" effect="light">
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="row_count" label="行数" width="80" />
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">{{ row.duration_ms }} ms</template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDetail(row)">详情</el-button>
              <el-button text type="primary" size="small" :loading="resending === row.id" @click="resend(row)">
                重发
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty">还没有发送记录</div>
          </template>
        </el-table>
      </div>
    </div>

    <el-drawer v-model="detailVisible" title="发送详情" size="620px">
      <div v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="规则">{{ detail.rule_name }}</el-descriptions-item>
          <el-descriptions-item label="发送群">{{ detail.bot_names || '—' }}</el-descriptions-item>
          <el-descriptions-item label="触发方式">{{ triggerLabel(detail.trigger) }}</el-descriptions-item>
          <el-descriptions-item label="结果">
            <el-tag :type="detail.success ? 'success' : 'danger'" size="small" effect="light">
              {{ detail.success ? '成功' : '失败' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="数据行数">{{ detail.row_count }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detail.duration_ms }} ms</el-descriptions-item>
          <el-descriptions-item label="时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="detail.error" class="detail-block">
          <div class="detail-title">错误信息</div>
          <el-alert type="error" :closable="false" :title="detail.error" show-icon />
        </div>

        <div v-if="detailImage" class="detail-block">
          <div class="detail-title">推送的图片</div>
          <img class="log-image" :src="detailImage" alt="推送的报表图片" />
        </div>

        <div v-if="detail.message_text" class="detail-block">
          <div class="detail-title">消息快照</div>
          <pre class="message-preview">{{ detail.message_text }}</pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const items = ref([])
const loading = ref(false)
const resending = ref(null)
const detailVisible = ref(false)
const detail = ref(null)

const filters = reactive({ rule_id: '', status: '', limit: 50 })

// 图片消息的快照里是 ![](地址)，这里挑出来展示。
// 地址可能是钉钉才访问得到的局域网地址，统一换成本站的相对路径。
const detailImage = computed(() => {
  const text = detail.value?.message_text || ''
  const match = /!\[[^\]]*\]\((\S+?)\)/.exec(text)
  if (!match) return ''
  const url = match[1]
  const index = url.indexOf('/static/')
  if (index < 0) return url
  const base = (import.meta.env.BASE_URL || '/').replace(/\/$/, '')
  return `${base}${url.slice(index)}`
})

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await api.listLogs({
      rule_id: filters.rule_id || undefined,
      status: filters.status || undefined,
      limit: filters.limit,
    })
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  detail.value = await api.getLog(row.id)
  detailVisible.value = true
}

async function resend(row) {
  resending.value = row.id
  try {
    const result = await api.resendLog(row.id)
    if (result.success) {
      ElMessage.success('重发成功')
    } else {
      ElMessage.error(result.error || '重发失败')
    }
    load()
  } finally {
    resending.value = null
  }
}

function triggerLabel(value) {
  return { auto: '定时', manual: '手动', retry: '重发', test: '测试' }[value] || value
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 19)
}
</script>

<style scoped>
.filters {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.detail-block {
  margin-top: 18px;
}

.detail-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-700);
  margin-bottom: 8px;
}

.log-image {
  display: block;
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
</style>

