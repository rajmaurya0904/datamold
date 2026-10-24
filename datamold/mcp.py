"""A minimal MCP server over stdio (newline-delimited JSON-RPC 2.0).

Implements ``initialize``, ``ping``, ``tools/list`` and ``tools/call`` with four tools:
``convert_csv``, ``validate_mapping``, ``infer_mapping`` and ``list_functions``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import IO, Any

from . import __version__, api
from .dsl import MAPPING_HELP
from .errors import DatamoldError

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_CSV = {"type": "string", "description": "CSV text including the header row"}
_MAPPING = {"type": "string", "description": "Mapping DSL text. " + MAPPING_HELP}
_DELIM = {"type": "string", "description": "Single-character delimiter; sniffed if omitted"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "convert_csv",
        "description": "Convert CSV text to a JSON array of records using a mapping.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "csv": _CSV,
                "mapping": _MAPPING,
                "on_error": {"type": "string", "enum": ["fail", "skip", "null"]},
                "delimiter": _DELIM,
                "limit": {"type": "integer", "minimum": 0},
            },
            "required": ["csv", "mapping"],
        },
    },
    {
        "name": "validate_mapping",
        "description": "Parse a mapping and, if csv is given, check its columns exist.",
        "inputSchema": {
            "type": "object",
            "properties": {"mapping": _MAPPING, "csv": _CSV, "delimiter": _DELIM},
            "required": ["mapping"],
        },
    },
    {
        "name": "infer_mapping",
        "description": "Draft a starting mapping from a CSV sample, with guessed types.",
        "inputSchema": {
            "type": "object",
            "properties": {"csv": _CSV, "delimiter": _DELIM},
            "required": ["csv"],
        },
    },
    {
        "name": "list_functions",
        "description": "List the pipe functions usable in a mapping.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_DISPATCH: dict[str, Callable[[dict[str, Any]], Any]] = {
    "convert_csv": api.convert,
    "validate_mapping": api.validate,
    "infer_mapping": api.infer,
    "list_functions": lambda _args: api.functions(),
}


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _call_tool(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict) or "name" not in params:
        raise ValueError("tools/call needs a 'name'")
    name = params["name"]
    if name not in _DISPATCH:
        raise ValueError(f"unknown tool {name!r}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        raise ValueError("'arguments' must be an object")
    try:
        data = _DISPATCH[name](args)
    except DatamoldError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}], "isError": False}


def handle(message: Any) -> dict[str, Any] | None:
    """Handle one decoded JSON-RPC message; returns the response, or None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "invalid JSON-RPC request")
    method = message.get("method")
    req_id = message.get("id")
    is_notification = "id" not in message
    if not isinstance(method, str):
        return None if is_notification else _error(req_id, -32600, "missing method")
    if is_notification:
        return None  # notifications/initialized, notifications/cancelled, ...
    params = message.get("params")
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        version = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "datamold", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            result = _call_tool(params)
        except ValueError as exc:
            return _error(req_id, -32602, str(exc))
        except Exception as exc:  # a bug in a tool must not kill the server
            return _error(req_id, -32603, f"internal error: {type(exc).__name__}: {exc}")
    else:
        return _error(req_id, -32601, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
    """Run the server loop until stdin closes."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = _error(None, -32700, "parse error")
        else:
            if isinstance(message, list):
                replies = [r for r in (handle(m) for m in message) if r is not None]
                response = replies or None  # type: ignore[assignment]
            else:
                response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
