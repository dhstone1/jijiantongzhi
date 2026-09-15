<template>
  <div class="login-page">
    <div class="glow glow-a"></div>
    <div class="glow glow-b"></div>

    <div class="card">
      <div class="brand">
        <div class="brand-mark">推</div>
        <div>
          <div class="brand-name">运营数据推送系统</div>
          <div class="brand-sub">Data Push Console</div>
        </div>
      </div>

      <h1 class="title">输入手机号进入</h1>
      <p class="desc">
        系统根据人员信息表识别你的身份和归属地。省级管理员看全省，地市管理员看本地市，
        普通人员只看自己归属地。
      </p>

      <el-form @submit.prevent="handleLogin">
        <el-input
          v-model="mobile"
          size="large"
          placeholder="请输入手机号"
          maxlength="11"
          clearable
          :prefix-icon="Iphone"
          @keyup.enter="handleLogin"
        />
        <el-button
          type="primary"
          size="large"
          class="submit"
          :loading="loading"
          @click="handleLogin"
        >
          进入系统
        </el-button>
      </el-form>

      <div v-if="errorText" class="error">{{ errorText }}</div>

      <div class="demo">
        <div class="demo-title">演示账号</div>
        <div class="demo-list">
          <button v-for="item in demos" :key="item.mobile" class="demo-item" @click="fill(item.mobile)">
            <span class="demo-name">{{ item.name }}</span>
            <span class="demo-region">{{ item.region }}</span>
            <span class="demo-mobile mono">{{ item.mobile }}</span>
          </button>
        </div>
        <div class="hint">接入真实数据前，可先用演示账号体验完整流程。</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Iphone } from '@element-plus/icons-vue'
import { api } from '../api'
import { useUserStore } from '../stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const mobile = ref('')
const loading = ref(false)
const errorText = ref('')

const demos = [
  { name: '陈静', region: '省级管理员 · 河北省', mobile: '13900000000' },
  { name: '孙磊', region: '地市管理员 · 邢台市', mobile: '13900000006' },
  { name: '张伟', region: '普通人员 · 襄都区', mobile: '13900000001' },
]

function fill(value) {
  mobile.value = value
  errorText.value = ''
}

async function handleLogin() {
  const value = mobile.value.trim()
  if (!value) {
    errorText.value = '请输入手机号'
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    const user = await api.login(value)
    store.setUser(user)
    router.push(route.query.redirect || { name: 'dashboard' })
  } catch (error) {
    errorText.value = error?.response?.data?.detail || '登录失败，请检查手机号'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  position: relative;
  overflow: hidden;
  background: #f4f6fb;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.5;
}

.glow-a {
  width: 520px;
  height: 520px;
  background: #cdd7fb;
  top: -180px;
  left: -120px;
}

.glow-b {
  width: 460px;
  height: 460px;
  background: #d9e6ff;
  bottom: -200px;
  right: -100px;
}

.card {
  position: relative;
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(16, 24, 40, 0.09);
  padding: 32px 32px 26px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 26px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(46, 75, 216, 0.3);
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.3;
}

.brand-sub {
  font-size: 10px;
  color: var(--ink-400);
  letter-spacing: 0.8px;
  text-transform: uppercase;
}

.title {
  font-size: 21px;
  font-weight: 600;
  margin: 0 0 8px;
  letter-spacing: 0.2px;
}

.desc {
  font-size: 13px;
  color: var(--ink-500);
  line-height: 1.7;
  margin: 0 0 22px;
}

.submit {
  width: 100%;
  margin-top: 14px;
}

.error {
  margin-top: 12px;
  padding: 9px 12px;
  border-radius: 8px;
  background: #fef3f2;
  border: 1px solid #fecdca;
  color: #b42318;
  font-size: 12.5px;
}

.demo {
  margin-top: 26px;
  padding-top: 20px;
  border-top: 1px dashed var(--line);
}

.demo-title {
  font-size: 12px;
  color: var(--ink-500);
  margin-bottom: 10px;
}

.demo-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.demo-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fcfcfd;
  cursor: pointer;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--ink-700);
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}

.demo-item:hover {
  border-color: var(--brand-500);
  background: var(--brand-50);
}

.demo-name {
  font-weight: 600;
  color: var(--ink-900);
  flex: 0 0 34px;
}

.demo-region {
  flex: 1;
  color: var(--ink-500);
  font-size: 12px;
}

.demo-mobile {
  color: var(--ink-400);
}

.hint {
  margin-top: 10px;
}
</style>
