# Dev Log — 前端 Markdown 渲染修复

> **日期**: 2026-05-09
> **标签**: bugfix, frontend, markdown, ui

---

## 一、概述

修复前端聊天界面中 LLM 返回的 Markdown 格式内容（如 `**粗体**`、`*斜体*`、代码块等）被原样显示为纯文本的渲染问题。引入 `react-markdown` 库对 assistant 消息进行解析，并补充完整的 Markdown 元素样式。

---

## 二、新增/修改的文件清单

### 前端（React / Vite）

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/package.json` | **修改** | 新增 `react-markdown` 依赖 |
| `frontend/src/App.jsx` | **修改** | 导入 `ReactMarkdown`，对 assistant 消息使用 Markdown 渲染；用户消息保持纯文本渲染 |
| `frontend/src/App.css` | **修改** | 新增约 90 行 Markdown 元素样式（p, strong, em, code, pre, ul/ol/li, h1-h6, blockquote, a, hr, table） |

---

## 三、实现细节

### 3.1 渲染逻辑 (`App.jsx`)

- **用户消息**：保持原有 `<div>{msg.content}</div>` 渲染，保留 `white-space: pre-wrap` 行为
- **Assistant 消息**：改用 `<ReactMarkdown>{msg.content}</ReactMarkdown>` 渲染，解析 LLM 返回的 Markdown 语法

### 3.2 样式覆盖 (`App.css`)

在 `.message.assistant .message-text` 之后新增 `.message-text` 下所有 Markdown 元素的样式规则：

- **`strong`**：加粗 + 高亮白色 (`#f0f0f0`)
- **`em`**：斜体 + 淡紫色 (`#c4b5fd`)
- **`code`**：内联代码，半透明紫色背景 + 圆角 + 等宽字体
- **`pre > code`**：代码块，深色背景 + 边框 + 圆角 + 水平滚动
- **`ul / ol`**：左缩进列表
- **`h1-h6`**：6 级标题，逐级递减字号
- **`blockquote`**：紫色左边框引用块
- **`table`**：完整表格样式（边框、表头背景色）
- **`a`**：紫色下划线链接
- **`hr`**：细线分隔线

### 3.3 兼容性考量

- 仅对 assistant 消息启用 Markdown 渲染，用户消息保持纯文本 + `pre-wrap`，避免用户输入中的特殊字符被意外解析
- 所有样式限制在 `.message-text` 作用域内，不影响其他 UI 区域

---

## 四、新增依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `react-markdown` | ^10.1.0 | React 原生 Markdown 解析渲染，无 XSS 风险 |

---

## 五、测试验证

### 手动测试步骤

1. 启动后端 + 前端，上传文档并发送查询
2. 验证 LLM 返回的 `**粗体**` 显示为 **加粗文本**
3. 验证 `*斜体*` 显示为 *倾斜文本*
4. 验证 `` `code` `` 显示为内联代码样式
5. 验证 ` ```code block``` ` 显示为代码块样式
6. 验证 `- 列表项` 显示为无序列表
7. 验证 `> 引用` 显示为引用块
8. 验证用户消息（纯文本）仍正常显示，不受 Markdown 渲染影响
9. 验证 `npm run build` 编译通过

### 边界情况

- 用户消息中包含 Markdown 特殊字符（`*`、`#` 等）→ 以纯文本显示，不会被渲染
- LLM 返回不含 Markdown 的纯文本 → ReactMarkdown 将其包裹在 `<p>` 中，显示正常
- 空消息 → 无内容渲染

---

## 六、与现有系统的影响

- **无破坏性变更**：仅修改 assistant 消息的渲染方式，不影响 API 调用、上传、文档管理等其他功能
- **向前兼容**：用户消息渲染逻辑完全不变
- **前端依赖**：新增 `react-markdown`，不影响后端
