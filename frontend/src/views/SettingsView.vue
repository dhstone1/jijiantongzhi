<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">系统设置</h1>
        <p class="page-sub">图片推送相关的系统级参数，改完立即生效，不用重启服务。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="save()">保存</el-button>
    </div>

    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">图片推送</div>
      </div>
      <div class="panel-body">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="钉钉里的图片是「链接」形式的"
          description="钉钉自定义机器人不支持表格，也发不了真正的图片文件，所以系统会把报表画成 PNG，再把图片链接发给群。钉钉客户端会自己去拉这张图，链接必须是它能访问到的地址 —— 要么本系统对外可达，要么把图片放到图床上。"
          style="margin-bottom: 18px"
        />

        <div class="block-title">图片存到哪里</div>
        <el-radio-group v-model="form.image_upload_mode" class="mode-group">
          <el-radio-button value="local">本系统服务器</el-radio-button>
          <el-radio-button value="beeimg">第三方图床</el-radio-button>
        </el-radio-group>

        <div v-if="form.image_upload_mode === 'local'" class="form-grid mode-body">
          <div class="field span-2">
            <label>图片服务地址</label>
            <el-input v-model="form.public_base_url" placeholder="例如 http://10.1.2.3:8080（留空表示暂不启用图片）" />
            <div class="hint">
              就是本系统的访问地址，末尾不用带斜杠，<strong>不要填图床的接口地址</strong>。
              填 <span class="mono">127.0.0.1</span> 或 <span class="mono">localhost</span> 时钉钉手机端加载不出来。
            </div>
            <div v-if="suggested.length" class="suggest">
              <span class="muted">本机可用地址：</span>
              <el-tag
                v-for="url in suggested"
                :key="url"
                size="small"
                effect="plain"
                class="pick"
                @click="form.public_base_url = url"
              >
                {{ url }}
              </el-tag>
            </div>
          </div>

          <div class="field">
            <label>图片保留天数</label>
            <el-input-number v-model="form.image_retention_days" :min="1" :max="90" />
            <div class="hint">超过天数的历史图片会自动删除，避免占用磁盘。</div>
          </div>
        </div>

        <div v-else class="form-grid mode-body">
          <el-alert
            class="span-2"
            type="warning"
            :closable="false"
            show-icon
            title="图床都有限额，建议填令牌用账号自己的存储"
            description="匿名上传额度很小（蜜蜂图床公共实例实测每小时 3 张，按 IP 计）；闪电图床免费账号 100 MB 容量、免费用户用存储 2、VIP 用存储 3。额度用尽或上传失败时，那一次推送会自动退回「文字表格版」，数据不会丢。报表内容与上次完全相同时，系统会直接复用已上传的链接，不占额度。"
            style="margin-bottom: 4px"
          />
          <div class="field span-2">
            <label>用哪个图床</label>
            <el-select v-model="provider" class="full" @change="applyProvider">
              <el-option label="闪电图床（注册即可，推荐）" value="boltp" />
              <el-option label="蜜蜂图床" value="beeimg" />
              <el-option label="自定义 / 其他图床" value="custom" />
            </el-select>
            <div class="hint">
              <template v-if="provider === 'custom'">
                填自己的接口地址和存储 ID，接口要兼容
                <span class="mono">POST /api/v2/upload</span>（multipart 传 file + storage_id）。
              </template>
              <template v-else>{{ providerNote }}</template>
            </div>
          </div>
          <div class="field span-2">
            <el-input
              v-model="form.beeimg_url"
              placeholder="https://www.boltp.com/api/v2/upload"
            >
              <template #prepend>接口地址</template>
            </el-input>
          </div>
          <div class="field">
            <label>存储 ID</label>
            <el-input v-model="form.beeimg_storage_id" placeholder="2" />
            <div class="hint">
              要填图床里真实存在的存储 ID，填错会报「不存在的储存驱动」。闪电图床：免费用户填
              <span class="mono">2</span>、VIP 填 <span class="mono">3</span>；蜜蜂图床公共实例匿名上传只能填
              <span class="mono">4</span>。不确定就点「测试上传」试出来。
            </div>
          </div>
          <div class="field">
            <label>接口令牌（可选）</label>
            <el-input v-model="form.beeimg_token" type="password" show-password placeholder="留空表示不修改" />
            <div class="hint">
              在图床后台「我的令牌」里创建并复制（要有上传权限），会作为
              <span class="mono">Authorization: Bearer</span> 头发送。闪电图床的存储必须登录才能用，所以这里一定要填。
            </div>
          </div>
          <div class="field">
            <label>图片过期天数</label>
            <el-input-number v-model="form.beeimg_expire_days" :min="0" :max="365" />
            <div class="hint">
              到期后图床自动删图，链接随之失效。填 <span class="mono">0</span> 表示永不过期，
              默认与本系统「图片保留天数」保持一致。
            </div>
          </div>
          <div class="field">
            <label>上传参数</label>
            <div class="switches">
              <el-switch v-model="form.beeimg_remove_exif" active-text="移除 EXIF" />
              <el-switch
                v-model="form.beeimg_is_public"
                active-text="公开可访问"
                :disabled="!settings.has_beeimg_token"
              />
            </div>
            <div class="hint">
              「公开可访问」需要图床登录态（填了接口令牌），否则本系统不传这个参数。
            </div>
          </div>
          <div class="field span-2">
            <el-button :loading="testing" @click="testHost">测试上传</el-button>
            <span class="muted test-tip">
              会先把上面的配置存下来，再真的传一张测试图上去（测的就是你填的）。
              图床有频率限制（公共实例实测每小时 3 张，按 IP 计），撞上限流时那条推送会自动退回文字版。
            </span>
            <div v-if="testResult" class="test-result">
              <el-tag type="success" size="small" effect="light">上传成功</el-tag>
              <a :href="testResult" target="_blank" rel="noreferrer" class="mono">{{ testResult }}</a>
            </div>
            <div v-if="testExpire" class="test-result">
              <span class="muted">这张图在</span>
              <span class="mono">{{ testExpire }}</span>
              <span class="muted">之后自动失效</span>
            </div>
          </div>
        </div>

        <div class="facts">
          <div class="fact">
            <span class="muted">当前状态</span>
            <el-tag :type="settings.image_ready ? 'success' : 'warning'" size="small" effect="light">
              {{ settings.image_ready ? '图片推送可用' : '未配置完整，图片规则会退回文字' }}
            </el-tag>
          </div>
          <div class="fact">
            <span class="muted">生效方式</span>
            <span class="mono">{{ modeText }}</span>
          </div>
          <div v-if="form.image_upload_mode === 'beeimg'" class="fact">
            <span class="muted">图片过期时间</span>
            <span class="mono">{{ settings.beeimg_expired_at || '永不过期' }}</span>
          </div>
          <div v-if="form.image_upload_mode === 'local'" class="fact">
            <span class="muted">图片存储目录</span>
            <span class="mono">{{ settings.image_dir || '—' }}</span>
          </div>
          <div class="fact">
            <span class="muted">中文字体</span>
            <el-tag :type="settings.font_available ? 'success' : 'danger'" size="small" effect="plain">
              {{ settings.font_available ? '正常' : '缺失，图片里的中文会变方块' }}
            </el-tag>
          </div>
        </div>

        <div class="hint" style="margin-top: 14px">
          放在图床上时，图片会离开本系统，链接是公网地址，请按「图片过期天数」让图床自动清理；
          放在本机时链接是随机文件名、按保留天数自动清理。
          两种方式都请按归属地建规则，图片里的数据就是那条规则取出来的数据。
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const saving = ref(false)
const testing = ref(false)
const testResult = ref('')
const testExpire = ref('')
const settings = ref({})

// 图床预设：选中就自动填好接口地址和存储 ID，只需要再补令牌
const PROVIDERS = {
  boltp: {
    url: 'https://www.boltp.com/api/v2/upload',
    storage: '2',
    note: '闪电图床：免费用户用存储 2、VIP 用存储 3，必须填「接口令牌」（在图床后台「我的令牌」里创建，给上传权限）。',
  },
  beeimg: {
    url: 'https://www.beeimg.cn/api/v2/upload',
    storage: '4',
    note: '蜜蜂图床：公共实例匿名上传只能填存储 4，额度很小（实测每小时 3 张），建议也填上令牌用账号自己的存储。',
  },
  custom: { url: '', storage: '', note: '' },
}

const provider = ref('custom')

const providerNote = computed(() => PROVIDERS[provider.value]?.note || '')

function detectProvider(url) {
  const value = (url || '').toLowerCase()
  if (value.includes('boltp')) return 'boltp'
  if (value.includes('beeimg')) return 'beeimg'
  return 'custom'
}

function applyProvider(key) {
  const preset = PROVIDERS[key]
  if (!preset || key === 'custom') return
  form.beeimg_url = preset.url
  form.beeimg_storage_id = preset.storage
}

const form = reactive({
  image_upload_mode: 'local',
  public_base_url: '',
  image_retention_days: 7,
  beeimg_url: '',
  beeimg_storage_id: '',
  beeimg_token: '',
  beeimg_expire_days: 7,
  beeimg_is_public: false,
  beeimg_remove_exif: true,
})

const suggested = computed(() => settings.value.suggested_urls || [])

const modeText = computed(() =>
  form.image_upload_mode === 'beeimg'
    ? '上传图床后发公网链接'
    : settings.value.effective_base_url || '未配置',
)

onMounted(load)

async function load() {
  settings.value = await api.getSettings()
  apply(settings.value)
}

function apply(data) {
  form.image_upload_mode = data.image_upload_mode || 'local'
  form.public_base_url = data.public_base_url || ''
  form.image_retention_days = data.image_retention_days || 7
  form.beeimg_url = data.beeimg_url || ''
  form.beeimg_storage_id = data.beeimg_storage_id || ''
  form.beeimg_token = data.beeimg_token || ''
  form.beeimg_expire_days = data.beeimg_expire_days ?? 7
  form.beeimg_is_public = !!data.beeimg_is_public
  form.beeimg_remove_exif = data.beeimg_remove_exif !== false
  provider.value = detectProvider(form.beeimg_url)
}

async function save(silent = false) {
  saving.value = true
  try {
    settings.value = await api.updateSettings({
      image_upload_mode: form.image_upload_mode,
      public_base_url: form.public_base_url.trim(),
      image_retention_days: form.image_retention_days,
      beeimg_url: form.beeimg_url.trim(),
      beeimg_storage_id: form.beeimg_storage_id.trim(),
      beeimg_token: form.beeimg_token,
      beeimg_expire_days: form.beeimg_expire_days ?? 0,
      beeimg_is_public: form.beeimg_is_public,
      beeimg_remove_exif: form.beeimg_remove_exif,
    })
    apply(settings.value)
    if (!silent) ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}

async function testHost() {
  testing.value = true
  testResult.value = ''
  testExpire.value = ''
  try {
    // 先把手填的配置存下来，保证「测的就是你看到的」
    await save(true)
    const result = await api.testImageHost()
    testResult.value = result.public_url
    testExpire.value = result.expired_at || ''
    ElMessage.success('上传成功')
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 20px;
}

.form-grid .span-2 {
  grid-column: span 2;
}

.block-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-800);
  margin-bottom: 12px;
}

.field label {
  display: block;
  font-size: 12.5px;
  color: var(--ink-700);
  margin-bottom: 7px;
  font-weight: 500;
}

.field .el-select,
.field .el-input,
.field .el-input-number {
  width: 100%;
}

.full {
  width: 100%;
}

.mode-group {
  margin-bottom: 20px;
}

.mode-body {
  padding: 18px;
  border: 1px dashed var(--line);
  border-radius: 10px;
}

.suggest {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
  font-size: 12px;
}

.pick {
  cursor: pointer;
}

.test-tip {
  margin-left: 10px;
  font-size: 12.5px;
}

.switches {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  height: 32px;
}

.test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 12.5px;
  word-break: break-all;
}

.facts {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px dashed var(--line);
}

.fact {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}
</style>
