/**
 * Vite 构建配置文件。
 *
 * 配置 @vitejs/plugin-react 插件（支持 React Fast Refresh 和 JSX 转换）。
 * Vite 开发服务器默认运行在 localhost:5173。
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
