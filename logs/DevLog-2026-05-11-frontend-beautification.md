# Dev Log — Frontend UI Beautification: Editorial Ink Theme

> **Date**: 2026-05-11
> **Tags**: frontend, design, ui-ux, refactor

---

## 一、概述

对前端进行全面视觉升级，从原有的"多效果玻璃态"设计转向更克制的"Editorial Ink"深色主题。核心思路：减少效果竞争，让排版、间距和色彩层次本身成为设计语言。

---

## 二、文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/index.css` | **重写** | 引入 Plus Jakarta Sans 字体（Google Fonts），降低噪点纹理透明度，优化基础样式 |
| `frontend/src/App.css` | **重写** | 全新设计系统：CSS 自定义属性（design tokens）、精简到约 800 行、更深邃的配色、更克制的玻璃效果 |
| `frontend/src/App.jsx` | **修改** | 欢迎页使用 SVG 图标替代 emoji；fileTypeIcon 返回 SVG 组件；优化文案；健康状态标签更简洁 |
| `CLAUDE.md` | **修改** | 更新前端描述，补充设计系统说明 |

---

## 三、设计决策

- **字体**: Plus Jakarta Sans (300–800)，替代系统默认字体，提升辨识度和排版质感
- **配色**: 更深邃的背景 (`#08080c` → `#0f0f15` → `#16161e` 三层深度)，紫色强调色 (`#a78bfa`) 使用更克制
- **玻璃效果**: 仅用于顶栏和输入区背景，侧边栏改为不透明表面，减少"毛玻璃泛滥"
- **消息气泡**: 用户消息保留淡紫色气泡，助手消息保持无气泡纯文本（更像阅读体验）
- **欢迎页**: 用 SVG 大脑图标替代 emoji，提示卡片用 SVG 图标配合细微动效
- **输入框**: 更简洁的聚焦态光晕，移除了复杂的 shimmer 扫光动画

---

## 四、实现细节

- CSS 变量体系完整重构：`--bg-root/surface/elevated`、`--text-primary/secondary/muted`、`--accent/subtle/glow`、`--border-*`、`--shadow-*`、`--radius-*`、`--ease-*`
- 噪点纹理透明度从 0.035 降到 0.025–0.03，动画从 8s 延长到 12s
- 移除了约 1200 行冗余 CSS（重复选择器、过度复杂的伪元素效果）

---

## 五、验证

- ✅ `npm run build` 通过，无错误
- ✅ 页面渲染正常：欢迎页、侧边栏、输入区均正确显示
- ✅ 上传弹窗和文档管理器弹窗可正常打开/关闭
- ✅ Plus Jakarta Sans 字体成功加载（24 fonts loaded）
- ✅ 健康检查功能正常
