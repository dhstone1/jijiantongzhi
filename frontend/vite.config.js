import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:18080'

export default defineConfig({
  // 部署到子路径（如 http://host/jijiantongzhi/）时用 VITE_BASE 指定，
  // 本地开发不设置，保持根路径。
  base: process.env.VITE_BASE || '/',
  plugins: [vue()],
  server: {
    port: Number(process.env.VITE_PORT || 5173),
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      // 推送出去的报表图片，让浏览器也能直接看到
      '/static': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
