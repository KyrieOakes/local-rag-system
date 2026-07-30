"""FastAPI 应用入口与健康检查端点测试。"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
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

    @patch("app.api.health._check_openai_compatible_endpoint")
    @patch("app.api.health._check_qdrant")
    def test_readiness_returns_dependency_status(
        self,
        qdrant_check,
        endpoint_check,
    ):
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(qdrant_check.call_count, 1)
        self.assertEqual(endpoint_check.call_count, 2)

    @patch("app.api.health._check_openai_compatible_endpoint")
    @patch("app.api.health._check_qdrant", side_effect=RuntimeError("offline"))
    def test_readiness_returns_503_when_dependency_is_unavailable(
        self,
        _qdrant_check,
        _endpoint_check,
    ):
        response = self.client.get("/health/ready")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["dependencies"]["qdrant"]["status"], "unavailable")

    def test_openapi_exposes_core_routes(self):
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/health", paths)
        self.assertIn("/health/ready", paths)
        self.assertIn("/documents/upload", paths)
        self.assertIn("/rag/query", paths)
        self.assertIn("/rag/query/stream", paths)
        self.assertIn("/conversations", paths)

    def test_optional_api_key_protects_non_health_routes(self):
        with patch.object(settings, "app_api_key", "test-secret"):
            rejected = self.client.get("/documents")
            health_like_non_route = self.client.get("/health-private")
            unknown_health_child = self.client.get("/health/private")
            accepted_by_middleware = self.client.post(
                "/rag/query",
                headers={"X-API-Key": "test-secret"},
                json={},
            )
            health = self.client.get("/health")

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(health_like_non_route.status_code, 401)
        self.assertEqual(unknown_health_child.status_code, 401)
        # Missing question reaches Pydantic validation, proving middleware
        # accepted the supplied key without invoking external dependencies.
        self.assertEqual(accepted_by_middleware.status_code, 422)
        self.assertEqual(health.status_code, 200)

    def test_api_key_rejection_keeps_cors_headers(self):
        origin = "http://127.0.0.1:5173"
        with patch.object(settings, "app_api_key", "test-secret"):
            response = self.client.get(
                "/documents",
                headers={"Origin": origin},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            origin,
        )

    def test_responses_include_request_id(self):
        response = self.client.get(
            "/health",
            headers={"X-Request-ID": "request-test-1"},
        )

        self.assertEqual(response.headers["X-Request-ID"], "request-test-1")


if __name__ == "__main__":
    unittest.main()
