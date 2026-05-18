/**
 * 后端 API 通信层。
 *
 * 封装所有与 FastAPI 后端（http://127.0.0.1:8000）的 HTTP 请求：
 * - healthCheck() — GET /health，检查后端在线状态
 * - uploadDocument(file) — POST /documents/upload，上传单个文件
 * - uploadDocuments(files) — POST /documents/upload-batch，批量上传文件
 * - queryRag(question) — POST /rag/query，发送 RAG 查询
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

export async function queryRag(question) {
  const res = await api.post('/rag/query', { question });
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
