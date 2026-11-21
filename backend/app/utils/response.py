from typing import Any


def success(data: Any, message: str = "Success") -> dict[str, Any]:
    return {"success": True, "message": message, "data": data}
