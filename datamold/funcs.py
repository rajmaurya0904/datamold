"""Pipe functions available in the mapping DSL.

Every function takes the current value plus its literal arguments and returns the
new value. ``None`` stands for an empty CSV cell and passes through most functions.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

_TRUE = {"true", "yes", "y", "1", "t", "on"}
_FALSE = {"false", "no", "n", "0", "f", "off"}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _elementwise(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Make a string function apply to each item when given a list (multi-source rules)."""

    @functools.wraps(fn)
    def wrapper(value: Any, *args: str) -> Any:
        if isinstance(value, list):
            return [fn(v, *args) for v in value]
        return fn(value, *args)

    return wrapper


@_elementwise
def f_trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


@_elementwise
def f_lower(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


@_elementwise
def f_upper(value: Any) -> Any:
    return value.upper() if isinstance(value, str) else value


@_elementwise
def f_title(value: Any) -> Any:
    return value.title() if isinstance(value, str) else value


def f_int(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = _text(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        raise ValueError(f"cannot convert {value!r} to int") from None
    if number != int(number):
        raise ValueError(f"cannot convert {value!r} to int without losing the fraction")
    return int(number)


def f_float(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return float(_text(value).strip().replace(",", ""))
    except ValueError:
        raise ValueError(f"cannot convert {value!r} to float") from None


def f_bool(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = _text(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"cannot convert {value!r} to bool")


def f_str(value: Any) -> Any:
    return None if value is None else _text(value)


def f_split(value: Any, sep: str = ",") -> Any:
    if value is None or value == "":
        return []
    return [part.strip() for part in _text(value).split(sep)]


def f_join(value: Any, sep: str = " ") -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [_text(v) for v in value if v not in (None, "")]
        return sep.join(parts) if parts else None
    return value


def f_default(value: Any, fallback: str = "") -> Any:
    return fallback if value is None or value == "" else value


@_elementwise
def f_replace(value: Any, old: str, new: str = "") -> Any:
    return value.replace(old, new) if isinstance(value, str) else value


@_elementwise
def f_regex(value: Any, pattern: str, repl: str = "") -> Any:
    if not isinstance(value, str):
        return value
    try:
        return re.sub(pattern, repl, value)
    except re.error as exc:
        raise ValueError(f"bad regex {pattern!r}: {exc}") from None


def f_map(value: Any, *pairs: str) -> Any:
    """Look the value up in ``key=result`` pairs; unknown values raise unless ``*=`` is given."""
    table: dict[str, str] = {}
    for pair in pairs:
        key, sep, result = pair.partition("=")
        if not sep:
            raise ValueError(f"map() argument {pair!r} must look like key=value")
        table[key] = result
    key = "" if value is None else _text(value)
    if key in table:
        return _coerce_literal(table[key])
    if "*" in table:
        return _coerce_literal(table["*"])
    raise ValueError(f"no map() entry for {value!r}")


def _coerce_literal(text: str) -> Any:
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def f_date(value: Any, in_fmt: str = "%Y-%m-%d", out_fmt: str = "%Y-%m-%d") -> Any:
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(_text(value).strip(), in_fmt).strftime(out_fmt)
    except ValueError:
        raise ValueError(f"{value!r} does not match date format {in_fmt!r}") from None


def f_round(value: Any, digits: str = "0") -> Any:
    if value is None:
        return None
    return round(float(value), int(digits))


def f_required(value: Any) -> Any:
    if value is None or value == "":
        raise ValueError("value is required but empty")
    return value


def f_nullif(value: Any, marker: str = "") -> Any:
    return None if value == marker else value


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "trim": f_trim,
    "lower": f_lower,
    "upper": f_upper,
    "title": f_title,
    "int": f_int,
    "float": f_float,
    "bool": f_bool,
    "str": f_str,
    "split": f_split,
    "join": f_join,
    "default": f_default,
    "replace": f_replace,
    "regex": f_regex,
    "map": f_map,
    "date": f_date,
    "round": f_round,
    "required": f_required,
    "nullif": f_nullif,
}

TYPE_NAMES = {"int", "float", "bool", "str"}
