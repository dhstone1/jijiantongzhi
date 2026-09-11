# 3. DataSourceView.vue - 增加权限tab
with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\DataSourceView.vue', 'r', encoding='utf-8') as f:
    c = f.read()

# 替换 import 行
c = c.replace("import { computed, onMounted, reactive, ref } from 'vue'",
              "import { computed, onMounted, reactive, ref } from 'vue'\nimport { useUserStore } from '../stores/user'")

# 添加 store 和权限变量
c = c.replace('const filteredTables = computed(() => {',
              '''const store = useUserStore()
const staffList = ref([])
const permittedMobiles = ref([])
const activeTab = ref('basic')

const filteredTables = computed(() => {''')

# 替换 load 函数
c = c.replace('items.value = await api.listDatasources()', 'items.value = await api.listDatasources(store.user?.mobile)')

# 替换对话框模板 - 添加 tabs
old_dialog = '''    <el-dialog v-model="dialogVisible" :title="editing ? '\\u7f16\\u8f91\\u6570\\u636e\\u6e90' : '\\u6dfb\\u52a0\\u6570\\u636e\\u6e90'" width="600px">
      <el-form label-width="96px" label-position="left">
        <el-form-item label="\\u540d\\u79f0">
          <el-input v-model="form.name" placeholder="\\u4f8b\\u5982\\uff1a\\u7f51\\u7edc\\u8fd0\\u8425\\u5e93" />
        </el-form-item>
        <el-form-item label="\\u6570\\u636e\\u5e93\\u7c7b\\u578b">
          <el-radio-group v-model="form.db_type">
            <el-radio-button value="postgresql">PostgreSQL</el-radio-button>
            <el-radio-button value="sqlite">\\u672c\\u5730\\u6587\\u4ef6\\u5e93</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.db_type === 'postgresql'">
          <el-form-item label="\\u4e3b\\u673a">
            <el-input v-model="form.host" placeholder="\\u4f8b\\u5982\\uff1a10.0.0.10" />
          </el-form-item>
          <el-form-item label="\\u7aef\\u53e3">
            <el-input-number v-model="form.port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="\\u6570\\u636e\\u5e93">
            <el-input v-model="form.database" placeholder="\\u6570\\u636e\\u5e93\\u540d" />
          </el-form-item>
          <el-form-item label="\\u53ea\\u8bfb\\u8d26\\u53f7">
            <el-input v-model="form.username" placeholder="\\u7528\\u6237\\u540d" />
          </el-form-item>
          <el-form-item label="\\u5bc6\\u7801">
            <el-input v-model="form.password" type="password" show-password placeholder="\\u7559\\u7a7a\\u8868\\u793a\\u4e0d\\u4fee\\u6539" />
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="\\u6587\\u4ef6\\u8def\\u5f84">
            <el-input v-model="form.file_path" placeholder="\\u4f8b\\u5982\\uff1aD:\\\\data\\\\demo.db" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">\\u53d6\\u6d88</el-button>
        <el-button type="primary" :loading="saving" @click="save">\\u4fdd\\u5b58</el-button>
      </template>
    </el-dialog>'''

new_dialog = '''    <el-dialog v-model="dialogVisible" :title="editing ? '\\u7f16\\u8f91\\u6570\\u636e\\u6e90' : '\\u6dfb\\u52a0\\u6570\\u636e\\u6e90'" width="640px">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="\\u57fa\\u672c\\u8bbe\\u7f6e" name="basic">
          <el-form label-width="96px" label-position="left">
            <el-form-item label="\\u540d\\u79f0">
              <el-input v-model="form.name" placeholder="\\u4f8b\\u5982\\uff1a\\u7f51\\u7edc\\u8fd0\\u8425\\u5e93" />
            </el-form-item>
            <el-form-item label="\\u6570\\u636e\\u5e93\\u7c7b\\u578b">
              <el-radio-group v-model="form.db_type">
                <el-radio-button value="postgresql">PostgreSQL</el-radio-button>
                <el-radio-button value="sqlite">\\u672c\\u5730\\u6587\\u4ef6\\u5e93</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <template v-if="form.db_type === 'postgresql'">
              <el-form-item label="\\u4e3b\\u673a">
                <el-input v-model="form.host" placeholder="\\u4f8b\\u5982\\uff1a10.0.0.10" />
              </el-form-item>
              <el-form-item label="\\u7aef\\u53e3">
                <el-input-number v-model="form.port" :min="1" :max="65535" />
              </el-form-item>
              <el-form-item label="\\u6570\\u636e\\u5e93">
                <el-input v-model="form.database" placeholder="\\u6570\\u636e\\u5e93\\u540d" />
              </el-form-item>
              <el-form-item label="\\u53ea\\u8bfb\\u8d26\\u53f7">
                <el-input v-model="form.username" placeholder="\\u7528\\u6237\\u540d" />
              </el-form-item>
              <el-form-item label="\\u5bc6\\u7801">
                <el-input v-model="form.password" type="password" show-password placeholder="\\u7559\\u7a7a\\u8868\\u793a\\u4e0d\\u4fee\\u6539" />
              </el-form-item>
            </template>

            <template v-else>
              <el-form-item label="\\u6587\\u4ef6\\u8def\\u5f84">
                <el-input v-model="form.file_path" placeholder="\\u4f8b\\u5982\\uff1aD:\\\\data\\\\demo.db" />
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="\\u53ef\\u89c1\\u6743\\u9650" name="permission">
          <div class="hint" style="margin-bottom: 12px">\\u8bbe\\u7f6e\\u5bf9\\u8be5\\u6570\\u636e\\u6e90\\u53ef\\u89c1\\u7684\\u4eba\\u5458\\uff08\\u624b\\u673a\\u53f7\\uff09\\uff0c\\u7ba1\\u7406\\u5458\\u9ed8\\u8ba4\\u53ef\\u89c1\\u5168\\u90e8\\u3002\\u7559\\u7a7a\\u8868\\u793a\\u4ec5\\u7ba1\\u7406\\u5458\\u53ef\\u89c1\\u3002</div>
          <el-transfer
            v-model="permittedMobiles"
            :data="staffList"
            filterable
            filter-placeholder="\\u641c\\u7d22\\u4eba\\u5458"
            :titles="['\\u5168\\u90e8\\u4eba\\u5458', '\\u53ef\\u89c1\\u4eba\\u5458']"
            />
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="dialogVisible = false">\\u53d6\\u6d88</el-button>
        <el-button type="primary" :loading="saving" @click="save">\\u4fdd\\u5b58</el-button>
      </template>
    </el-dialog>'''

c = c.replace(old_dialog, new_dialog)

# 替换 openDialog
old_open = '''function openDialog(row) {
  editing.value = row || null
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
  dialogVisible.value = true
}'''
new_open = '''function openDialog(row) {
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
}'''
c = c.replace(old_open, new_open)

# 替换 save 函数
old_save = '''async function save() {
  if (!form.name.trim()) return ElMessage.warning('\\u8bf7\\u586b\\u5199\\u540d\\u79f0')
  saving.value = true
  try {
    if (editing.value) {
      await api.updateDatasource(editing.value.id, { ...form })
      ElMessage.success('\\u5df2\\u4fdd\\u5b58')
    } else {
      await api.createDatasource({ ...form })
      ElMessage.success('\\u5df2\\u521b\\u5efa')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}'''
new_save = '''async function save() {
  if (!form.name.trim()) return ElMessage.warning('\\u8bf7\\u586b\\u5199\\u540d\\u79f0')
  saving.value = true
  try {
    let id = editing.value?.id
    if (editing.value) {
      await api.updateDatasource(id, { ...form })
      ElMessage.success('\\u5df2\\u4fdd\\u5b58')
    } else {
      const result = await api.createDatasource({ ...form })
      id = result.id
      ElMessage.success('\\u5df2\\u521b\\u5efa')
    }
    await api.grantPermissions('datasource', id, permittedMobiles.value)
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}'''
c = c.replace(old_save, new_save)

with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\DataSourceView.vue', 'w', encoding='utf-8') as f:
    f.write(c)
print('DataSourceView.vue OK')
