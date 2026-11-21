from __future__ import annotations

import asyncio
import logging
from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError

from ..config import Settings

logger = logging.getLogger(__name__)


class Neo4jConnectionError(RuntimeError):
    pass


class Neo4jConnection:
    def __init__(self, settings: Settings):
        self.settings = settings
        configured_values = (
            settings.neo4j_uri,
            settings.neo4j_username,
            settings.neo4j_password,
        )
        if any(configured_values) and not all(configured_values):
            raise Neo4jConnectionError(
                "Neo4j configuration is incomplete. Set NEO4J_URI, "
                "NEO4J_USERNAME, and NEO4J_PASSWORD."
            )

        self.driver: Driver | None = None
        if all(configured_values):
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
                max_connection_lifetime=1800,
                connection_timeout=10,
            )

    async def connect(self) -> None:
        if self.driver is None:
            raise Neo4jConnectionError(
                "Neo4j is not configured. Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD."
            )
        try:
            await asyncio.to_thread(self.driver.verify_connectivity)
        except Neo4jError as exc:
            logger.error("Neo4j connectivity check failed: %s", exc.code)
            raise Neo4jConnectionError("Neo4j connectivity check failed.") from exc

    async def close(self) -> None:
        if self.driver is not None:
            await asyncio.to_thread(self.driver.close)

    async def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.driver is None:
            raise Neo4jConnectionError("Neo4j is not configured.")
        try:
            def run():
                with self.driver.session(database=self.settings.neo4j_database) as session:
                    return [dict(record) for record in session.execute_read(
                        lambda tx: tx.run(query, parameters or {}).data()
                    )]
            return await asyncio.to_thread(run)
        except Neo4jError as exc:
            logger.error("Neo4j read failed: %s", exc.code)
            raise Neo4jConnectionError("Database query failed.") from exc

    async def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.driver is None:
            raise Neo4jConnectionError("Neo4j is not configured.")
        try:
            def run():
                with self.driver.session(database=self.settings.neo4j_database) as session:
                    return [dict(record) for record in session.execute_write(
                        lambda tx: tx.run(query, parameters or {}).data()
                    )]
            return await asyncio.to_thread(run)
        except Neo4jError as exc:
            logger.error("Neo4j write failed: %s", exc.code)
            raise Neo4jConnectionError("Database transaction failed.") from exc

    async def health(self) -> dict[str, Any]:
        if self.driver is None:
            return {"status": "degraded", "configured": False, "database": self.settings.neo4j_database}
        try:
            await self.connect()
            result = await self.execute_read("RETURN 1 AS ok")
            connected = bool(result and result[0].get("ok") == 1)
            return {
                "status": "healthy" if connected else "unhealthy",
                "configured": True,
                "database": self.settings.neo4j_database,
                "connectivity": connected,
            }
        except Neo4jConnectionError:
            return {"status": "unhealthy", "configured": True, "database": self.settings.neo4j_database}
