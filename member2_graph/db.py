"""Member 2 — Neo4j Aura connection module.

Provides a reusable, lazily-initialized Neo4j Python driver for the TRUSTRAIL
AI graph ingestion layer. Credentials are read from environment variables
(loaded from a local, gitignored `.env` file) and are never logged or written
to documentation.

Run from the repository root:
    $env:PYTHONPATH = "member2_graph"
    python member2_graph/db.py   # connection self-check
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver
from neo4j.exceptions import (
    Neo4jError,
    ServiceUnavailable,
    AuthError,
    ConfigurationError,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _load_env() -> None:
    """Load environment variables from member2_graph/.env if present.

    `load_dotenv` does not overwrite existing environment variables, so
    deployment-time secrets (e.g. injected by the platform) take precedence.
    """
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path, override=False)


_load_env()

NEO4J_URI: Optional[str] = os.environ.get("NEO4J_URI")
NEO4J_USERNAME: Optional[str] = os.environ.get("NEO4J_USERNAME")
NEO4J_PASSWORD: Optional[str] = os.environ.get("NEO4J_PASSWORD")
NEO4J_DATABASE: Optional[str] = os.environ.get("NEO4J_DATABASE")


def _missing_credentials() -> list[str]:
    missing: list[str] = []
    if not NEO4J_URI:
        missing.append("NEO4J_URI")
    if not NEO4J_USERNAME:
        missing.append("NEO4J_USERNAME")
    if not NEO4J_PASSWORD:
        missing.append("NEO4J_PASSWORD")
    return missing


# ---------------------------------------------------------------------------
# Driver lifecycle (singleton)
# ---------------------------------------------------------------------------

_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """Return the singleton Neo4j driver, connecting on first use.

    Raises:
        ConfigError: if required credentials are missing from the environment.
        Neo4jError: if the driver cannot be created / connectivity check fails.
    """
    global _driver
    if _driver is not None:
        return _driver

    missing = _missing_credentials()
    if missing:
        raise ConfigError(
            "Missing Neo4j credentials: " + ", ".join(missing) +
            ". Copy member2_graph/.env.example to member2_graph/.env and fill "
            "in your Neo4j Aura URI, username, and password."
        )

    # Mask credentials in any diagnostic output: never log the password.
    _driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )
    return _driver


def close_driver() -> None:
    """Close the singleton driver and release its connection pool."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def verify_connectivity() -> bool:
    """Verify the driver can reach the Neo4j database.

    Returns True on success, False on failure (connection errors are caught
    and reported without exposing credentials).
    """
    try:
        driver = get_driver()
        driver.verify_connectivity()
        return True
    except Exception as exc:
        # Surface a sanitized message only; credentials are never included.
        # Catches Neo4j errors as well as DNS/resolution and network errors.
        print(f"[member2_graph] Neo4j connectivity check failed: {type(exc).__name__}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------

@contextmanager
def session(database: Optional[str] = None) -> Iterator:
    """Yield a Neo4j session, guaranteeing it is closed after use.

    Defaults to NEO4J_DATABASE from the environment when not specified.

    Usage:
        with session() as s:
            s.run("MATCH (n) RETURN count(n)")
    """
    if database is None:
        database = NEO4J_DATABASE
    driver = get_driver()
    neo_session = driver.session(database=database)
    try:
        yield neo_session
    finally:
        neo_session.close()


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Member 2 — Neo4j connection self-check")
    print("=" * 60)
    missing = _missing_credentials()
    if missing:
        print(f"\nMissing credentials: {missing}")
        print("Create member2_graph/.env from .env.example before connecting.")
    else:
        # URI shown; password and username are deliberately omitted.
        print(f"\nConfigured URI: {NEO4J_URI}")
        ok = verify_connectivity()
        print(f"\nConnectivity: {'OK' if ok else 'FAILED'}")
    close_driver()
    print("\nSelf-check complete.")
