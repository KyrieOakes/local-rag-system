# Dev Log — API 密钥泄露修复

> **日期**: 2026-07-18
> **标签**: security, secrets, configuration, git-history

---

## 一、概述

移除 `app/core/config.py` 中曾被提交的云端 API 密钥，将云端凭据改为只能通过本地 `.env` 或进程环境变量注入；补充安全回归测试，并在 `CLAUDE.md` 与 `AGENTS.md` 中加入仓库级密钥管理规则。

由于密钥曾进入 Git 历史，本次同时重写 `main` 分支历史并强制推送清理后的提交链。旧密钥必须在服务商控制台吊销/轮换，Git 历史清理不能恢复其安全性。

---

## 二、新增/修改的文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/core/config.py` | **修改** | 云端 API Key 默认值改为空，只允许环境注入 |
| `.env.example` | **修改** | 新增安全的 Cloud LLM 配置模板，Key 保持空值 |
| `tests/test_config.py` | **新增** | 验证源码默认值为空及环境变量覆盖行为 |
| `CLAUDE.md` | **修改** | 新增凭据处理、提交检查、泄露响应和日志脱敏规则 |
| `AGENTS.md` | **修改** | 同步安全规则与测试数量 |
| Git `main` 历史 | **重写** | 从历史版本的配置文件中删除已提交凭据 |

---

## 三、API 设计

本次没有新增或修改 HTTP API。配置契约调整如下：

```dotenv
LLM_PROVIDER=cloud
CLOUD_LLM_BASE_URL=https://api.deepseek.com
CLOUD_LLM_MODEL=deepseek-chat
CLOUD_LLM_API_KEY=<仅存放在本地 .env 或部署环境>
```

---

## 四、实现细节

### 4.1 安全默认值

`Settings.cloud_llm_api_key` 的源码默认值为空字符串。开发者选择 `LLM_PROVIDER=cloud` 时，必须通过环境变量或被 `.gitignore` 排除的 `.env` 提供凭据。

### 4.2 仓库规则

- 禁止在源码、测试、日志、Notebook、示例、截图和文档中提交真实凭据。
- `.env.example` 只能保留变量名和安全占位值。
- 提交前检查 staged diff，不允许终端和异常输出真实密钥。
- 已提交的密钥必须吊销并清理历史，后续删除提交不能视为完成修复。

### 4.3 Git 历史

重写 `main` 中包含泄露配置的历史提交，并使用 `--force-with-lease` 更新远端。协作者需要重新拉取或重新克隆，避免把旧历史再次推回远端。

---

## 五、新增依赖

无新增依赖。

---

## 六、测试验证

```bash
conda activate localrag
python -m unittest discover tests/
```

验证范围包括：源码默认值不包含 Cloud Key、环境变量能够注入配置，以及原有 API/检索评估测试全部回归通过。

---

## 七、边界情况

- 本地 `.env` 不会被修改或提交；如其中仍使用旧 Key，轮换后需要人工更新。
- GitHub 分支历史清理不等于密钥吊销；fork、clone、缓存和日志中仍可能存在旧值。
- 强制推送后，基于旧历史的本地分支不得直接合并回 `main`。

---

## 八、影响分析

- **安全性提升**：公开源码和新 Git 历史不再包含云端密钥。
- **配置变化**：Cloud 模式不再提供凭据默认值，部署时必须显式注入。
- **本地模式无影响**：LM Studio/Ollama 的本地占位 Key 行为保持不变。
- **协作影响**：历史重写后，其他开发者需要同步新的 `main` 提交链。
