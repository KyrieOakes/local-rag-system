# Dev Log — 助手 Markdown 空行修复

> **日期**: 2026-08-10
> **标签**: bugfix, frontend, react-markdown, css, streaming

---

## 一、概述

修复本地模型回答在前端出现过大段落空隙的问题。本地模型通常比云端 DeepSeek 生成更多标准 `\n\n` Markdown 段落；原样输出经过 ReactMarkdown 转换为块级段落后，外层 `white-space: pre-wrap` 又保留了块之间的换行文本节点，再叠加段落下边距与较大行高，导致正常段落间隔被重复放大。

本次仅调整助手消息的渲染样式。用户输入仍保留原始换行，Markdown 代码块仍严格保留空白，SSE、后端生成链路和消息持久化均不变。

---

## 二、新增/修改/删除文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/App.css` | 修改 | 助手 Markdown 使用正常空白流、收紧段落间距并显式保护代码块空白 |
| `AGENTS.md` | 修改 | 记录助手 Markdown、用户文本与代码块的空白处理职责 |
| `logs/DevLog-2026-08-10-助手Markdown空行修复.md` | 新增 | 记录问题证据、修复边界与验证结果 |

无删除文件。

---

## 三、调试结论

- 云端和本地模型都通过同一个 LangChain `ChatOpenAI` 适配器、StrOutputParser、SSE JSON 编码和前端 Token 拼接链路。
- 数据库中的本地模型答案包含较多标准双换行，但未发现连续三个以上换行、回车符、Unicode 行分隔符或大段连续空格。
- ReactMarkdown 会把 `第一段\n\n第二段` 渲染为两个 `<p>`，并在块节点之间保留换行文本节点。
- `.message-text` 原有 `white-space: pre-wrap` 会保留该节点；段落原有 `10px` 下边距和 `1.72` 行高进一步放大视觉间隔。
- 因此问题位于前端 Markdown 排版层，不是 SSE 边界解析错误，也不需要在后端破坏性清洗模型内容。

---

## 四、后端变化

无。模型调用、RAG 编排、SSE 事件协议和 SQLite 消息落库逻辑保持不变。

---

## 五、前端变化

### 5.1 助手消息

新增 `.message.assistant .message-text` 定向规则：

- `white-space: normal`：由 ReactMarkdown 的块级结构统一管理段落换行，避免二次保留换行文本节点。
- `line-height: 1.65`：保持中文可读性的同时减少过度松散的正文行距。

### 5.2 用户消息

用户消息继续继承 `.message-text` 的 `white-space: pre-wrap`，用户通过 Shift+Enter 输入的换行不会丢失。

### 5.3 Markdown 段落和代码块

- 普通段落下边距由 `10px` 调整为 `8px`。
- `<pre>` 显式使用 `white-space: pre`，确保代码缩进、换行和横向滚动语义不受助手正文规则影响。

---

## 六、API、数据库与向量库变化

- API：无变化。
- SQLite：无 schema 或数据变化。
- Qdrant：无变化。
- SSE 事件格式：无变化。

---

## 七、配置与依赖变化

- `.env` 和前端环境变量：无变化。
- npm/Python 依赖：无变化。
- Docker 与部署配置：无变化。

---

## 八、架构决策

选择在前端展示层修复，而不在后端合并或删除换行：

1. Markdown 的双换行属于合法段落语义，不应由服务端统一清洗。
2. 后端正则压缩换行容易破坏代码块、列表、引用和表格。
3. 用户消息和助手 Markdown 的渲染语义不同，应分别处理空白规则。
4. 该方案同时适用于 Hermes、Qwen、DeepSeek 等模型，不依赖模型名称或 Provider 分支。

---

## 九、测试与验证

### 自动化验证

- `npm test`：10/10 通过。
- `npm run lint`：通过。
- `npm run build`：通过，Vite 成功生成生产资源。

### 浏览器验证

临时启动 Vite 前端并检查浏览器实际加载的 CSSOM：

- `.message-text`：`white-space: pre-wrap`，供用户普通文本保留换行。
- `.message.assistant .message-text`：`white-space: normal; line-height: 1.65`。
- `.message-text p`：`margin: 0 0 8px`。
- `.message-text pre`：`white-space: pre`。

前端验证后已关闭临时开发服务器。后端未在此次浏览器验证中启动，因此页面显示 Backend Disconnected 属于预期，不影响 CSS 规则验证。

---

## 十、边界情况

- 本地模型输出大量正常段落：间距不再被 `pre-wrap` 重复放大。
- 用户多行输入：仍按原始换行显示。
- Markdown 代码块：保留缩进、连续空格和换行。
- 列表、标题、引用和表格：继续由 ReactMarkdown 及既有块级样式负责。
- 流式生成期间：每次 Token 更新仍会重新解析当前 Markdown，但完成态与落库态的空白语义一致。

---

## 十一、已知限制与后续改进

- 不同模型的段落偏好仍会不同，本次统一的是渲染语义，不会改写模型回答。
- 当前未增加 Provider/Model 字段到消息表，历史回答无法逐条精确归属模型；如需长期对比，可在查询追踪中记录模型标识和输出格式统计。
- 如后续发现流式阶段存在短暂 Markdown 跳动，可单独评估按帧合并 Token 或降低 Markdown 重解析频率。

---

## 十二、性能与现有系统影响

- 仅新增 CSS 选择器和属性覆盖，不增加运行时网络请求或 JavaScript 计算。
- 不影响 RAG 检索、重排、上下文记忆、模型生成、SSE 协议、消息持久化和来源标签。
- CSS 选择器基于现有 `.message.assistant` DOM 结构，无组件接口变化。
