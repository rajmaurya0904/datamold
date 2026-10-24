"""Command line interface: ``datamold convert | check | infer | functions | serve``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, api
from .dsl import parse_mapping
from .engine import ON_ERROR_MODES, check_columns, infer_mapping, read_csv, transform
from .errors import DatamoldError, MappingSyntaxError, RowError

EXIT_OK = 0
EXIT_DATA = 1  # input data could not be converted
EXIT_USAGE = 2  # bad mapping, unreadable file, bad arguments


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise DatamoldError(f"file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise DatamoldError(f"cannot read {path}: {exc}") from None


def _delimiter(value: str | None) -> str | None:
    if value is None:
        return None
    value = "\t" if value in ("\\t", "tab") else value
    if len(value) != 1:
        raise DatamoldError("--delimiter must be a single character (or 'tab')")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datamold", description="Transform CSV to JSON with a small mapping DSL."
    )
    parser.add_argument("--version", action="version", version=f"datamold {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    conv = sub.add_parser("convert", help="convert a CSV file to JSON using a mapping")
    conv.add_argument("csv", help="CSV file, or - for stdin")
    conv.add_argument("-m", "--mapping", required=True, help="mapping file")
    conv.add_argument("-o", "--output", help="write here instead of stdout")
    conv.add_argument("--ndjson", action="store_true", help="one JSON object per line")
    conv.add_argument("--indent", type=int, default=2, help="JSON indent (0 = compact)")
    conv.add_argument("--on-error", choices=ON_ERROR_MODES, default="fail")
    conv.add_argument("--delimiter", help="CSV delimiter (default: sniffed)")
    conv.add_argument(
        "--columns", help="comma-separated column names for a CSV that has no header row"
    )
    conv.add_argument("--limit", type=int, help="only emit the first N records")

    chk = sub.add_parser("check", help="validate a mapping, optionally against a CSV header")
    chk.add_argument("mapping", help="mapping file")
    chk.add_argument("--csv", help="CSV file whose header the mapping must match")
    chk.add_argument("--delimiter")

    inf = sub.add_parser("infer", help="draft a mapping from a CSV file")
    inf.add_argument("csv", help="CSV file, or - for stdin")
    inf.add_argument("--delimiter")

    sub.add_parser("functions", help="list pipe functions")
    sub.add_parser("serve", help="run as an MCP server on stdio")
    return parser


def _cmd_convert(args: argparse.Namespace) -> int:
    mapping = parse_mapping(_read(args.mapping))
    result = transform(
        _read(args.csv),
        mapping,
        on_error=args.on_error,
        delimiter=_delimiter(args.delimiter),
        columns=[c.strip() for c in args.columns.split(",")] if args.columns else None,
    )
    if args.limit is not None:
        if args.limit < 0:
            raise DatamoldError("--limit must be zero or more")
        result.records = result.records[: args.limit]
    if args.ndjson:
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in result.records)
    else:
        indent = args.indent if args.indent > 0 else None
        text = json.dumps(result.records, indent=indent, ensure_ascii=False) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(text, encoding="utf-8")
        except OSError as exc:
            raise DatamoldError(f"cannot write {args.output}: {exc}") from None
    else:
        sys.stdout.write(text)
    for message in result.errors:
        print(f"datamold: warning: {message}", file=sys.stderr)
    print(
        f"datamold: {len(result.records)} records from {result.rows_read} rows"
        + (f", {result.rows_filtered} filtered" if result.rows_filtered else "")
        + (f", {len(result.errors)} errors" if result.errors else ""),
        file=sys.stderr,
    )
    return EXIT_OK


def _cmd_check(args: argparse.Namespace) -> int:
    mapping = parse_mapping(_read(args.mapping))
    msg = f"ok: {len(mapping.rules)} rules, {len(mapping.filters)} filters"
    if args.csv:
        header, _ = read_csv(_read(args.csv), _delimiter(args.delimiter))
        check_columns(mapping, header)
        msg += f"; all {len(mapping.columns_used())} referenced columns exist in the CSV"
    print(msg)
    return EXIT_OK


def _cmd_infer(args: argparse.Namespace) -> int:
    sys.stdout.write(infer_mapping(_read(args.csv), _delimiter(args.delimiter)))
    return EXIT_OK


def _cmd_functions(_args: argparse.Namespace) -> int:
    for signature in api.functions().values():
        print(signature)
    return EXIT_OK


def _cmd_serve(_args: argparse.Namespace) -> int:
    from .mcp import serve

    serve()
    return EXIT_OK


COMMANDS = {
    "convert": _cmd_convert,
    "check": _cmd_check,
    "infer": _cmd_infer,
    "functions": _cmd_functions,
    "serve": _cmd_serve,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except RowError as exc:
        print(f"datamold: error: {exc}", file=sys.stderr)
        print("datamold: use --on-error skip or null to keep going", file=sys.stderr)
        return EXIT_DATA
    except MappingSyntaxError as exc:
        print(f"datamold: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except DatamoldError as exc:
        print(f"datamold: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
