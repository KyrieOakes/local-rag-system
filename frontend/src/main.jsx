/**
 * React 应用入口文件。
 *
 * 职责：
 * - 挂载 React 应用到 DOM（#root 元素）
 * - 启用 StrictMode（开发环境下额外检查副作用）
 * - 导入全局样式（index.css）和根组件（App.jsx）
 *
 * 这是 Vite 构建的入口点，由 index.html 中 <script type="module"> 引用。
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
