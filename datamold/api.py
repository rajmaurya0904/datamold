"""Plain-dict entry points shared by the serverless handler and the MCP server."""

from __future__ import annotations

import inspect
from typing import Any

from .dsl import parse_mapping
from .engine import ON_ERROR_MODES, infer_mapping, read_csv, transform
from .errors import DatamoldError
from .funcs import FUNCTIONS


def _require_text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DatamoldError(f"'{key}' is required and must be a non-empty string")
    return value


def _delimiter(args: dict[str, Any]) -> str | None:
    delim = args.get("delimiter")
    if delim is None or delim == "":
        return None
    if delim == "\\t":
        delim = "\t"
    if not isinstance(delim, str) or len(delim) != 1:
        raise DatamoldError("'delimiter' must be a single character")
    return delim


def convert(args: dict[str, Any]) -> dict[str, Any]:
    """Convert CSV text to records. Keys: csv, mapping, on_error, delimiter, limit."""
    csv_text = _require_text(args, "csv")
    mapping_text = _require_text(args, "mapping")
    on_error = args.get("on_error", "fail")
    if on_error not in ON_ERROR_MODES:
        raise DatamoldError(f"'on_error' must be one of {', '.join(ON_ERROR_MODES)}")
    result = transform(csv_text, mapping_text, on_error=on_error, delimiter=_delimiter(args))
    records = result.records
    limit = args.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise DatamoldError("'limit' must be a non-negative integer")
        records = records[:limit]
    return {"records": records, "stats": result.summary(), "errors": result.errors}


def validate(args: dict[str, Any]) -> dict[str, Any]:
    """Check a mapping; with ``csv`` also check that its columns exist."""
    mapping = parse_mapping(_require_text(args, "mapping"))
    out: dict[str, Any] = {
        "ok": True,
        "rules": len(mapping.rules),
        "filters": len(mapping.filters),
        "columns_used": sorted(mapping.columns_used()),
    }
    if args.get("csv"):
        from .engine import check_columns

        header, _ = read_csv(args["csv"], _delimiter(args))
        check_columns(mapping, header)
        out["csv_columns"] = header
    return out


def infer(args: dict[str, Any]) -> dict[str, Any]:
    """Draft a mapping from a CSV sample."""
    return {"mapping": infer_mapping(_require_text(args, "csv"), _delimiter(args))}


def functions() -> dict[str, str]:
    """Describe the available pipe functions."""
    out = {}
    for name, fn in sorted(FUNCTIONS.items()):
        params = list(inspect.signature(fn).parameters.values())[1:]
        out[name] = f"{name}({', '.join(p.name for p in params)})"
    return out
