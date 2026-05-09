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

export async function queryRag(question, topK = 4) {
  const res = await api.post('/rag/query', {
    question,
    top_k: topK,
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
