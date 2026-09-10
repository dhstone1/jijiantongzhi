<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">钉钉群</h1>
        <p class="page-sub">
          在钉钉群里添加「自定义机器人」，把 Webhook 地址和加签密钥填进来即可。
        </p>
      </div>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon> 添加钉钉群
      </el-button>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="@ 人的前提"
      description="使用钉钉自定义机器人 @ 人，手机号必须在该机器人所在企业的通讯录里能匹配到，否则消息照常发送但不会真正 @ 到人。建议先配置一个群做测试。"
      style="margin-bottom: 16px"
    />

    <div class="panel">
      <div class="panel-body tight">
        <el-table :data="items" v-loading="loading" style="width: 100%">
          <el-table-column prop="name" label="群名称" min-width="160" />
          <el-table-column prop="webhook" label="Webhook" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.webhook }}</span>
            </template>
          </el-table-column>
          <el-table-column label="加签" width="90">
            <template #default="{ row }">
              <el-tag :type="row.has_secret ? 'success' : 'info'" size="small" effect="plain">
                {{ row.has_secret ? '已配置' : '未配置' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近测试" width="220">
            <template #default="{ row }">
              <div v-if="row.last_test_at" class="test-line">
                <el-tag :type="row.last_test_ok ? 'success' : 'danger'" size="small" effect="light">
                  {{ row.last_test_ok ? '成功' : '失败' }}
                </el-tag>
                <span class="muted">{{ row.last_test_msg }}</span>
              </div>
              <span v-else class="muted">未测试</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" :loading="testing === row.id" @click="test(row)">
                发送测试
              </el-button>
              <el-button text size="small" @click="openDialog(row)">编辑</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑钉钉群' : '添加钉钉群'" width="600px">
      <el-form label-width="100px" label-position="left">
        <el-form-item label="群名称">
          <el-input v-model="form.name" placeholder="例如：网络运营日报群" />
        </el-form-item>
        <el-form-item label="Webhook">
          <el-input
            v-model="form.webhook"
            type="textarea"
            :rows="2"
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
          />
        </el-form-item>
        <el-form-item label="加签密钥">
          <el-input v-model="form.secret" type="password" show-password placeholder="SEC 开头，留空表示不修改" />
          <div class="hint">机器人安全设置选择「加签」时才需要填写。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const items = ref([])
const loading = ref(false)
const testing = ref(null)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)

const form = reactive({ name: '', webhook: '', secret: '', is_active: true })

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await api.listBots()
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  editing.value = row || null
  Object.assign(form, {
    name: row?.name || '',
    webhook: row?.webhook || '',
    secret: '',
    is_active: row?.is_active ?? true,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写群名称')
  if (!editing.value && !form.webhook.trim()) return ElMessage.warning('请填写 Webhook 地址')
  saving.value = true
  try {
    if (editing.value) {
      await api.updateBot(editing.value.id, { ...form })
      ElMessage.success('已保存')
    } else {
      await api.createBot({ ...form })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function test(row) {
  testing.value = row.id
  try {
    await api.testBot(row.id)
    ElMessage.success('测试消息已发送，请到群里确认')
    load()
  } catch {
    load()
  } finally {
    testing.value = null
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除「${row.name}」？`, '删除确认', { type: 'warning' })
  await api.deleteBot(row.id)
  ElMessage.success('已删除')
  load()
}
</script>

<style scoped>
.test-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
</style>

