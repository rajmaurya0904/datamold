"""Apply a parsed mapping to CSV data."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from .dsl import Filter, Mapping, Rule, Source, parse_mapping
from .errors import DatamoldError, RowError
from .funcs import FUNCTIONS

ON_ERROR_MODES = ("fail", "skip", "null")


@dataclass
class Result:
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rows_read: int = 0
    rows_filtered: int = 0

    def summary(self) -> dict[str, int]:
        return {
            "rows_read": self.rows_read,
            "rows_filtered": self.rows_filtered,
            "records": len(self.records),
            "errors": len(self.errors),
        }


def read_csv(
    text: str, delimiter: str | None = None, columns: list[str] | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV text into (header, rows). The delimiter is sniffed when not given."""
    if text.startswith("﻿"):
        text = text[1:]
    if not text.strip():
        raise DatamoldError("CSV input is empty")
    if delimiter is None:
        delimiter = _sniff(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    if columns is not None:
        header = list(columns)
    else:
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            raise DatamoldError("CSV input has no header row") from None
    if len(set(header)) != len(header):
        dupes = sorted({h for h in header if header.count(h) > 1})
        raise DatamoldError(f"CSV header has duplicate column names: {', '.join(dupes)}")
    rows: list[dict[str, str]] = []
    for number, cells in enumerate(reader, start=1):
        if not cells or all(c.strip() == "" for c in cells):
            continue
        if len(cells) > len(header):
            raise RowError(f"has {len(cells)} cells but the header has {len(header)}", number)
        cells = cells + [""] * (len(header) - len(cells))
        row = dict(zip(header, cells, strict=True))
        row["$row"] = str(number)
        rows.append(row)
    return header, rows


def _sniff(text: str) -> str:
    first = text.splitlines()[0] if text.splitlines() else ""
    counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def _compare(cell: str, flt: Filter) -> bool:
    op, want = flt.op, flt.value
    if op == "empty":
        return cell.strip() == ""
    if op == "notempty":
        return cell.strip() != ""
    if op == "contains":
        return want in cell
    if op in ("==", "!="):
        equal = cell.strip() == want
        return equal if op == "==" else not equal
    try:
        left, right = float(cell), float(want)
    except ValueError:
        left, right = cell, want  # type: ignore[assignment]
    return {
        ">": left > right,
        "<": left < right,
        ">=": left >= right,
        "<=": left <= right,
    }[op]


def _passes(row: dict[str, str], filters: list[Filter]) -> bool:
    return all(_compare(row[f.column], f) for f in filters)


def _source_value(src: Source, row: dict[str, str]) -> Any:
    if src.kind == "literal":
        return src.value
    if src.kind == "row":
        return int(row["$row"])
    cell = row[src.value]
    return None if cell.strip() == "" else cell


def _apply_rule(rule: Rule, row: dict[str, str]) -> Any:
    values = [_source_value(s, row) for s in rule.sources]
    value: Any = values[0] if len(values) == 1 else values
    for call in rule.pipeline:
        try:
            value = FUNCTIONS[call.name](value, *call.args)
        except ValueError as exc:
            raise ValueError(f"{'.'.join(rule.target)} (mapping line {rule.line}): {exc}") from None
        except TypeError as exc:
            raise ValueError(
                f"{'.'.join(rule.target)} (mapping line {rule.line}): "
                f"bad arguments for {call.name}(): {exc}"
            ) from None
    if rule.as_list and not isinstance(value, list):
        value = [] if value is None else [value]
    return value


def _assign(record: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = record
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


def check_columns(mapping: Mapping, header: list[str]) -> None:
    missing = sorted(mapping.columns_used() - set(header))
    if missing:
        raise DatamoldError(
            "mapping refers to columns not in the CSV: "
            + ", ".join(missing)
            + f" (CSV columns: {', '.join(header)})"
        )


def transform(
    csv_text: str,
    mapping: Mapping | str,
    *,
    on_error: str = "fail",
    delimiter: str | None = None,
    columns: list[str] | None = None,
) -> Result:
    """Convert ``csv_text`` using ``mapping``.

    ``on_error`` decides what happens to a row whose conversion fails: ``fail`` raises
    :class:`RowError`, ``skip`` drops the row, ``null`` keeps the row with the bad field null.
    Every problem is also recorded in ``Result.errors``.
    """
    if on_error not in ON_ERROR_MODES:
        raise DatamoldError(f"on_error must be one of {', '.join(ON_ERROR_MODES)}")
    if isinstance(mapping, str):
        mapping = parse_mapping(mapping)
    header, rows = read_csv(csv_text, delimiter, columns)
    check_columns(mapping, header)
    result = Result(rows_read=len(rows))
    seen: set[str] = set()
    for row in rows:
        number = int(row["$row"])
        if not _passes(row, mapping.filters):
            result.rows_filtered += 1
            continue
        if mapping.distinct:
            key = row[mapping.distinct].strip()
            if key in seen:
                result.rows_filtered += 1
                continue
            seen.add(key)
        record: dict[str, Any] = {}
        if mapping.passthrough:
            mapped = {s.value for r in mapping.rules for s in r.sources if s.kind == "column"}
            record.update({k: v for k, v in row.items() if k != "$row" and k not in mapped})
        failed = False
        for rule in mapping.rules:
            try:
                _assign(record, rule.target, _apply_rule(rule, row))
            except ValueError as exc:
                message = f"row {number}: {exc}"
                result.errors.append(message)
                if on_error == "fail":
                    raise RowError(str(exc), number) from None
                if on_error == "skip":
                    failed = True
                    break
                _assign(record, rule.target, None)
        if not failed:
            result.records.append(record)
    return result


def infer_mapping(csv_text: str, delimiter: str | None = None) -> str:
    """Draft a mapping with one rule per column and a guessed type."""
    header, rows = read_csv(csv_text, delimiter)
    lines = ["# draft mapping generated from the CSV header; edit as needed"]
    for name in header:
        cells = [r[name].strip() for r in rows if r[name].strip() != ""]
        kind = _guess_type(cells)
        target = _target_name(name)
        suffix = f": {kind}" if kind != "str" else ""
        trim = " | trim" if kind == "str" else ""
        lines.append(f"{target}{suffix} <- {name}{trim}")
    return "\n".join(lines) + "\n"


def _target_name(column: str) -> str:
    name = re.sub(r"\W+", "_", column.strip()).strip("_").lower() or "field"
    return "f_" + name if name[0].isdigit() else name


def _guess_type(cells: list[str]) -> str:
    if not cells:
        return "str"
    if all(c.lower() in ("true", "false") for c in cells):
        return "bool"
    try:
        for c in cells:
            int(c)
        return "int"
    except ValueError:
        pass
    try:
        for c in cells:
            float(c)
        return "float"
    except ValueError:
        return "str"


def validate_mapping(text: str, header: list[str] | None = None) -> Mapping:
    """Parse a mapping and optionally check its columns exist in ``header``."""
    mapping = parse_mapping(text)
    if header is not None:
        check_columns(mapping, header)
    return mapping
