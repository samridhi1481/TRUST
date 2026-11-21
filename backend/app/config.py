import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()
MAX_ALLOWED_GRAPH_DEPTH = 6


@dataclass(frozen=True)
class Settings:
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str
    cors_origins: tuple[str, ...]
    max_graph_depth: int


def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    max_graph_depth = int(os.getenv("MAX_GRAPH_DEPTH", "4"))
    if not 1 <= max_graph_depth <= MAX_ALLOWED_GRAPH_DEPTH:
        raise ValueError(
            f"MAX_GRAPH_DEPTH must be between 1 and {MAX_ALLOWED_GRAPH_DEPTH}."
        )
    return Settings(
        neo4j_uri=os.getenv("NEO4J_URI", ""),
        neo4j_username=os.getenv("NEO4J_USERNAME", ""),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        max_graph_depth=max_graph_depth,
    )
