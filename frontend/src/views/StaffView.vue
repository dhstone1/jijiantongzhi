<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">人员信息</h1>
        <p class="page-sub">
          手机号既是进入系统的身份凭据，也是钉钉 @ 人的依据；归属地决定这个人能看到哪些数据。
        </p>
      </div>
      <div class="head-actions">
        <el-upload :auto-upload="false" :show-file-list="false" accept=".xlsx,.xlsm,.csv" :on-change="handleImport">
          <el-button :loading="importing">
            <el-icon><Upload /></el-icon> 从 Excel 导入
          </el-button>
        </el-upload>
        <el-button type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon> 添加人员
        </el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="Excel 导入格式"
      description="第一行为表头，需要包含「姓名」和「手机号」两列，可选「归属地」「岗位」。归属地会自动按字典归一化，识别不了的会在导入结果里提示。"
      style="margin-bottom: 16px"
    />

    <div class="panel">
      <div class="panel-body tight">
        <el-table :data="items" v-loading="loading" style="width: 100%">
          <el-table-column prop="name" label="姓名" width="120" />
          <el-table-column prop="mobile" label="手机号" width="150">
            <template #default="{ row }">
              <span class="mono">{{ row.mobile }}</span>
            </template>
          </el-table-column>
          <el-table-column label="归属地" width="130">
            <template #default="{ row }">
              <el-tag v-if="row.region_name" size="small" effect="plain">{{ row.region_name }}</el-tag>
              <span v-else class="muted">全部</span>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="110">
            <template #default="{ row }">
              <el-tag :type="row.role === 'admin' ? 'warning' : 'info'" size="small" effect="light">
                {{ row.role === 'admin' ? '管理员' : '普通用户' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="position" label="岗位" min-width="140" />
          <el-table-column label="接收告警" width="100">
            <template #default="{ row }">
              <el-tag :type="row.receive_alert ? 'success' : 'info'" size="small" effect="plain">
                {{ row.receive_alert ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDialog(row)">编辑</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑人员' : '添加人员'" width="560px">
      <el-form label-width="90px" label-position="left">
        <el-form-item label="姓名">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.mobile" maxlength="11" placeholder="钉钉 @ 人也用这个号码" />
        </el-form-item>
        <el-form-item label="归属地">
          <el-select v-model="form.region_name" placeholder="全部归属地" clearable filterable style="width: 100%">
            <el-option label="全部归属地" value="" />
            <el-option v-for="r in regions" :key="r.id" :label="r.standard_name" :value="r.standard_name" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role">
            <el-radio-button value="user">普通用户</el-radio-button>
            <el-radio-button value="admin">管理员</el-radio-button>
          </el-radio-group>
          <div class="hint">管理员可以看到全部归属地的数据与规则。</div>
        </el-form-item>
        <el-form-item label="岗位">
          <el-input v-model="form.position" placeholder="例如：网络运营" />
        </el-form-item>
        <el-form-item label="接收告警">
          <el-switch v-model="form.receive_alert" />
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
const regions = ref([])
const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)

const form = reactive({
  name: '',
  mobile: '',
  region_name: '',
  role: 'user',
  position: '',
  receive_alert: true,
})

onMounted(load)

async function load() {
  loading.value = true
  try {
    const [staff, regionList] = await Promise.all([api.listStaff(), api.listRegions()])
    items.value = staff
    regions.value = regionList
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  editing.value = row || null
  Object.assign(form, {
    name: row?.name || '',
    mobile: row?.mobile || '',
    region_name: row?.region_name || '',
    role: row?.role || 'user',
    position: row?.position || '',
    receive_alert: row?.receive_alert ?? true,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim() || !form.mobile.trim()) return ElMessage.warning('请填写姓名和手机号')
  saving.value = true
  try {
    if (editing.value) {
      await api.updateStaff(editing.value.id, { ...form })
      ElMessage.success('已保存')
    } else {
      await api.createStaff({ ...form })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除「${row.name}」？`, '删除确认', { type: 'warning' })
  await api.deleteStaff(row.id)
  ElMessage.success('已删除')
  load()
}

async function handleImport(uploadFile) {
  const file = uploadFile.raw
  if (!file) return
  importing.value = true
  try {
    const result = await api.importStaff(file)
    let message = `导入完成：新增 ${result.created} 人，更新 ${result.updated} 人`
    if (result.unknown_regions?.length) {
      message += `；未识别归属地：${result.unknown_regions.join('、')}`
    }
    ElMessage.success(message)
    load()
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
}
</style>

