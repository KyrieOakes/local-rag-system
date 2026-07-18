"""FastAPI 应用入口与健康检查端点测试。"""

import unittest

from fastapi.testclient import TestClient

from app.main import app


class HealthApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_root_returns_service_message(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Local RAG System 正在运行"})

    def test_health_returns_ok(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_rejects_unsupported_method(self):
        response = self.client.post("/health")

        self.assertEqual(response.status_code, 405)

    def test_openapi_exposes_core_routes(self):
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/health", paths)
        self.assertIn("/documents/upload", paths)
        self.assertIn("/rag/query", paths)
        self.assertIn("/rag/query/stream", paths)
        self.assertIn("/conversations", paths)


if __name__ == "__main__":
    unittest.main()
