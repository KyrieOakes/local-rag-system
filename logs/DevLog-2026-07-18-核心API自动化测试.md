# Dev Log — 核心 API 自动化测试补全

> **日期**: 2026-07-18
> **标签**: testing, unittest, fastapi, sse, regression

---

## 一、概述

将原有的健康检查、RAG 和文档 API 占位测试替换为可执行的 FastAPI 回归测试，并新增会话历史 API 测试。测试通过 `TestClient` 驱动真实路由、请求校验和响应模型，通过 `unittest.mock` 隔离 Qdrant、Embedding、LLM 与 SQLite 边界，确保测试可离线、快速、稳定运行。

测试总数由 25 个提升至 54 个，其中新增 29 个核心 API 测试。

---

## 二、新增/修改的文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tests/test_health.py` | **重写** | 覆盖根路径、健康检查、错误 HTTP 方法和 OpenAPI 核心路由注册 |
| `tests/test_documents.py` | **重写** | 覆盖单文件上传、批量部分失败、列表、删除、400/404/500 分支 |
| `tests/test_rag.py` | **重写** | 覆盖同步查询、默认参数、Pydantic 校验、服务异常和 SSE 事件流 |
| `tests/test_conversations.py` | **新增** | 覆盖会话列表、详情、删除及空结果、404、存储异常 |
| `AGENTS.md` | **修改** | 记录四个 API 路由模块与 54 个离线测试的当前状态 |

---

## 三、API 设计

本次未新增或修改生产 API。自动化测试覆盖以下现有接口：

| 方法 | 路径 | 主要验证内容 |
|------|------|--------------|
| `GET` | `/` | 服务欢迎响应 |
| `GET` | `/health` | 健康状态与方法限制 |
| `POST` | `/documents/upload` | 上传成功、扩展名校验、摄入异常 |
| `POST` | `/documents/upload-batch` | 批量请求与部分失败响应 |
| `GET` | `/documents` | 文档列表与服务异常 |
| `DELETE` | `/documents/{source}` | 路径型 source、成功、404、500 |
| `POST` | `/rag/query` | 参数传递、响应模型、422、500 |
| `POST` | `/rag/query/stream` | SSE Content-Type、缓存头和事件序列 |
| `GET` | `/conversations` | 正常列表、空列表、500 |
| `GET` | `/conversations/{id}` | 消息详情、404、500 |
| `DELETE` | `/conversations/{id}` | 删除成功、404、500 |

---

## 四、实现细节

### 4.1 测试边界

- 使用 FastAPI `TestClient` 执行真实路由匹配、请求体解析、Pydantic 校验和响应序列化。
- 使用 `patch` 替换 API 模块已经导入的 service/store 函数，避免访问 Qdrant、SQLite 和模型服务。
- 使用 `AsyncMock` 模拟异步文件保存，保留 multipart 请求解析的真实行为。
- 使用异步生成器模拟 RAG 流式服务，验证 `text/event-stream`、`Cache-Control` 及 routing/token/sources/done 事件。

### 4.2 错误与边界覆盖

- 空问题和非法 history role 返回 422。
- 不支持的上传扩展名返回 400。
- 不存在的文档和会话返回 404。
- Qdrant、摄入服务、RAG 服务和会话存储异常映射为 500。
- 批量上传单个文件失败时，其余文件仍保留成功结果。

---

## 五、新增依赖

无新增依赖。测试使用 Python 标准库 `unittest`、`unittest.mock` 以及项目现有 FastAPI/Starlette `TestClient`。

---

## 六、测试验证

执行命令：

```bash
conda activate localrag
python -m unittest discover tests/ -v
```

验证结果：

```text
Ran 54 tests in 0.055s
OK
```

所有测试均在未启动 Qdrant、LM Studio 和前端的情况下通过。

---

## 七、边界情况

- SSE 测试验证 API 协议与事件透传，不调用真实生成模型；真实模型断流仍属于后续集成测试范围。
- 文档 API 使用 mock 验证路由与服务契约，不验证真实 Qdrant upsert/delete；该部分适合由 Docker 集成测试补充。
- 异常分支会触发应用日志中的预期 traceback，不代表测试失败。

---

## 八、影响分析

- **无生产行为变化**：本次只新增/修改测试、项目说明和 DevLog。
- **回归保护增强**：核心 API 的请求校验、状态码、参数转发、响应结构和 SSE 协议已有自动验证。
- **执行成本低**：54 个测试约 0.06 秒完成，适合后续接入 CI 作为每次提交的必跑检查。
- **剩余缺口**：尚未覆盖真实 Qdrant/Embedding/LLM 集成链路、浏览器端 SSE 解析及前端组件交互。
