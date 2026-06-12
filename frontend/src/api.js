/**
 * 后端 API 通信层。
 *
 * 封装所有与 FastAPI 后端（http://127.0.0.1:8000）的 HTTP 请求：
 * - healthCheck() — GET /health，检查后端在线状态
 * - uploadDocument(file) — POST /documents/upload，上传单个文件
 * - uploadDocuments(files) — POST /documents/upload-batch，批量上传文件
 * - queryRag({question, conversationId, history, forceRag}) — POST /rag/query，发送 RAG 查询
 * - listDocuments() — GET /documents，列出已索引文档
 * - deleteDocument(source) — DELETE /documents/{source}，删除文档
 *
 * 所有请求通过 axios 实例发送，baseURL 统一配置。
 */
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://127.0.0.1:8000',
});

export async function healthCheck() {
  const res = await api.get('/health');
  return res.data;
}

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await api.post('/documents/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });

  return res.data;
}

export async function uploadDocuments(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }

  const res = await api.post('/documents/upload-batch', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });

  return res.data;
}

export async function queryRag({ question, conversationId, history, forceRag }) {
  const res = await api.post('/rag/query', {
    question,
    conversation_id: conversationId || null,
    history: history || [],
    force_rag: forceRag || false,
  });
  return res.data;
}

export async function listDocuments() {
  const res = await api.get('/documents');
  return res.data;
}

export async function deleteDocument(source) {
  const res = await api.delete(`/documents/${encodeURIComponent(source)}`);
  return res.data;
}

/**
 * Stream a RAG query via SSE (Server-Sent Events).
 *
 * @param {Object} params
 * @param {string} params.question
 * @param {string|null} params.conversationId
 * @param {Array} params.history
 * @param {boolean} params.forceRag
 * @param {Object} callbacks
 * @param {function} callbacks.onRouting - ({routing, conversation_id}) => void
 * @param {function} callbacks.onStatus - ({phase, message}) => void
 * @param {function} callbacks.onToken - (token: string) => void
 * @param {function} callbacks.onSources - (sources: Array) => void
 * @param {function} callbacks.onDone - () => void
 * @param {function} callbacks.onError - ({message, phase}) => void
 */
export async function queryRagStream(
  { question, conversationId, history, forceRag },
  callbacks
) {
  const response = await fetch('http://127.0.0.1:8000/rag/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      conversation_id: conversationId || null,
      history: history || [],
      force_rag: forceRag || false,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = null; // persists across reader.read() calls to handle split event/data lines

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ') && currentEvent) {
          const data = line.slice(6);
          try {
            const parsed = JSON.parse(data);
            switch (currentEvent) {
              case 'routing':
                callbacks.onRouting?.(parsed);
                break;
              case 'status':
                callbacks.onStatus?.(parsed);
                break;
              case 'token':
                callbacks.onToken?.(parsed);
                break;
              case 'sources':
                callbacks.onSources?.(parsed);
                break;
              case 'done':
                callbacks.onDone?.();
                break;
              case 'error':
                callbacks.onError?.(parsed);
                break;
            }
          } catch {
            // Safety net: if JSON parse fails unexpectedly, log and ignore
            console.warn('SSE: failed to parse data for event', currentEvent, data);
          }
          currentEvent = null;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
