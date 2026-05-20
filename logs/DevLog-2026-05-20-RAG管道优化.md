# Dev Log — RAG Pipeline Optimization: Routing Gate + Conversation Context + Streaming

> **日期**: 2026-05-20
> **标签**: optimization, rag-gate, conversation-context, streaming, frontend

---

## 一、概述

全面优化 RAG 查询管道，实现三大核心改进：

1. **RAG 路由门控** — 两层路由判断查询是否需要检索。Layer 0 关键词预过滤（零 LLM 调用）拦截问候/致谢/告别；Layer 1 统一 LLM 调用同时完成路由决策 + 意图检测 + 改写/直接回答。
2. **多轮对话上下文** — 前端发送最近 10 条消息作为历史，后端在查询处理和答案生成两处注入历史，支持代词消解和连贯对话。
3. **SSE 流式响应** — 新增 `/rag/query/stream` 端点，逐 token 推送到前端，大幅提升感知速度。

附加优化：嵌入 LRU 缓存（256 条目）、异步日志（后台线程）、压缩查询处理提示词。

---

## 二、新增/修改的文件清单

### 后端（Python / FastAPI）

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/schemas/rag.py` | **重写** | 新增 `Message` 模型；`QueryRequest` 新增 `conversation_id`、`history`、`force_rag`；`QueryResponse` 新增 `conversation_id`、`routing` |
| `app/api/rag.py` | **重写** | `POST /rag/query` 传递新参数；新增 `POST /rag/query/stream` SSE 端点 |
| `app/services/rag_service.py` | **重写** | 编排逻辑分支：`needs_rag=False` 跳过检索直接返回；新增 `query_rag_stream()` 异步生成器；异步日志（`threading.Thread`） |
| `app/rag/query_processor.py` | **重写** | Layer 0 关键词预过滤（9 条规则）；Layer 1 统一 LLM 路由提示词；`process_query()` 新增 `history` 参数；返回 `needs_rag`/`direct_answer` |
| `app/rag/chain.py` | **重写** | 提取 `_build_chain_input()`；新增 `generate_answer_stream()` 异步生成器；`_format_history()` 历史格式化（2048 token 上限） |
| `app/rag/prompt.py` | **修改** | `RAG_SYSTEM_PROMPT` 新增 `{history}` 占位符 |
| `app/rag/embeddings.py` | **重写** | `LoggingOpenAIEmbeddings` → `CachedOpenAIEmbeddings`，线程安全 LRU 缓存（MD5 键，256 条目最大） |

### 前端（React / Vite）

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/api.js` | **重写** | `queryRag()` 改为接受 `{question, conversationId, history, forceRag}` 对象；新增 `queryRagStream()` SSE 读取函数（fetch + ReadableStream + 事件回调） |
| `frontend/src/App.jsx` | **修改** | 新增 `conversationId` 状态；`newChat()` 重置 `conversationId`；`handleSend()` 改为流式 + `@rag` 前缀处理 + 历史构建；消息新增 `routing` 字段和路由指示器 UI |
| `frontend/src/App.css` | **修改** | 新增 `.routing-badge` 样式（三种状态：rag/direct/greeting 颜色编码） |

---

## 三、API 设计

### `POST /rag/query`（已有端点，参数扩展）

**Request**:
```json
{
  "question": "What is RAG?",
  "conversation_id": null,
  "history": [],
  "force_rag": false
}
```

**Response 200**:
```json
{
  "question": "What is RAG?",
  "answer": "RAG stands for...",
  "sources": [...],
  "conversation_id": "a1b2c3d4e5f6",
  "routing": "rag"
}
```

`routing` 取值：`"rag"` | `"direct"` | `"greeting"`

### `POST /rag/query/stream`（新增 SSE 端点）

**Request**: 同 `/rag/query`

**SSE Events**:
```
event: routing
data: {"routing":"rag","conversation_id":"a1b2c3d4e5f6"}

event: token
data: RAG

event: token
data:  stands for...

event: sources
data: [{"content":"...","source":"intro.pdf",...}]

event: done
data: {}
```

---

## 四、实现细节

### 4.1 RAG 路由门控

**端到端流程变化**:

Before（固定 2 次 LLM 调用）:
```
User → [LLM: intent+rewrite] → [Vector Search] → [LLM: answer] → Response
```

After（动态）:
```
User → [Keyword pre-filter?]
  ├─ Match → Instant response (0 LLM calls)
  └─ No match → [LLM: route+rewrite OR route+answer]
       ├─ ROUTING=NO → Return direct answer (1 LLM call)
       └─ ROUTING=YES → [Vector Search] → [LLM: RAG answer] (2 LLM calls)
```

**关键词预过滤规则**（`_check_greeting`）:
- 问候类: `hi`, `hello`, `你好`, etc.
- 致谢类: `thanks`, `谢谢`, etc.
- 告别类: `bye`, `再见`, etc.
- 元问题: `who are you`, `你是谁`, etc.

匹配后直接返回预设回复，不调用任何 LLM。

**统一路由提示词**:
```
Analyze the user query for a RAG system. Perform routing first, then act accordingly.

ROUTING rules:
- YES: query needs document search
- NO: query is answerable from general knowledge

If ROUTING=YES: classify INTENT + rewrite query for vector search.
If ROUTING=NO: provide a concise, helpful direct answer.

Output format:
ROUTING: YES|NO
[if YES] INTENT: <intent>
[if YES] QUERY: <rewritten query>
[if NO] ANSWER: <direct reply>
```

### 4.2 多轮对话

**对话生命周期**:
1. 首条消息：前端发送 `conversation_id: null` → 后端生成 12 位 hex UUID → 返回给前端
2. 后续消息：前端携带已存储的 `conversation_id`
3. "New Chat" 按钮 → 前端重置 `conversationId` 为 `null`

**历史构建**（前端）:
```javascript
const recentHistory = messages
  .filter((m) => m.role === "user" || m.role === "assistant")
  .slice(-10)
  .map(({ role, content }) => ({ role, content }));
```

**历史注入点**:
1. `query_processor` — 追加到查询处理提示词尾部，辅助代词消解
2. `RAG_SYSTEM_PROMPT` — `{history}` 占位符在 `{context}` 之前

**Token 预算**: `_format_history()` 限制 ~2048 tokens（字符长度 ÷ 3 估算），旧消息优先丢弃。

### 4.3 SSE 流式

**后端**: `query_rag_stream()` 异步生成器，依次 yield `routing` → `token`×N → `sources` → `done` 事件。`generate_answer_stream()` 使用 LangChain `chain.astream()` 逐 token 产出。

**前端**: `queryRagStream()` 使用 `fetch` + `ReadableStream.getReader()` 解析 SSE 协议。`handleSend()` 在 `onToken` 回调中逐字符追加到消息内容，首 token 到达时自动隐藏 loading 动画。

### 4.4 嵌入缓存

`CachedOpenAIEmbeddings`:
- 线程安全（`threading.Lock`）
- MD5 哈希文本作为缓存键
- 256 条目上限，超出时淘汰最早条目（FIFO）
- 日志记录 hits/misses 用于监控

### 4.5 `@rag` 前缀

前端检测输入是否以 `@rag` 开头，如果是：
- 显示文本中去掉 `@rag` 前缀
- API 请求中设置 `force_rag: true`
- 后端在 `process_query` 返回 `needs_rag=False` 时，若 `force_rag=True` 则覆盖为 `True`

---

## 五、新增依赖

无。所有改动使用已有依赖（FastAPI, LangChain, Pydantic, React, axios）。

---

## 六、测试验证

### 手动测试步骤

1. **RAG Gate — 问候拦截**: 发送 "hello" → 前端应显示 "Quick reply" 路由标记，无来源块，响应近乎即时
2. **RAG Gate — 文档查询**: 上传文档后发送 "Summarize my documents" → 路由标记显示 "Searched documents"，附来源块
3. **RAG Gate — 通用问题**: 发送 "What is Python?" → 路由标记显示 "Direct response"，LLM 直接回答
4. **对话上下文**: 发送 "What is RAG?" → 再发送 "How does it work?" → 第二个回答应引用 RAG 概念
5. **New Chat**: 点击 "New Chat" → 发送 "What was I asking about?" → 应无上下文记忆
6. **流式响应**: 发送任何问题 → 应看到 token 逐个出现，首 token 后 loading 动画消失
7. **@rag 前缀**: 发送 "@rag What is Python?" → 应走 RAG 路径（搜索文档）
8. **向后兼容**: 使用 curl 发送 `{"question": "hello"}` → 应得到正常响应，包含新增字段

---

## 七、影响分析

- **破坏性变更**: `POST /rag/query` 响应新增 `conversation_id` 和 `routing` 字段，旧前端会忽略未知字段（JSON 兼容）。`POST /rag/query` 请求新增可选字段（均有默认值），旧前端只发 `{"question": "..."}` 仍可正常工作。
- **性能**: 非 RAG 查询延迟显著降低（0-1 次 LLM 调用 vs 原来的 2 次）。RAG 查询延迟无变化（仍为 2 次 LLM 调用），但流式传输显著提升感知速度。
- **嵌入缓存**: 重复查询跳过嵌入 API 调用，节省 ~100-500ms。
- **异步日志**: 响应不再阻塞于 JSONL 磁盘写入，节省 ~10-50ms。
