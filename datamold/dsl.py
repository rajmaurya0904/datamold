"""Parser for the datamold mapping DSL.

Each non-blank, non-comment line is either a directive or a rule::

    @filter status == active
    id: int          <- user_id
    name             <- first, last | join(" ") | title
    address.city     <- City | trim
    tags[]           <- tags | split(";")
    source           <- "csv"

A rule is ``target[: type] <- source[, source ...] [| func(args) ...]``. Sources are column
names, quoted literals, or ``$row`` (the 1-based data row number).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .errors import MappingSyntaxError
from .funcs import FUNCTIONS, TYPE_NAMES

_TARGET_RE = re.compile(r"^[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*)*(\[\])?$")
_FILTER_OPS = ("==", "!=", ">=", "<=", ">", "<", "contains", "empty", "notempty")
_FILTER_RE = re.compile(
    r'(?P<col>"[^"]+"|\S+)\s+(?P<op>==|!=|>=|<=|>|<|contains|notempty|empty)(?:\s+(?P<val>.*))?'
)
_CALL_RE = re.compile(r"([A-Za-z_]\w*)\s*(?:\((.*)\))?", re.S)


@dataclass(frozen=True)
class Source:
    kind: str  # "column" | "literal" | "row"
    value: str = ""


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    target: tuple[str, ...]
    as_list: bool
    sources: tuple[Source, ...]
    pipeline: tuple[Call, ...]
    line: int


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: str
    line: int


@dataclass
class Mapping:
    rules: list[Rule] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    passthrough: bool = False

    def columns_used(self) -> set[str]:
        used = {s.value for r in self.rules for s in r.sources if s.kind == "column"}
        used.update(f.column for f in self.filters)
        return used


def _split_top(text: str, sep: str, line: int) -> list[str]:
    """Split on ``sep`` outside of double quotes and parentheses."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_quote = False
        elif ch == '"':
            in_quote = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise MappingSyntaxError("unbalanced ')'", line)
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if in_quote:
        raise MappingSyntaxError("unterminated string literal", line)
    if depth:
        raise MappingSyntaxError("unbalanced '('", line)
    parts.append("".join(buf))
    return parts


def _unquote(token: str, line: int) -> str:
    """Decode every double-quoted segment in ``token`` and keep the rest verbatim."""
    out: list[str] = []
    i = 0
    while i < len(token):
        if token[i] == '"':
            j = i + 1
            while j < len(token) and token[j] != '"':
                j += 2 if token[j] == "\\" else 1
            if j >= len(token):
                raise MappingSyntaxError("unterminated string literal", line)
            try:
                out.append(json.loads(token[i : j + 1]))
            except json.JSONDecodeError:
                raise MappingSyntaxError(f"bad string literal {token[i : j + 1]}", line) from None
            i = j + 1
        else:
            out.append(token[i])
            i += 1
    return "".join(out)


def _parse_source(text: str, line: int) -> Source:
    text = text.strip()
    if not text:
        raise MappingSyntaxError("empty source", line)
    if text == "$row":
        return Source("row")
    if text.startswith('"'):
        if not (text.endswith('"') and len(text) >= 2):
            raise MappingSyntaxError(f"bad literal {text}", line)
        return Source("literal", _unquote(text, line))
    return Source("column", text)


def _parse_call(text: str, line: int) -> Call:
    text = text.strip()
    match = _CALL_RE.fullmatch(text)
    if not match:
        raise MappingSyntaxError(f"cannot parse function call {text!r}", line)
    name, raw_args = match.group(1), match.group(2)
    if name not in FUNCTIONS:
        known = ", ".join(sorted(FUNCTIONS))
        raise MappingSyntaxError(f"unknown function {name!r} (known: {known})", line)
    args: tuple[str, ...] = ()
    if raw_args is not None and raw_args.strip():
        args = tuple(_unquote(a.strip(), line) for a in _split_top(raw_args, ",", line))
    return Call(name, args)


def _parse_filter(rest: str, line: int) -> Filter:
    match = _FILTER_RE.fullmatch(rest.strip())
    if not match:
        raise MappingSyntaxError(
            "@filter needs: <column> <op> <value> with op one of " + ", ".join(_FILTER_OPS), line
        )
    op, val = match.group("op"), match.group("val")
    if op in ("empty", "notempty"):
        val = ""
    elif val is None:
        raise MappingSyntaxError(f"@filter operator {op!r} needs a value", line)
    return Filter(_unquote(match.group("col"), line), op, _unquote(val.strip(), line), line)


def parse_mapping(text: str) -> Mapping:
    """Parse mapping text into a :class:`Mapping`; raises MappingSyntaxError on bad input."""
    mapping = Mapping()
    seen_leaf: dict[tuple[str, ...], int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            word, _, rest = stripped.partition(" ")
            if word == "@filter":
                mapping.filters.append(_parse_filter(rest, number))
            elif word == "@passthrough":
                mapping.passthrough = True
            else:
                raise MappingSyntaxError(f"unknown directive {word}", number)
            continue
        if "<-" not in stripped:
            raise MappingSyntaxError("expected '<-' between target and source", number)
        left, _, right = stripped.partition("<-")
        left = left.strip()
        declared_type = None
        if ":" in left:
            left, _, declared_type = (p.strip() for p in left.partition(":"))
            if declared_type not in TYPE_NAMES:
                raise MappingSyntaxError(
                    f"unknown type {declared_type!r} (use one of {', '.join(sorted(TYPE_NAMES))})",
                    number,
                )
        if not _TARGET_RE.match(left):
            raise MappingSyntaxError(f"invalid target name {left!r}", number)
        as_list = left.endswith("[]")
        path = tuple(left.removesuffix("[]").split("."))
        for depth in range(1, len(path)):
            if path[:depth] in seen_leaf:
                raise MappingSyntaxError(
                    f"{'.'.join(path[:depth])!r} is already a value (line "
                    f"{seen_leaf[path[:depth]]}), cannot nest under it",
                    number,
                )
        if path in seen_leaf:
            raise MappingSyntaxError(
                f"target {'.'.join(path)!r} already defined on line {seen_leaf[path]}", number
            )
        for other in seen_leaf:
            if other[: len(path)] == path:
                raise MappingSyntaxError(f"{'.'.join(path)!r} is also used as an object", number)
        seen_leaf[path] = number
        segments = _split_top(right, "|", number)
        sources = tuple(_parse_source(s, number) for s in _split_top(segments[0], ",", number))
        pipeline = [_parse_call(s, number) for s in segments[1:]]
        if declared_type:
            pipeline.append(Call(declared_type))
        mapping.rules.append(Rule(path, as_list, sources, tuple(pipeline), number))
    if not mapping.rules and not mapping.passthrough:
        raise MappingSyntaxError("mapping has no rules")
    return mapping


MAPPING_HELP = (
    "One rule per line: 'target[: type] <- source[, source] [| func(args) ...]'. "
    "Sources are column names, \"quoted literals\" or $row. Targets may nest (a.b) or end in [] "
    "for a list. Directives: '@filter <col> <op> <value>' and '@passthrough'. "
    "Types: int, float, bool, str. Lines starting with # are comments."
)
