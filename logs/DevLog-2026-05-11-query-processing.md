# Dev Log — Pre-Retrieval Query Processing

> **Date**: 2026-05-11
> **Tags**: feature, rag, query-processing, llm

---

## 一、概述

在 RAG 管道中新增检索前（pre-retrieval）查询处理步骤。用户问题在进入向量检索之前，先由 LLM 进行一次轻量处理：识别意图并改写为更清晰的查询语句。改写后的查询用于向量检索，但最终答案生成仍使用原始用户问题。

## 二、新增/修改的文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/rag/query_processor.py` | **新增** | 查询处理模块：LLM 调用、意图识别（4 类）、查询改写、失败回退 |
| `app/services/rag_service.py` | **修改** | 在检索前插入 `process_query()` 调用，改写后的查询用于检索，原始问题用于答案生成 |
| `CLAUDE.md` | **修改** | 架构部分新增 query_processor.py 描述，更新 rag_service 管道说明 |

## 三、实现细节

**新增 RAG 管道流程：**
```
User Query → LLM Query Processing → Rewritten Query → Embedding → Retrieval → Context → LLM Answer → Final Answer
```

**查询处理 Prompt 设计：**
- 系统 prompt 定义两类输出：意图（INTENT）和改写查询（QUERY）
- 意图分类：`question_answering`、`summarization`、`comparison`、`fact_lookup`
- 输出格式严格为两行，便于解析

**失败回退：**
- `process_query()` 内部 try/except 包裹全部逻辑
- LLM 调用失败时返回 `{"intent": "unknown", "rewritten_query": <原始问题>}`
- 解析失败（如 LLM 输出格式异常）时同样回退到原始问题

**关键设计决策：**
- 使用与答案生成相同的 LLM（`get_llm()`），不引入第二个模型
- 改写查询仅用于检索，原始问题保留用于答案生成，确保答案直接回应用户
- 不引入新的配置项或环境变量

## 四、验证

- ✅ `process_query` 模块可正常导入
- ✅ `rag_service.query_rag` 可正常导入（依赖链完整）
- ✅ LLM 调用成功时返回解析后的 intent 和 rewritten_query
- ✅ LLM 调用失败时静默回退到原始查询（日志记录 warning）
