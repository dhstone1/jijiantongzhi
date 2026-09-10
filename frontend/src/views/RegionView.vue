<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">归属地字典</h1>
        <p class="page-sub">
          报表里同一个区县可能有多种写法（襄都 / 桥东区、内邱 / 内丘）。把它们配成别名，
          归属地权限和 @ 人才不会漏。
        </p>
      </div>
      <div class="head-actions">
        <el-button @click="checkerVisible = true">
          <el-icon><Search /></el-icon> 名称检查
        </el-button>
        <el-button type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon> 添加归属地
        </el-button>
      </div>
    </div>

    <div class="panel">
      <div class="panel-body tight">
        <el-table :data="items" v-loading="loading" style="width: 100%">
          <el-table-column prop="standard_name" label="标准名" width="140">
            <template #default="{ row }">
              <strong>{{ row.standard_name }}</strong>
            </template>
          </el-table-column>
          <el-table-column prop="short_name" label="简称" width="110" />
          <el-table-column label="别名（报表里出现的其他写法）" min-width="280">
            <template #default="{ row }">
              <el-tag v-for="alias in row.aliases" :key="alias" size="small" class="alias-tag" effect="plain">
                {{ alias }}
              </el-tag>
              <span v-if="!row.aliases.length" class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="level" label="层级" width="90" />
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="openDialog(row)">编辑</el-button>
              <el-button text type="danger" size="small" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑归属地' : '添加归属地'" width="560px">
      <el-form label-width="90px" label-position="left">
        <el-form-item label="标准名">
          <el-input v-model="form.standard_name" placeholder="例如：襄都区" />
        </el-form-item>
        <el-form-item label="简称">
          <el-input v-model="form.short_name" placeholder="例如：襄都" />
        </el-form-item>
        <el-form-item label="别名">
          <el-select
            v-model="form.aliases"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入后回车添加，例如：桥东区"
            style="width: 100%"
          />
          <div class="hint">报表、数据库里出现过的其他写法都填进来，系统过滤时会一并匹配。</div>
        </el-form-item>
        <el-form-item label="上级">
          <el-input v-model="form.parent" placeholder="例如：邢台市" />
        </el-form-item>
        <el-form-item label="层级">
          <el-radio-group v-model="form.level">
            <el-radio-button value="区县">区县</el-radio-button>
            <el-radio-button value="市">市</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="checkerVisible" title="名称检查" width="620px">
      <div class="hint" style="margin-bottom: 12px">
        把报表里出现的归属地名称贴进来（一行一个，或用逗号分隔），系统会告诉你哪些识别不了。
      </div>
      <el-input v-model="checkerInput" type="textarea" :rows="5" placeholder="襄都&#10;桥东区&#10;内邱&#10;达活" />
      <el-button type="primary" style="margin-top: 12px" :loading="checking" @click="runCheck">开始检查</el-button>

      <div v-if="checkResult" class="check-result">
        <el-divider content-position="left">检查结果</el-divider>
        <el-table :data="checkResult.results" size="small" border max-height="280">
          <el-table-column prop="raw" label="原始写法" width="130" />
          <el-table-column label="识别结果" width="130">
            <template #default="{ row }">
              <el-tag v-if="row.ok" type="success" size="small" effect="light">{{ row.standard }}</el-tag>
              <el-tag v-else type="danger" size="small" effect="light">未识别</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="匹配方式" width="110">
            <template #default="{ row }">
              <span class="muted">{{ matchLabel(row.matched_by) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="建议" min-width="140">
            <template #default="{ row }">
              <span v-if="row.suggestion" class="suggest">可能是「{{ row.suggestion }}」</span>
              <span v-else-if="!row.ok" class="muted">建议加入别名或人工核对</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="checkResult.unknown.length" class="hint warn-text">
          未识别 {{ checkResult.unknown.length }} 个：{{ checkResult.unknown.join('、') }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const items = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const checkerVisible = ref(false)
const checkerInput = ref('')
const checking = ref(false)
const checkResult = ref(null)

const form = reactive({
  standard_name: '',
  short_name: '',
  parent: '邢台市',
  level: '区县',
  aliases: [],
  sort_order: 0,
  is_active: true,
})

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await api.listRegions()
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  editing.value = row || null
  Object.assign(form, {
    standard_name: row?.standard_name || '',
    short_name: row?.short_name || '',
    parent: row?.parent || '邢台市',
    level: row?.level || '区县',
    aliases: [...(row?.aliases || [])],
    sort_order: row?.sort_order || 0,
    is_active: row?.is_active ?? true,
  })
  dialogVisible.value = true
}

async function save() {
  if (!form.standard_name.trim()) return ElMessage.warning('请填写标准名')
  saving.value = true
  try {
    if (editing.value) {
      await api.updateRegion(editing.value.id, { ...form })
      ElMessage.success('已保存')
    } else {
      await api.createRegion({ ...form })
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除归属地「${row.standard_name}」？`, '删除确认', { type: 'warning' })
  await api.deleteRegion(row.id)
  ElMessage.success('已删除')
  load()
}

async function runCheck() {
  const values = checkerInput.value
    .split(/[\n,，、;；]/)
    .map((v) => v.trim())
    .filter(Boolean)
  if (!values.length) return ElMessage.warning('请先输入要检查的名称')
  checking.value = true
  try {
    checkResult.value = await api.checkRegions(values)
  } finally {
    checking.value = false
  }
}

function matchLabel(value) {
  return { exact: '精确匹配', suffix: '去后缀匹配', fuzzy: '模糊推荐', none: '无匹配' }[value] || value
}
</script>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
}

.alias-tag {
  margin: 0 6px 4px 0;
}

.check-result {
  margin-top: 8px;
}

.suggest {
  color: #b54708;
  font-size: 12.5px;
}

.warn-text {
  color: #b54708;
  margin-top: 10px;
}
</style>

