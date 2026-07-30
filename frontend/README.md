# Local RAG Frontend

React 19 + Vite 的单页聊天界面，提供：

- SSE token 流式渲染与搜索/精排/生成状态；
- 生成期间可用输入区停止按钮取消 SSE；
- `rag` / `direct` / `greeting` 路由标记；
- 对话列表、切换和删除；
- PDF、TXT、MD、Markdown、DOCX 多文件上传；
- 正确区分新索引、已经是最新版本和失败状态；
- 按类型展示文档，并优先使用稳定 `document_id` 删除；
- 来源只展示原始数值 `Score`，不把不同量纲的 vector、Cross-Encoder 和 Hybrid 分数误标成统一的高/中/低置信度；
- assistant Markdown 渲染和 CJK 换行优化。

## 启动

```bash
npm ci
cp .env.example .env
npm run dev
```

默认地址：`http://127.0.0.1:5173`。

配置：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_KEY=
```

只有后端设置了 `APP_API_KEY` 时才填写 `VITE_API_KEY`。Vite 环境变量会进入浏览器 bundle，因此这里的 key 只适合本地/可信内网的简单共享口令。

## 验证

```bash
npm run lint
npm run build
```

## SSE 客户端契约

`src/api.js` 使用 `fetch` 和 `ReadableStream` 解析：

```text
routing → status* → token* → sources → done
```

错误：

```text
[routing] → [status*] → error → done
```

每个 `data:` 都是 JSON；token 也是 JSON 字符串。解析器把 `currentEvent` 保留在多次 `reader.read()` 之间，以处理 event/data 被网络 chunk 拆开的情况。

`queryRagStream` 接受 `AbortSignal`，输入区在生成期间会切换为停止按钮。后端在请求取消或生成失败时不会保存半截回答。

## 代码结构

```text
src/App.jsx   当前全部页面状态和 UI
src/api.js    Axios JSON API + fetch SSE 客户端
src/App.css   Editorial Ink 组件样式
src/index.css reset、纹理和本地系统字体栈
```

当前 `App.jsx` 仍是大型单组件。功能继续增长时，应拆分为 chat、upload、documents、conversations 组件及对应 hooks；这是已知重构方向，不是当前已经完成的能力。

## 容器

```bash
docker build \
  --build-arg VITE_API_BASE_URL=http://127.0.0.1:8000 \
  -t local-rag-frontend .
```

仓库根目录也可运行：

```bash
docker compose --profile full up --build -d
```

镜像使用多阶段构建，最终由 Nginx 提供静态文件和 SPA fallback。
