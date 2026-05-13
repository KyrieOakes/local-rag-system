# Dev Log — RAG 检索层评估体系

> **日期**: 2026-05-13
> **标签**: feature, rag-evaluation, retrieval, metrics, testing, visualization, notebook, chunking-comparison

---

## 一、概述

新增一套面向 RAG Retrieval 层的离线评估体系，用于判断系统是否能把正确、少噪声、少重复的上下文检索出来。包含四个层次：

1. **指标层** — 纯数学指标函数（Recall@K, Precision@K, MRR, NDCG@K, 上下文冗余率等）
2. **匹配层** — 将 golden dataset 的 source/snippet 标注映射到当前检索 chunk
3. **CLI 运行器** — 复用生产 retriever，输出结构化 JSON 报告
4. **Jupyter Notebook** — 完整的测试 pipeline + 11 张可视化图表 + 分块策略对比

---

## 二、新增/修改的文件清单

### 评估模块（Python）

| 文件 | 操作 | 说明 |
|------|------|------|
| `evaluation/__init__.py` | **新增** | 声明 evaluation 为项目内评估工具包 |
| `evaluation/README.md` | **新增/重写** | 中文说明检索层评估目标、指标体系、golden dataset、chunking 策略对比方式 |
| `evaluation/run_retrieval_eval.py` | **新增** | 检索评估 CLI runner，调用现有 retriever 并输出 JSON 实验报告 |
| `evaluation/retrieval_eval_pipeline.ipynb` | **新增** | Jupyter Notebook：完整测试 pipeline + 11 张可视化图表 + 分块策略对比 |
| `evaluation/retrieval_metrics/__init__.py` | **新增** | 导出检索指标函数 |
| `evaluation/retrieval_metrics/metrics.py` | **新增** | 实现 Recall@K、Precision@K、MRR、NDCG@K、上下文冗余度等指标 |
| `evaluation/retrieval_metrics/matching.py` | **新增** | 将 golden dataset 中的 source/snippet 标注映射到当前检索 chunk |
| `evaluation/retrieval_metrics/evaluator.py` | **新增** | 统一评估入口，按 `core_metrics` 和 `context_quality` 输出结果 |
| `evaluation/datasets/golden_retrieval.example.jsonl` | **新增/扩展** | 从 2 条扩展到 22 条高质量 golden questions，覆盖 8 个主题领域 |

### 测试（Python unittest）

| 文件 | 操作 | 说明 |
|------|------|------|
| `tests/test_retrieval_metrics.py` | **新增** | 覆盖核心指标、上下文冗余度、边界输入（16 个用例） |
| `tests/test_retrieval_matching.py` | **新增** | 覆盖 file_path/source/snippet 匹配逻辑（6 个用例） |
| `tests/test_retrieval_evaluator.py` | **新增** | 覆盖统一 evaluator 输出结构和典型检索质量场景（3 个用例） |

### 项目配置

| 文件 | 操作 | 说明 |
|------|------|------|
| `CLAUDE.md` | **更新** | 新增 evaluation 命令、notebook 说明、可视化依赖 |
| `logs/DevLog-2026-05-13-RAG检索层评估.md` | **重写** | 合并所有本轮变更的完整记录 |

---

## 三、Golden Dataset

### 格式

```json
{"id":"q01","question":"What is the organizational structure of the AI Engineering department?","relevant_sources":[{"file_path":"data/engineering/ai/_index.md","text":"Editors Extensions","relevance":2},{"file_path":"data/engineering/ai/_index.md","text":"Code Creation","relevance":2}]}
```

### 字段说明

- `id`：评估样本 ID，稳定且可读
- `question`：检索问题
- `relevant_sources`：人工标注的相关证据列表
- `file_path`：相关证据所在文件路径（推荐填写）
- `source` / `file_name`：可选，用于匹配上传文件名或展示名
- `text`：可选的文本片段，用于避免只按文件命中过宽
- `relevance`：分级相关性分数（1.0~3.0），用于 NDCG@K

### 覆盖范围

22 条 golden questions 覆盖 8 个主题领域：

| 主题 | 问题数 | 示例 ID |
|------|--------|----------|
| AI Engineering 组织结构 | 1 | q01 |
| Global Search（RAG/ES/Zoekt/运维） | 5 | q02, q12, q18, q19 |
| Code Creation（模型评估/上线/API） | 4 | q03, q07, q08, q17, q21 |
| Duo Chat（技术策略/韧性/监控） | 3 | q04, q14, q22 |
| Duo Workflow（团队流程/架构） | 2 | q13, q20 |
| 职业发展（晋升/级别/导师） | 4 | q05, q06, q11, q15 |
| 管理岗位（Acting/Interim） | 1 | q16 |
| Editor Extensions / Milestone Planning | 2 | q09, q10 |

所有 `text` 字段均从对应源文档中提取的原文片段，确保 snippet 匹配能正确命中。

---

## 四、CLI 设计

### `evaluation/run_retrieval_eval.py`

```bash
conda activate localrag

# 基础用法
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name recursive-800-120

# 含 query processor
python evaluation/run_retrieval_eval.py \
  --dataset evaluation/datasets/golden_retrieval.example.jsonl \
  --top-k 5 \
  --experiment-name recursive-800-120-qp \
  --use-query-processor
```

### 参数

| 参数 | 说明 |
|------|------|
| `--dataset` | golden retrieval JSONL 数据集路径 |
| `--top-k` | 评估 top-k 检索结果 |
| `--experiment-name` | 实验名称，建议包含 chunking 策略（如 `chunk-800-120`） |
| `--output-dir` | 报告输出目录，默认 `evaluation/results` |
| `--use-query-processor` | 是否把 query rewriting 纳入评估 |

报告输出：`evaluation/results/<experiment-name>.json`

---

## 五、Jupyter Notebook

### `evaluation/retrieval_eval_pipeline.ipynb`

完整的评估流水线 notebook，所有 markdown 为中文，包含以下章节：

| 章节 | 内容 | 图表 |
|------|------|------|
| §1-3 | 环境配置、加载 22 条 golden dataset | — |
| §4 | 双模式评估引擎（LIVE/DEMO） | — |
| §5-6 | 构建 DataFrame + 聚合统计 | 汇总表 |
| §7 | 逐题核心指标条形图 | 1 张 (2×2) |
| §8 | 逐题上下文质量条形图 | 1 张 (1×3) |
| §9 | 聚合指标总览（含误差棒） | 1 张 (1×2) |
| §10 | 六维检索质量雷达图 | 1 张 |
| §11 | Top-K 敏感度分析 (K=1..10) | 1 张 (1×2) |
| §12 | Recall 分布 + Recall vs Precision 散点图 | 1 张 (1×2) |
| §13 | 指标相关性热力图 | 1 张 |
| §14-15 | JSON 报告导出 + 自动诊断 | — |
| §16 | **分块策略对比** | 4 张 |

**分块策略对比子章节（§16a–§16f）：**

| 子章节 | 说明 |
|--------|------|
| 16a | 策略对比汇总表 — 带颜色渐变的格式化表格 |
| 16b | 核心指标对比柱状图 — 所有策略并排 |
| 16c | 上下文质量对比 — 冗余率/无关率/重复率 |
| 16d | 雷达图叠加 — 所有策略在同一雷达图上叠加 |
| 16e | 权衡分析散点图 — Recall vs. Precision，每个点标注策略名 |
| 16f | 逐题召回差异热力图 — 定位对分块策略敏感的问题（需真实报告） |

### 分块策略对比使用流程

1. 修改 `.env` 中的 `CHUNK_SIZE` 和 `CHUNK_OVERLAP`
2. 重新摄入文档：`python ingest.py --input_dir data/engineering --batch_size 64`
3. 运行 CLI 评估：`python evaluation/run_retrieval_eval.py --experiment-name chunk-800-120`
4. 重复 1-3，每次使用不同的 `--experiment-name`
5. 在 notebook 中运行 §16 的单元格，自动加载所有报告并生成对比图表

当 `evaluation/results/` 目录下没有真实报告时，notebook 会自动生成 4 组模拟实验数据用于演示对比功能。

### 两种运行模式

- **DEMO 模式**（`LIVE_MODE = False`，默认）：使用模拟检索结果，不依赖任何外部服务，可离线运行
- **LIVE 模式**（`LIVE_MODE = True`）：调用真实 Qdrant vectorstore 和 embedding 服务进行检索

---

## 六、实现细节

### 6.1 评估 Pipeline

```text
golden dataset
    ↓
读取每个 question
    ↓
可选：query_processor 做 query rewriting
    ↓
调用现有 retrieve_relevant_documents
    ↓
将 LangChain Document 转成 RetrievedItem
    ↓
使用 relevant_sources 做 source/snippet-aware 匹配
    ↓
计算 core_metrics + context_quality
    ↓
输出 retrieval-eval-v1 JSON 报告
```

### 6.2 核心指标

- `Recall@K`：正确证据是否被召回
- `Precision@K`：top-k 上下文中有多少是有用内容
- `MRR`：第一个正确文档的倒数排名
- `NDCG@K`：支持二元和分级相关性的排序质量

### 6.3 上下文质量指标

- `context_redundancy@K`：无关 + 重复上下文的综合比例
- `irrelevant_rate@K`：top-k 中未命中标注证据的比例
- `duplicate_rate@K`：top-k 中重复上下文的比例

### 6.4 匹配层设计

不把 `chunk_index` 作为 golden dataset 的核心标注，因为切换 chunking 策略后 chunk 边界和 index 会变化。改为标注稳定证据来源（file_path + text snippet），再由匹配层映射到当前策略生成的 chunk。

支持：
- 按 `file_path` 匹配
- 按 `source` / `file_name` 匹配上传文档
- 按 `text` snippet 匹配 chunk 内容（大小写和空白容错）
- 未匹配项保留 `expected:<index>` 虚拟项用于 NDCG ideal ranking

### 6.5 分块策略对比机制

`load_all_reports()` 函数扫描 `evaluation/results/` 目录下的所有 `retrieval-eval-v1` 格式报告，提取聚合指标构建对比 DataFrame，然后生成 4-5 张对比图表。不需要额外配置 — 只要报告在目录里就会被自动加载。

---

## 七、新增依赖

### Python 依赖（已安装到 conda `localrag` 环境）

| 包 | 用途 |
|----|------|
| `matplotlib` | 基础绑图 |
| `seaborn` | 热力图和样式 |
| `pandas` | DataFrame 和格式化表格 |
| `numpy` | 数值计算 |
| `jupyter` | Notebook 运行环境 |
| `nbconvert` | Notebook 执行和导出 |

安装命令：

```bash
conda activate localrag
pip install matplotlib seaborn pandas jupyter nbconvert
```

---

## 八、测试验证

### 自动化测试

```bash
python -m unittest tests/test_retrieval_metrics.py tests/test_retrieval_matching.py tests/test_retrieval_evaluator.py
```

结果：**25 tests, OK**

### Notebook 执行验证

```bash
jupyter nbconvert --to notebook --execute --inplace evaluation/retrieval_eval_pipeline.ipynb
```

结果：**22 个代码单元全部执行成功，生成 11 张 PNG 图表，无错误**

### 重点测试场景

- 正确文档在 top-k 外时 Recall 从 0 到 1 的变化
- top-k 中混入噪声时 Precision 被惩罚
- 重复 chunk 时 duplicate_rate 上升
- 错文件中出现相同 snippet 不算命中
- 上传文件只靠 `source` / `file_name` 也能匹配
- snippet 匹配支持大小写和空白容错
- 完全 miss 时 Recall、Precision、MRR 都为 0，irrelevant_rate 为 1
- 分级相关性下 NDCG 能奖励高价值证据排在前面

---

## 九、边界情况

- 只评估 Retrieval 层，不评估 LLM 生成答案质量
- 评估脚本不会自动切换 chunking 策略或重建 Qdrant collection
- 分块策略对比需要手动变更配置 → 重新摄入 → 运行 CLI → 回到 notebook
- `run_retrieval_eval.py` 依赖当前 Qdrant、embedding 服务和 `.env` 配置可用
- Notebook DEMO 模式可离线运行，但对比功能需要真实报告才能体现策略差异
- 示例 golden dataset 从真实文档提取了 22 条问题，后续需要持续维护

---

## 十、与现有系统的影响

- **无 API 破坏性变更**：未修改 FastAPI 路由、请求结构或响应结构
- **无前端影响**：未修改 React/Vite 前端逻辑
- **评估模块可独立运行**：不影响正常 RAG 查询流程
- **支持策略对比**：通过不同 `--experiment-name` 保存多份报告，notebook 自动加载对比
- **Notebook 含演示模式**：无需启动任何服务即可看到完整的可视化效果
