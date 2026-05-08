# Dev Log — 文档管理 API（列表 + 删除）

> **日期**: 2025-01-XX
> **标签**: feature, document-management, api, frontend

---

## 一、概述

新增完整的文档管理功能，允许用户在浏览器中查看所有已索引文档（按文件类型分组），并一键删除任何文档（同时清理 Qdrant 向量库和本地文件）。

---

## 二、新增/修改的文件清单

### 后端（Python / FastAPI）

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/rag/vectorstore.py` | **修改** | 新增 `_get_qdrant_client()`、`list_all_documents()`、`delete_document_by_source()` 三个函数 |
| `app/services/document_service.py` | **重写** | 新增 `list_documents()` 和 `delete_document()` 业务逻辑 |
| `app/api/documents.py` | **修改** | 新增 `GET /documents`（列表）和 `DELETE /documents/{source}`（删除）两个端点 |

### 前端（React / Vite）

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/api.js` | **修改** | 新增 `listDocuments()` 和 `deleteDocument(source)` 两个 API 函数 |
| `frontend/src/App.jsx` | **修改** | 新增 Document Manager 面板 UI 和全部交互逻辑（约 120 行） |
| `frontend/src/App.css` | **修改** | 新增约 200 行样式（`.docmgr-*` 全部组件样式） |

---

## 三、API 设计

### `GET /documents`

列出所有已索引的文档（来源信息来自 Qdrant payload metadata）。

**Response 200**:
```json
[
  {"source": "intro.pdf", "file_type": ".pdf", "chunks": 45},
  {"source": "notes.txt", "file_type": ".txt", "chunks": 12},
  {"source": "README.md", "file_type": ".md", "chunks": 8}
]
```

### `DELETE /documents/{source}`

按文件名删除文档及其在 Qdrant 中的所有分块。

**Response 200**:
```json
{
  "source": "intro.pdf",
  "deleted_chunks": 45,
  "file_deleted": false,
  "status": "deleted"
}
```

**Response 404** (文档不存在):
```json
{"detail": "Document not found: nonexistent.pdf"}
```

---

## 四、实现细节

### 4.1 Qdrant 操作层 (`app/rag/vectorstore.py`)

#### `list_all_documents()`
- 使用 `qdrant_client.scroll()` 遍历所有点（每批 500 条）
- 按 `metadata.source` 聚合，统计每个 source 的 chunk 数
- 从文件名后缀推断 `file_type`（如 `.pdf`、`.txt`、`.md`）
- **复杂度**: O(n)，n 为总 chunk 数

#### `delete_document_by_source(source)`
- 先调用 `qdrant_client.count()` 精确统计匹配点数
- 再调用 `qdrant_client.delete()` 按 `metadata.source` 过滤删除
- 使用 `qdrant_client.models.Filter` + `FieldCondition` + `MatchValue`
- **返回值**: 实际删除的点数（0 表示文档不存在）

### 4.2 业务层 (`app/services/document_service.py`)

- `list_documents()` 直接透传 `list_all_documents()` 的结果
- `delete_document()` 组合调用：先删 Qdrant → 再删本地文件

### 4.3 API 层 (`app/api/documents.py`)

- `GET /documents` → `list_documents()` → JSON 数组
- `DELETE /documents/{source:path}` → `delete_document(source)` → 删除结果 JSON
  - 使用 `{source:path}` 捕获器以支持含特殊字符的文件名
  - 404 保护：未找到文档时返回 `HTTPException(404)`

### 4.4 前端 Document Manager 面板

**触发方式**: 左侧 Sidebar 底部 "Manage Documents" 区块中的 "Browse & Delete" 按钮（橙色高亮）

**面板内容**:
1. **Loading 状态**: Typing indicator + "Loading documents..."
2. **Error 状态**: 红色错误卡片 + Retry 按钮
3. **空列表状态**: 📭 图标 + 引导文字
4. **正常列表**: 按文件类型分组显示
   - Group Header: 文件图标 + 类型名 + 文件数 badge
   - 每个文件行: 文件名 + chunk 数 + 删除按钮 (🗑️)
5. **删除按钮**: 
   - Hover: 红色高亮
   - 点击: 显示 loading spinner
   - 完成后: 自动刷新列表 + 显示成功/失败消息
   - 防重复点击保护

**关闭方式**: 点击外部 / ESC 键 / 关闭按钮

**CSS 类命名**: 全部使用 `docmgr-*` 前缀，无命名冲突

---

## 五、新增依赖

### Python 后端

`qdrant-client` 已存在于 `requirements.txt`（由 `langchain-qdrant` 依赖引入）。本次新增 import:

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue
```

### 前端

无新依赖，全部使用已有 axios + React hooks。

---

## 六、测试验证

### 手动测试步骤

1. **上传文档**: 用 POST /documents/upload 上传 2-3 个不同类型的文档
2. **列表验证**: GET /documents 确认返回正确的文件列表和 chunk 数
3. **删除验证**: 
   - DELETE /documents/intro.pdf → 返回 deleted_chunks > 0
   - GET /documents → 确认 intro.pdf 已消失
   - 再次 DELETE /documents/intro.pdf → 返回 404
4. **前端验证**:
   - 点击 "Browse & Delete" 按钮 → 面板弹出
   - 文档按类型分组显示
   - 点击删除按钮 → 文档消失 → 成功消息出现
   - 关闭面板 → 重新打开 → 列表已更新
5. **边界情况**:
   - 删除不存在的文档 → 404
   - 空数据库 → 返回空列表 + 前端显示空状态
   - 含特殊字符的文件名 → URL 编码正常处理

---

## 七、日志影响

本次新增未添加 RAG 步骤级日志（与文档管理流程分离）。文档管理操作使用 Python `logging` 模块的默认 INFO 级别（由 FastAPI 请求日志自动记录）。

---

## 八、与现有系统的影响

- **无破坏性变更**: 现有 POST /upload、POST /rag/query、GET /health 完全不变
- **向前兼容**: 新增的 GET /documents、DELETE /documents/{source} 不影响任何现有路由
- **Sidebar 布局**: 新增 "Manage Documents" section 追加在 "Upload Document" 下方，不改变现有 UI 逻辑
