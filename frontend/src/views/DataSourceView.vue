<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">数据源</h1>
        <p class="page-sub">配置公共数据库的只读连接。系统只做 SELECT，不会修改任何业务数据。</p>
      </div>
      <el-button type="primary" @click="openDialog()">
        <el-icon><Plus /></el-icon> 添加数据源
      </el-button>
    </div>

    <div class="panel">
      <div class="panel-body tight">
        <el-table :data="items" v-loading="loading" style="width: 100%">
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.db_type === 'sqlite' ? '本地库' : 'PostgreSQL' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="detail" label="连接" min-width="240" show-overflow-tooltip />
          <el-table-column label="最近测试" width="220">
            <template #default="{ row }">
              <div v-if="row.last_test_at" class="test-line">
                <el-tag :type="row.last_test_ok ? 'success' : 'danger'" size="small" effect="light">
                  {{ row.last_test_ok ? '连通' : '失败' }}
                </el-tag>
                <span class="muted">{{ row.last_test_msg }}</span>
              </div>
              <span v-else class="muted">未测试</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" :loading="testing === row.id" @click="test(row)">
                测试连接
              </el-button>
              <el-button text type="primary" size="small" @click="browse(row)">浏览数据</el-button>
              <el-button text size="small" @click="openDialog(row)">编辑</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑数据源' : '添加数据源'" width="620px">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="连接配置" name="basic">
          <el-form label-width="96px" label-position="left">
            <el-form-item label="名称">
              <el-input v-model="form.name" placeholder="例如：网络运营库" />
            </el-form-item>
            <el-form-item label="数据库类型">
              <el-radio-group v-model="form.db_type">
                <el-radio-button value="postgresql">PostgreSQL</el-radio-button>
                <el-radio-button value="sqlite">本地文件库</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <template v-if="form.db_type === 'postgresql'">
              <el-form-item label="主机">
                <el-input v-model="form.host" placeholder="例如：10.0.0.10" />
              </el-form-item>
              <el-form-item label="端口">
                <el-input-number v-model="form.port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="数据库">
                <el-input v-model="form.database" placeholder="数据库名" />
              </el-form-item>
              <el-form-item label="只读账号">
                <el-input v-model="form.username" placeholder="用户名" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="form.password" type="password" show-password placeholder="留空表示不修改" />
              </el-form-item>
            </template>

            <template v-else>
              <el-form-item label="文件路径">
                <el-input v-model="form.file_path" placeholder="例如：G:\\data\\demo.db" />
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>
        <el-tab-pane v-if="store.isAdmin" label="可见权限" name="perm">
          <div class="hint" style="margin-bottom: 10px">
            一个都不勾表示所有人都能用这个数据源；勾选后只有这些人员在建规则时能选到它。
          </div>
          <el-select
            v-model="permittedMobiles"
            multiple
            filterable
            clearable
            placeholder="搜索姓名或手机号"
            style="width: 100%"
          >
            <el-option
              v-for="person in staffList"
              :key="person.key"
              :label="person.label"
              :value="person.key"
            />
          </el-select>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 数据浏览抽屉 -->
    <el-drawer v-model="browseVisible" :title="`浏览数据 · ${current?.name || ''}`" size="72%">
      <div class="browse">
        <div class="table-list">
          <el-input v-model="keyword" placeholder="搜索表名" clearable size="small" style="margin-bottom: 10px" />
          <div
            v-for="t in filteredTables"
            :key="t.name"
            class="table-item"
            :class="{ active: t.name === currentTable }"
            @click="selectTable(t.name)"
          >
            <el-icon><Grid /></el-icon>
            <span class="table-name">{{ t.name }}</span>
            <span class="table-kind">{{ t.kind === 'view' ? '视图' : '表' }}</span>
          </div>
          <div v-if="!filteredTables.length" class="empty">暂无数据表</div>
        </div>

        <div class="table-detail">
          <template v-if="currentTable">
            <div class="detail-head">
              <strong>{{ currentTable }}</strong>
              <span class="muted">{{ tableColumns.length }} 个字段</span>
            </div>
            <el-table :data="tableColumns" size="small" border max-height="240" style="margin-bottom: 16px">
              <el-table-column prop="name" label="字段" min-width="150" />
              <el-table-column prop="type" label="类型" min-width="130" />
              <el-table-column prop="comment" label="注释" min-width="140" />
            </el-table>

            <div class="detail-head">
              <strong>前 {{ previewLimit }} 行</strong>
            </div>
            <el-table :data="previewRows" size="small" border max-height="360">
              <el-table-column
                v-for="col in previewColumns"
                :key="col.key"
                :prop="col.key"
                :label="col.label"
                min-width="120"
                show-overflow-tooltip
              />
            </el-table>
          </template>
          <div v-else class="empty">请在左侧选择一张表</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useUserStore } from '../stores/user'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const items = ref([])
const loading = ref(false)
const testing = ref(null)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const browseVisible = ref(false)
const current = ref(null)
const tables = ref([])
const keyword = ref('')
const currentTable = ref('')
const tableColumns = ref([])
const previewColumns = ref([])
const previewRows = ref([])
const previewLimit = ref(20)

const form = reactive({
  name: '',
  db_type: 'postgresql',
  host: '',
  port: 5432,
  database: '',
  username: '',
  password: '',
  file_path: '',
  is_active: true,
})

const store = useUserStore()
const staffList = ref([])
const permittedMobiles = ref([])
const activeTab = ref('basic')

const filteredTables = computed(() => {
  if (!keyword.value) return tables.value
  const kw = keyword.value.toLowerCase()
  return tables.value.filter((t) => t.name.toLowerCase().includes(kw))
})

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await api.listDatasources(store.user?.mobile)
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  editing.value = row || null
  activeTab.value = 'basic'
  Object.assign(form, {
    name: row?.name || '',
    db_type: row?.db_type || 'postgresql',
    host: row?.host || '',
    port: row?.port || 5432,
    database: row?.database || '',
    username: row?.username || '',
    password: '',
    file_path: row?.file_path || '',
    is_active: row?.is_active ?? true,
  })
  permittedMobiles.value = []
  Promise.all([
    api.listStaff(),
    row ? api.listPermissions('datasource', row.id) : [],
  ]).then(([staff, perms]) => {
    staffList.value = staff.map((s) => ({ key: s.mobile, label: s.name + '(' + s.mobile + ')' }))
    permittedMobiles.value = perms.map((p) => p.mobile)
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.name.trim()) return ElMessage.warning('请填写名称')
  saving.value = true
  try {
    let dsId = editing.value?.id
    if (editing.value) {
      await api.updateDatasource(dsId, { ...form })
    } else {
      dsId = (await api.createDatasource({ ...form })).id
    }
    await api.grantPermissions({
      resource_type: 'datasource',
      resource_id: dsId,
      mobiles: permittedMobiles.value,
    })
    ElMessage.success(editing.value ? '已保存' : '已创建')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function test(row) {
  testing.value = row.id
  try {
    const result = await api.testDatasource(row.id)
    ElMessage.success(result.message)
    load()
  } catch {
    load()
  } finally {
    testing.value = null
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除数据源「${row.name}」？`, '删除确认', { type: 'warning' })
  await api.deleteDatasource(row.id)
  ElMessage.success('已删除')
  load()
}

async function browse(row) {
  current.value = row
  browseVisible.value = true
  currentTable.value = ''
  tableColumns.value = []
  previewRows.value = []
  tables.value = await api.listTables(row.id)
}

async function selectTable(name) {
  currentTable.value = name
  const [cols, pv] = await Promise.all([
    api.listColumns(current.value.id, name),
    api.previewTable(current.value.id, name, previewLimit.value),
  ])
  tableColumns.value = cols
  // 预览接口给的是「按字段顺序排的数组」，el-table 要的是对象，这里按下标映射成对象。
  // key 用下标而不是字段名，视图里出现同名字段也不会互相覆盖。
  previewColumns.value = pv.columns.map((name, index) => ({ key: `c${index}`, label: name }))
  previewRows.value = pv.rows.map((row) => {
    const item = {}
    pv.columns.forEach((_, index) => {
      item[`c${index}`] = row[index]
    })
    return item
  })
}
</script>

<style scoped>
.test-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.browse {
  display: flex;
  gap: 16px;
  height: 100%;
}

.table-list {
  width: 250px;
  flex: 0 0 250px;
  border-right: 1px solid var(--line-soft);
  padding-right: 14px;
  overflow-y: auto;
}

.table-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 9px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 13px;
  color: var(--ink-700);
}

.table-item:hover {
  background: var(--line-soft);
}

.table-item.active {
  background: var(--brand-50);
  color: var(--brand-600);
  font-weight: 600;
}

.table-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-kind {
  font-size: 10.5px;
  color: var(--ink-400);
}

.table-detail {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.detail-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
}
</style>

