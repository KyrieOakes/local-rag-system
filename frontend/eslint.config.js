/**
 * ESLint 配置文件（Flat Config 格式）。
 *
 * 规则集：
 * - 忽略 dist/ 目录
 * - 继承 ESLint 推荐规则
 * - React Hooks 规则（检查 hooks 的依赖数组和调用位置）
 * - React Refresh 规则（确保 HMR 安全的导出）
 * - 浏览器全局变量环境
 * - 启用 JSX 语法解析
 *
 * 运行：cd frontend && npm run lint
 */
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
])
