import unittest
from unittest.mock import AsyncMock, patch

from backend.app.config import Settings
from backend.app.database.neo4j_connection import Neo4jConnection, Neo4jConnectionError


def make_settings(
    uri: str = "",
    username: str = "",
    password: str = "",
) -> Settings:
    return Settings(
        neo4j_uri=uri,
        neo4j_username=username,
        neo4j_password=password,
        neo4j_database="neo4j",
        cors_origins=(),
        max_graph_depth=4,
    )


class Neo4jConnectionTests(unittest.IsolatedAsyncioTestCase):
    def test_unconfigured_database_is_reported_without_driver(self) -> None:
        connection = Neo4jConnection(make_settings())

        self.assertIsNone(connection.driver)

    def test_partial_database_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(Neo4jConnectionError, "configuration is incomplete"):
            Neo4jConnection(make_settings(uri="neo4j+s://example.databases.neo4j.io"))


    async def test_health_reports_successful_database_check(self) -> None:
        with patch("backend.app.database.neo4j_connection.GraphDatabase.driver"):
            connection = Neo4jConnection(make_settings("neo4j+s://example.test", "neo4j", "secret"))

        connection.connect = AsyncMock()
        connection.execute_read = AsyncMock(return_value=[{"ok": 1}])

        self.assertEqual(await connection.health(), {
            "status": "healthy",
            "configured": True,
            "database": "neo4j",
            "connectivity": True,
        })


    async def test_health_reports_database_failure_without_exposing_credentials(self) -> None:
        with patch("backend.app.database.neo4j_connection.GraphDatabase.driver"):
            connection = Neo4jConnection(make_settings("neo4j+s://example.test", "neo4j", "secret"))

        connection.connect = AsyncMock(side_effect=Neo4jConnectionError("connection failed"))

        self.assertEqual(await connection.health(), {
            "status": "unhealthy",
            "configured": True,
            "database": "neo4j",
        })
