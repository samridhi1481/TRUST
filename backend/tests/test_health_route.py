import unittest

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


class StubNeo4jConnection:
    def __init__(self, status: str):
        self.status = status
        self.closed = False

    async def health(self) -> dict[str, object]:
        return {
            "status": self.status,
            "configured": True,
            "database": "neo4j",
        }

    async def close(self) -> None:
        self.closed = True


def make_settings() -> Settings:
    return Settings(
        neo4j_uri="",
        neo4j_username="",
        neo4j_password="",
        neo4j_database="neo4j",
        cors_origins=("http://localhost:5173",),
        max_graph_depth=4,
    )


class HealthRouteTests(unittest.TestCase):
    def test_healthy_database_returns_success_and_closes_driver(self) -> None:
        database = StubNeo4jConnection("healthy")
        app = create_app(make_settings(), database)

        with TestClient(app) as client:
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertTrue(database.closed)

    def test_unavailable_database_returns_service_unavailable(self) -> None:
        app = create_app(make_settings(), StubNeo4jConnection("unhealthy"))

        with TestClient(app) as client:
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
