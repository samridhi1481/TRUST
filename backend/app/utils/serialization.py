from collections.abc import Mapping
from typing import Any


def serialize_neo4j_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: serialize_neo4j_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_neo4j_value(item) for item in value]
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
