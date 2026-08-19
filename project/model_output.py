"""Strict helpers for small JSON objects returned by language models."""

from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    payload = (text or "").strip()
    if payload.startswith("```"):
        payload = payload.split("\n", 1)[1] if "\n" in payload else ""
        payload = payload.rsplit("```", 1)[0]
    start, end = payload.find("{"), payload.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model output does not contain a JSON object")
    value = json.loads(payload[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model output must be a JSON object")
    return value


def string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
