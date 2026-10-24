# datamold

**Turns CSV into the JSON you actually want, using a few lines of mapping instead of a throwaway script. Runs as a CLI, a Lambda-style handler, or an MCP server.**

Every CSV-to-JSON job starts the same way: columns are named wrong, numbers are strings, dates are in the wrong format, three columns should be one nested object. You write a 40-line script, use it once, and lose it. `datamold` keeps that logic in a small mapping file you can read, check and rerun.

```console
$ cat examples/people.dm
# people mapping
@filter status == active
id: int            <- user_id
name               <- first_name, last_name | trim | join(" ") | title
email              <- Email | lower
address.city       <- city
tags[]             <- tags | split(";")
joined             <- signup | date("%Y-%m-%d", "%d %b %Y")
spend: float       <- spend | default(0)

$ datamold convert examples/people.csv -m examples/people.dm --ndjson
datamold: 2 records from 3 rows, 1 filtered
{"id": 1, "name": "Ada Lovelace", "email": "ada@example.com", "address": {"city": "London"}, "tags": ["math", "code"], "joined": "10 Dec 1815", "spend": 1200.5}
{"id": 3, "name": "Grace Hopper", "email": "grace@example.com", "address": {"city": "NYC"}, "tags": [], "joined": "09 Dec 1906", "spend": 99.0}
```

Bad input fails loudly instead of silently producing garbage (here a mapping that declares `id: int <- first_name`):

```console
$ datamold convert examples/people.csv -m bad.dm
datamold: error: row 1: id (mapping line 1): cannot convert ' ada ' to int
datamold: use --on-error skip or null to keep going
```

## Install

Not on PyPI yet, so install from a clone (Python 3.11+, no runtime dependencies):

```bash
pip install -e .
```

## Usage

```bash
datamold convert data.csv -m rules.dm -o out.json   # CSV + mapping -> JSON (--ndjson, --limit, --on-error skip|null)
datamold infer data.csv > rules.dm                   # draft a mapping with guessed types
datamold check rules.dm --csv data.csv               # validate the mapping and its column names
datamold serve                                       # MCP server on stdio
```

`convert` reads stdin when the CSV argument is `-`. Exit codes: `0` ok, `1` a row could not be converted, `2` bad mapping, missing column or unreadable file.

**Mapping language.** One rule per line: `target[: type] <- source[, source] [| func(args) ...]`.

- Sources are column names, `"quoted literals"`, or `$row` (1-based data row number). Several sources become a list that `join` can combine.
- Targets nest with dots (`address.city`) and end in `[]` to force a list.
- Types are `int`, `float`, `bool`, `str`. Empty cells become `null`.
- `@filter <column> <op> <value>` drops rows (`==`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `empty`, `notempty`). `@passthrough` keeps unmapped columns as-is.
- `datamold functions` lists the pipe functions: `trim lower upper title split join default replace regex map date round required nullif` plus the type converters.

**MCP server.** Register `datamold serve` as a stdio server in your MCP client. It exposes `convert_csv`, `validate_mapping`, `infer_mapping` and `list_functions`.

**Serverless.** `datamold.handler.handler(event, context)` accepts either `{"csv": ..., "mapping": ...}` or an API Gateway proxy event (JSON body, optionally base64) and returns a proxy-style response: 200 with records, 400 for bad input, 422 for a row that fails conversion. Point a Lambda at `datamold.handler.handler`; there is no deployment tooling in this repo.

## How it works

- `dsl.py` parses the mapping into rules and filters, reporting errors with the mapping line number.
- `engine.py` reads the CSV with the standard `csv` module (BOM stripped, delimiter sniffed from the header, blank rows skipped), checks that every referenced column exists, then runs each row through its rules.
- `funcs.py` holds the pipe functions. String functions apply per item when a rule has several sources.
- `mcp.py` speaks newline-delimited JSON-RPC 2.0 (`initialize`, `ping`, `tools/list`, `tools/call`); tool failures come back as `isError` results.
- `handler.py` wraps the same functions for Lambda-style invocation.

## Limitations

- Whole input is held in memory; this is not a streaming tool for multi-gigabyte files.
- One output record per CSV row. No grouping, joins or aggregation.
- Column names containing a comma or pipe cannot be used as bare sources.
- The delimiter is sniffed from the header line only (comma, semicolon, tab, pipe). Pass `--delimiter` when in doubt.
- The MCP server implements tools only (no resources or prompts) and has been tested against hand-written JSON-RPC, not every MCP client.
- The handler is a plain function; packaging and deploying it is up to you.

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

## License

MIT -- see [LICENSE](LICENSE).
