# Dev Log — 项目中文注释 + 评估 Notebook 面试展示优化 + 检索评估首轮结果

> **日期**: 2026-05-18
> **标签**: documentation, notebook, evaluation, visualization, bugfix, interview-ready, retrieval-tuning, embedding

---

## 一、概述

本轮工作分为五个层面：

1. **全项目中文化** — 为 55 个源文件添加中文文件头注释
2. **评估 Notebook 优化** — 将第 16 节升级到面试展示级，自动提取配置信息、优化图表、增加诊断
3. **Bug 修复**（7 项）— 覆盖配置读取、集合重建、路径检测、LLM 分支互换等
4. **首轮检索评估** — 完成 chunk=800/120 vs chunk=256/50 两组对比实验
5. **调优方向确定** — 基于实验数据给出优先级排序

---

## 二、新增/修改的文件清单

### 中文注释（全覆盖，55 个文件）

| 层级 | 文件数 | 说明 |
|------|--------|------|
| `app/main.py` | 1 | FastAPI 入口 |
| `app/api/` | 4 | health / documents / rag 路由 + `__init__` |
| `app/core/` | 3 | config / logging |
| `app/llm/` | 2 | local_llm 工厂 |
| `app/rag/` | 9 | loader → splitter → embeddings → retriever → chain → prompt → query_processor → query_logger → vectorstore |
| `app/rag/ingestion/` | 5 | checksum_store → batch_embedder → bulk_writer → ingest_pipeline |
| `app/schemas/` | 3 | rag.py / document.py |
| `app/services/` | 4 | ingestion / document / rag 服务 |
| `app/utils/` | 3 | file_utils / id_utils |
| `evaluation/` | 5 | run_retrieval_eval / metrics / matching / evaluator |
| `frontend/` | 6 | App.jsx / App.css / index.css / api.js / main.jsx / vite.config.js / eslint.config.js |
| `ingest.py` | 1 | CLI 批量摄取脚本 |
| `scripts/` | 2 | clear_qdrant / ingest_sample_docs |
| `tests/` | 6 | 3 个检索评估测试 + 3 个占位测试 |

### Notebook 优化（cells 0-44）

| Cell | 改动 |
|------|------|
| cell-0 | 标题加入"策略对比与面试展示"，补充完整使用流程 |
| cell-2 | 修复 ROOT_DIR 检测（向上查找含 `app/` 的目录而非 `Path.cwd().parent`）；`os.chdir(ROOT_DIR)` 确保 pydantic-settings 找到 `.env`；启动时打印当前配置 + `.env` 存在状态 |
| cell-4 | `DATASET_PATH` 改为 `evaluation/datasets/...`；`OUTPUT_DIR` 改为 `evaluation/results`；打印实验名提示 |
| cell-16 | 修复 `colors` 变量未定义（改 `bar_color_context` + `mean_color` 独立变量） |
| cell-28 | **修复：** 报告 JSON 中加入 `settings_snapshot`（chunk_size / embedding_model / chunk_overlap / qdrant_collection）；从 `app.core.config` 导入 settings |
| cell-31 | 通用化标题 + 完整对比测试流程（5 步）+ 重置命令 + 关键提醒 |
| cell-32 | `load_all_reports` 新增 `_short_label`、`_chunk_size`、`_embedding_model`、`_display_name` 字段；默认路径改为 `evaluation/results`；加载后打印每份报告的配置+指标摘要 |
| cell-34 | 对比表新增 `Chunk` 和 `Embedding Model` 列；打印 🏆 最优策略 |
| cell-36 | 柱状图 legend 自动显示 `experiment \| chunk \| embedding`；专业配色+百分比格式化 |
| cell-38 | 上下文质量图同 36 风格 |
| cell-39 | 新增雷达图含义解释 |
| cell-40 | 雷达图使用 husl 高区分度配色；legend 移到图外 |
| cell-42 | Recall vs Precision 散点图改为象限分析；标注 ★ IDEAL ZONE |
| cell-44 | 热力图新增逐题敏感度分析：Recall 波动最大/最小 3 个问题 |

### Bug 修复（7 项）

| 文件 | 问题 | 修复 |
|------|------|------|
| `app/llm/local_llm.py` | `"local"` / `"cloud"` 分支互换 | 交换条件判断 |
| `.env` | 缺失 + 地址错误（10.0.0.79:4399 不通） | 从 `.env.example` 创建，改回 10.0.0.59:1234 |
| `evaluation/results/*.json` | 旧报告缺少 `settings_snapshot` | 清理后由修复后的 cell-28 重新生成 |
| `notebook cell-2` | `Path.cwd().parent` 在 Jupyter 中不稳定 | 改为向上查找含 `app/` 目录 + `os.chdir()` |
| `notebook cell-16` | `colors` 变量未定义 | 改为 `bar_color_context` 独立变量 |
| `notebook cell-4/28/32` | 路径相对于旧 cwd（evaluation/） | 改为项目根目录相对路径 |
| `app/rag/ingestion/bulk_writer.py` | clear_qdrant 后 upsert 失败（集合不存在） | `bulk_upsert_chunks()` 增加自动创建集合逻辑 |

---

## 三、关键设计决策

### 3.1 `settings_snapshot` 自动写入

Notebook cell-28 的报告导出现在自动从 `app.core.config.settings` 读取当前配置快照，对比表通过 `load_all_reports` 自动提取。

### 3.2 配置读取链路

```
.env → pydantic-settings → Settings() → 全局 settings 单例
    │
    ├── ingest.py（新进程，每次读最新 .env）
    ├── API 服务
    ├── Notebook 评估（需 Restart Kernel 才能读最新 .env）
    └── CLI 评估工具
```

### 3.3 ROOT_DIR 健壮检测

从 `Path.cwd().parent` 改为 `while` 循环向上查找含 `app/` 子目录的路径，解决 Jupyter 在不同目录启动时路径错乱的问题。

### 3.4 集合自动创建

`bulk_writer.py` 的 `bulk_upsert_chunks()` 在写入前检测集合是否存在，不存在则从第一条 embedding 推断向量维度并自动创建。消除 `clear_qdrant` 后需手动重建集合的步骤。

---

## 四、首轮检索评估结果

### 实验配置

| 实验 | chunk_size | chunk_overlap | embedding_model |
|------|-----------|--------------|-----------------|
| #1 | 800 | 120 | text-embedding-qwen3-embedding-4b |
| #2 | 256 | 50 | text-embedding-qwen3-embedding-4b |

### 结果对比

| 指标 | chunk=800/120 | chunk=256/50 | 变化 |
|------|:-----------:|:----------:|:----:|
| Recall@5 | 0.5909 | 0.6364 | **+7.7%** |
| Precision@5 | 0.1818 | 0.1636 | -10.0% |
| MRR | 0.3326 | 0.3826 | **+15.0%** |
| NDCG@5 | 0.3251 | 0.3013 | -7.3% |
| 上下文冗余率 | 0.8182 | 0.8364 | +2.2% |

### 诊断

- 小 chunk 提升了 Recall 和 MRR，说明更细粒度的分块有助于找到相关文档
- 但 Precision 仅 16-18%、冗余率 82-84%，说明 top-5 中约 80% 是噪声 — 仅靠调 chunk 参数无法根本改善
- 两个实验的 duplicate_rate 均为 0，说明 chunk_overlap 不是当前问题

### 调优建议（按优先级）

1. **换 embedding 模型**（最高优先级）：LM Studio 上已有 `text-embedding-nomic-embed-text-v1.5`，在检索 benchmark 上通常优于 qwen3-embedding
2. **开启 query_processor**：LLM 改写查询可扩展模糊术语、补全关键词
3. **提升 top-K**：从 5 试到 7 或 10，观察 Recall 提升幅度
4. **chunk_size 试 400-500，overlap 试 80-100**：256 可能过小而破坏语义完整性
5. **re-rank**：方向对，但优先级放在上游优化之后

---

## 五、与现有系统的影响

- **无 API 破坏性变更**：未修改 FastAPI 路由或数据结构
- **无前端影响**：未修改 React 组件逻辑
- **.env 文件新增**：从 `.env.example` 创建，`.gitignore` 已排除
- **local_llm bug 修复**：`llm_provider="local"` → 本地配置，"cloud" → 云端配置
- **bulk_writer 增强**：集合不存在时自动创建，消除重置后的手动步骤
- **Notebook 向前兼容**：旧报告（无 `settings_snapshot`）显示 `?`，新报告自动填充

---

## 六、操作指南

```bash
# 完整对比测试流程
# 1. 改 .env
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
# 2. 清空
python scripts/clear_qdrant.py && rm -f data/ingestion_state.db
# 3. 摄入（集合自动创建）
python ingest.py --input_dir data/engineering --batch_size 64
# 4. 评估（CLI 或 Notebook 二选一）
python evaluation/run_retrieval_eval.py --dataset ... --experiment-name emb-nomic-chunk400
# 5. 重复 1-4 换配置，最后 Notebook §16 看对比
```
