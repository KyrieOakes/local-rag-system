# DevLog — SSE 流式输出修复与增强

> **日期**: 2026-06-12
> **标签**: bugfix, sse, streaming, frontend, ux

---

## 一、概述

修复 SSE 流式输出的 4 个问题，使流式体验真正生效：
1. 前端 `currentEvent` 变量作用域 bug — event 事件可能被静默丢弃
2. 首个 token 到达前有长时间静默 — 用户不知道系统在做什么
3. 非 RAG 路径整段回答一次性发送 — 无流式效果
4. LLM 中途失败时 stream 直接断开 — 前端卡在 loading

---

## 二、修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/services/rag_service.py` | 修改 | `_sse_event()` 对字符串统一 JSON 编码；新增 `import asyncio`；非 RAG 路径逐词流式 + status 事件；RAG 路径三处 status 事件（searching/reranking/generating）；token 循环 try/except 错误恢复 |
| `app/api/rag.py` | 修改 | docstring 补充 `status` 和 `error` 事件说明 |
| `frontend/src/api.js` | 修改 | `currentEvent` 移到 `while` 循环外（Critical Bugfix）；新增 `status`/`error` case；简化 `token` case；JSDoc 更新 |
| `frontend/src/App.jsx` | 修改 | placeholder 消息新增 `statusText`；新增 `onStatus`/`onError` 回调；消息渲染区显示进度文字 |
| `frontend/src/App.css` | 修改 | 新增 `.stream-status` 样式 |

---

## 三、实现细节

### Bugfix: currentEvent 作用域

```javascript
// Before (Bug): currentEvent 在每次 reader.read() 时被重置
while (true) {
  const { done, value } = await reader.read();
  let currentEvent = null;  // ← event/data 跨 chunk 时丢失
  ...
}

// After: 移到循环外，跨 chunk 保持状态
let currentEvent = null;
while (true) {
  const { done, value } = await reader.read();
  ...
}
```

### 后端 _sse_event() 统一 JSON 编码

```python
# Before: 字符串不编码 → 前端 JSON.parse 失败 → catch hack
payload = data if isinstance(data, str) else json.dumps(data, ...)

# After: 所有数据统一 JSON 编码 → 前端始终用 JSON.parse
payload = json.dumps(data, ensure_ascii=False)
```

### 非 RAG 路径逐词流式

```python
words = answer.split()
for i, word in enumerate(words):
    token = word + (" " if i < len(words) - 1 else "")
    yield _sse_event("token", token)
    await asyncio.sleep(0)  # yield event loop 让 ASGI flush
```

### RAG 路径 status 事件

在三个阻塞操作前发送进度事件：
- `status: {phase: "searching"}` — 向量检索前
- `status: {phase: "reranking"}` — Rerank 前（仅启用时）
- `status: {phase: "generating"}` — LLM 生成前

### 错误恢复

```python
try:
    async for token in generate_answer_stream(...):
        yield _sse_event("token", token)
except Exception as exc:
    yield _sse_event("error", {"message": ..., "phase": "generating"})
```

---

## 四、SSE 事件协议（更新后）

| 事件 | data | 触发时机 |
|------|------|---------|
| `routing` | `{routing, conversation_id}` | 路由决策完成 |
| `status` | `{phase, message}` | 管道各阶段开始 |
| `token` | `"<string>"` | 每个 token（JSON 编码） |
| `sources` | `[...SourceChunk]` | 检索到的文档 |
| `done` | `{}` | 流结束 |
| `error` | `{message, phase}` | 生成失败 |

---

## 五、测试验证

```bash
# Greeting 路径 — 确认逐词流式 + status 事件
curl -N -X POST http://127.0.0.1:8000/rag/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"你好",...}'
# ✅ routing → status → token×N(逐词) → sources → done
```

---

## 六、影响分析

- **向后兼容**: 新增 event 类型是加法的，旧客户端忽略未知 event 即可
- **前端**: 不再依赖 JSON.parse 失败作为 token 分发手段，更健壮
- **性能**: `asyncio.sleep(0)` 无实际延迟，仅让出事件循环
- **错误处理**: LLM 失败不再导致前端卡死
