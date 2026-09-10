<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">概览</h1>
        <p class="page-sub">当前登录：{{ store.user?.name }} · {{ store.displayRegion }}</p>
      </div>
      <el-button type="primary" @click="router.push({ name: 'rule-new' })">
        <el-icon><Plus /></el-icon> 新建推送规则
      </el-button>
    </div>

    <div class="stat-grid">
      <div v-for="card in cards" :key="card.label" class="stat-card">
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value">
          {{ card.value }}
          <span v-if="card.suffix" class="stat-suffix">{{ card.suffix }}</span>
        </div>
        <div class="stat-foot">{{ card.foot }}</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">最近的发送记录</div>
        <el-button text type="primary" size="small" @click="router.push({ name: 'logs' })">查看全部</el-button>
      </div>
      <div class="panel-body tight">
        <el-table :data="logs" style="width: 100%">
          <el-table-column label="规则" min-width="200" prop="rule_name" show-overflow-tooltip />
          <el-table-column label="发送群" min-width="140" prop="bot_names" show-overflow-tooltip />
          <el-table-column label="结果" width="90">
            <template #default="{ row }">
              <el-tag :type="row.success ? 'success' : 'danger'" size="small" effect="light">
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="行数" width="80" prop="row_count" />
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">{{ row.duration_ms }} ms</template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <template #empty>
            <div class="empty">还没有发送记录</div>
          </template>
        </el-table>
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">开始使用</div>
      </div>
      <div class="panel-body">
        <div class="steps">
          <div v-for="(step, index) in steps" :key="step.title" class="step">
            <div class="step-no">{{ index + 1 }}</div>
            <div>
              <div class="step-title">{{ step.title }}</div>
              <div class="step-desc">{{ step.desc }}</div>
              <el-link v-if="step.to" type="primary" :underline="false" @click="router.push(step.to)">
                {{ step.action }} →
              </el-link>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useUserStore } from '../stores/user'

const router = useRouter()
const store = useUserStore()

const stats = ref({})
const logs = ref([])

const steps = [
  {
    title: '配置数据源',
    desc: '填入 PostgreSQL 只读账号，系统会自动读取表结构和字段说明。',
    to: { name: 'datasources' },
    action: '去配置',
  },
  {
    title: '维护归属地字典',
    desc: '把同一区县的各种写法（襄都 / 桥东区）配成别名，权限过滤才准。',
    to: { name: 'regions' },
    action: '去维护',
  },
  {
    title: '添加钉钉群',
    desc: '粘贴群机器人的 Webhook 地址，点测试确认能收到消息。',
    to: { name: 'bots' },
    action: '去添加',
  },
  {
    title: '导入人员信息',
    desc: '姓名、手机号、归属地。手机号既是登录凭据，也是 @ 人的依据。',
    to: { name: 'staff' },
    action: '去导入',
  },
  {
    title: '新建推送规则',
    desc: '选表、选字段、配条件，右侧实时预览，保存后就自动推送。',
    to: { name: 'rule-new' },
    action: '去创建',
  },
]

const cards = computed(() => [
  {
    label: '推送规则',
    value: stats.value.total_rules ?? 0,
    suffix: `启用 ${stats.value.enabled_rules ?? 0}`,
    foot: '按归属地隔离',
  },
  {
    label: '今日发送',
    value: stats.value.today_logs ?? 0,
    suffix: '次',
    foot: `累计 ${stats.value.total_logs ?? 0} 次`,
  },
  {
    label: '发送失败',
    value: stats.value.failed_logs ?? 0,
    suffix: '次',
    foot: '可一键重发',
  },
  {
    label: '数据源',
    value: stats.value.datasource_count ?? 0,
    suffix: '个',
    foot: '只读连接',
  },
  {
    label: '钉钉群',
    value: stats.value.bot_count ?? 0,
    suffix: '个',
    foot: 'Webhook 机器人',
  },
  {
    label: '定时任务',
    value: stats.value.scheduler_jobs?.length ?? 0,
    suffix: '个',
    foot: '小时 / 每天 / 每周',
  },
])

onMounted(async () => {
  stats.value = await api.stats(store.user?.mobile)
  logs.value = await api.listLogs({ limit: 8 })
})

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.stat-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 16px 18px;
}

.stat-label {
  font-size: 12.5px;
  color: var(--ink-500);
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.5px;
  margin: 8px 0 6px;
  color: var(--ink-900);
}

.stat-suffix {
  font-size: 12px;
  font-weight: 400;
  color: var(--ink-400);
  margin-left: 4px;
}

.stat-foot {
  font-size: 11.5px;
  color: var(--ink-400);
}

.steps {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 18px;
}

.step {
  display: flex;
  gap: 12px;
}

.step-no {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  border-radius: 50%;
  background: var(--brand-50);
  color: var(--brand-600);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-title {
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: 4px;
}

.step-desc {
  font-size: 12.5px;
  color: var(--ink-500);
  line-height: 1.7;
  margin-bottom: 6px;
}
</style>

