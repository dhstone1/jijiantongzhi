# 4. BotView.vue - 类似修改
with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\BotView.vue', 'r', encoding='utf-8') as f:
    c = f.read()

# import
c = c.replace("import { onMounted, reactive, ref } from 'vue'",
              "import { onMounted, reactive, ref } from 'vue'\nimport { useUserStore } from '../stores/user'")

# 添加 store 和权限变量
c = c.replace('const form = reactive({ name: \"\", webhook: \"\", secret: \"\", is_active: true })',
              '''const store = useUserStore()
const staffList = ref([])
const permittedMobiles = ref([])
const activeTab = ref('basic')

const form = reactive({ name: \"\", webhook: \"\", secret: \"\", is_active: true })''')

# load 加 mobile
c = c.replace('items.value = await api.listBots()', 'items.value = await api.listBots(store.user?.mobile)')

# 替换对话框
old_dialog = '''    <el-dialog v-model="dialogVisible" :title="editing ? '\\u7f16\\u8f91\\u9489\\u9489\\u7fa4' : '\\u6dfb\\u52a0\\u9489\\u9489\\u7fa4'" width="600px">
      <el-form label-width="100px" label-position="left">
        <el-form-item label="\\u7fa4\\u540d\\u79f0">
          <el-input v-model="form.name" placeholder="\\u4f8b\\u5982\\uff1a\\u7f51\\u7edc\\u8fd0\\u8425\\u65e5\\u62a5\\u7fa4" />
        </el-form-item>
        <el-form-item label="Webhook">
          <el-input
            v-model="form.webhook"
            type="textarea"
            :rows="2"
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
          />
        </el-form-item>
        <el-form-item label="\\u52a0\\u7b7e\\u5bc6\\u94a5">
          <el-input v-model="form.secret" type="password" show-password placeholder="SEC \\u5f00\\u5934\\uff0c\\u7559\\u7a7a\\u8868\\u793a\\u4e0d\\u4fee\\u6539" />
          <div class="hint">\\u673a\\u5668\\u4eba\\u5b89\\u5168\\u8bbe\\u7f6e\\u9009\\u62e9\\u300c\\u52a0\\u7b7e\\u300d\\u65f6\\u624d\\u9700\\u8981\\u586b\\u5199\\u3002</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">\\u53d6\\u6d88</el-button>
        <el-button type="primary" :loading="saving" @click="save">\\u4fdd\\u5b58</el-button>
      </template>
    </el-dialog>'''

new_dialog = '''    <el-dialog v-model="dialogVisible" :title="editing ? '\\u7f16\\u8f91\\u9489\\u9489\\u7fa4' : '\\u6dfb\\u52a0\\u9489\\u9489\\u7fa4'" width="640px">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="\\u57fa\\u672c\\u8bbe\\u7f6e" name="basic">
          <el-form label-width="100px" label-position="left">
            <el-form-item label="\\u7fa4\\u540d\\u79f0">
              <el-input v-model="form.name" placeholder="\\u4f8b\\u5982\\uff1a\\u7f51\\u7edc\\u8fd0\\u8425\\u65e5\\u62a5\\u7fa4" />
            </el-form-item>
            <el-form-item label="Webhook">
              <el-input
                v-model="form.webhook"
                type="textarea"
                :rows="2"
                placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
              />
            </el-form-item>
            <el-form-item label="\\u52a0\\u7b7e\\u5bc6\\u94a5">
              <el-input v-model="form.secret" type="password" show-password placeholder="SEC \\u5f00\\u5934\\uff0c\\u7559\\u7a7a\\u8868\\u793a\\u4e0d\\u4fee\\u6539" />
              <div class="hint">\\u673a\\u5668\\u4eba\\u5b89\\u5168\\u8bbe\\u7f6e\\u9009\\u62e9\\u300c\\u52a0\\u7b7e\\u300d\\u65f6\\u624d\\u9700\\u8981\\u586b\\u5199\\u3002</div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="\\u53ef\\u89c1\\u6743\\u9650" name="permission">
          <div class="hint" style="margin-bottom: 12px">\\u8bbe\\u7f6e\\u5bf9\\u8be5\\u9489\\u9489\\u7fa4\\u53ef\\u89c1\\u7684\\u4eba\\u5458\\uff08\\u624b\\u673a\\u53f7\\uff09\\uff0c\\u7ba1\\u7406\\u5458\\u9ed8\\u8ba4\\u53ef\\u89c1\\u5168\\u90e8\\u3002\\u7559\\u7a7a\\u8868\\u793a\\u4ec5\\u7ba1\\u7406\\u5458\\u53ef\\u89c1\\u3002</div>
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

# openDialog
old_open = '''function openDialog(row) {
  editing.value = row || null
  Object.assign(form, {
    name: row?.name || '',
    webhook: row?.webhook || '',
    secret: '',
    is_active: row?.is_active ?? true,
  })
  dialogVisible.value = true
}'''
new_open = '''function openDialog(row) {
  editing.value = row || null
  activeTab.value = 'basic'
  Object.assign(form, {
    name: row?.name || '',
    webhook: row?.webhook || '',
    secret: '',
    is_active: row?.is_active ?? true,
  })
  permittedMobiles.value = []
  Promise.all([
    api.listStaff(),
    row ? api.listPermissions('dingtalk_bot', row.id) : [],
  ]).then(([staff, perms]) => {
    staffList.value = staff.map((s) => ({ key: s.mobile, label: s.name + '(' + s.mobile + ')' }))
    permittedMobiles.value = perms.map((p) => p.mobile)
  })
  dialogVisible.value = true
}'''
c = c.replace(old_open, new_open)

# save
old_save = '''async function save() {
  if (!form.name.trim()) return ElMessage.warning('\\u8bf7\\u586b\\u5199\\u7fa4\\u540d\\u79f0')
  if (!editing.value && !form.webhook.trim()) return ElMessage.warning('\\u8bf7\\u586b\\u5199 Webhook \\u5730\\u5740')
  saving.value = true
  try {
    if (editing.value) {
      await api.updateBot(editing.value.id, { ...form })
      ElMessage.success('\\u5df2\\u4fdd\\u5b58')
    } else {
      await api.createBot({ ...form })
      ElMessage.success('\\u5df2\\u521b\\u5efa')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}'''
new_save = '''async function save() {
  if (!form.name.trim()) return ElMessage.warning('\\u8bf7\\u586b\\u5199\\u7fa4\\u540d\\u79f0')
  if (!editing.value && !form.webhook.trim()) return ElMessage.warning('\\u8bf7\\u586b\\u5199 Webhook \\u5730\\u5740')
  saving.value = true
  try {
    let id = editing.value?.id
    if (editing.value) {
      await api.updateBot(id, { ...form })
      ElMessage.success('\\u5df2\\u4fdd\\u5b58')
    } else {
      const result = await api.createBot({ ...form })
      id = result.id
      ElMessage.success('\\u5df2\\u521b\\u5efa')
    }
    await api.grantPermissions('dingtalk_bot', id, permittedMobiles.value)
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}'''
c = c.replace(old_save, new_save)

with open(r'E:\22_codex\jijiantongzhi\frontend\src\views\BotView.vue', 'w', encoding='utf-8') as f:
    f.write(c)
print('BotView.vue OK')
