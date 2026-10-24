import base64
import io
import json
import subprocess
import sys

import pytest

from datamold import cli, mcp
from datamold.handler import handler

CSV = "id,name\n1,ann\n2,bob\n"
MAP = "id: int <- id\nname <- name | title"


def test_handler_direct_event() -> None:
    out = handler({"csv": CSV, "mapping": MAP}, None)
    body = json.loads(out["body"])
    assert out["statusCode"] == 200
    assert body["records"] == [{"id": 1, "name": "Ann"}, {"id": 2, "name": "Bob"}]


def test_handler_proxy_event_plain_and_base64() -> None:
    raw = json.dumps({"csv": CSV, "mapping": MAP, "limit": 1})
    assert len(json.loads(handler({"body": raw})["body"])["records"]) == 1
    b64 = base64.b64encode(raw.encode()).decode()
    out = handler({"body": b64, "isBase64Encoded": True})
    assert out["statusCode"] == 200


def test_handler_error_status_codes() -> None:
    assert handler({"body": "not json"})["statusCode"] == 400
    assert handler({"csv": CSV})["statusCode"] == 400
    assert handler({"csv": CSV, "mapping": "x <- missing"})["statusCode"] == 400
    bad = handler({"csv": CSV, "mapping": "n: int <- name"})
    assert bad["statusCode"] == 422 and "row 1" in json.loads(bad["body"])["error"]
    assert handler({"action": "zap", "csv": CSV})["statusCode"] == 400
    assert handler([1, 2])["statusCode"] == 400


def test_handler_validate_and_infer_actions() -> None:
    ok = json.loads(handler({"action": "validate", "mapping": MAP, "csv": CSV})["body"])
    assert ok["ok"] and ok["csv_columns"] == ["id", "name"]
    inf = json.loads(handler({"action": "infer", "csv": CSV})["body"])
    assert "id: int <- id" in inf["mapping"]


def rpc(*messages: dict) -> list[dict]:
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_mcp_initialize_list_and_call() -> None:
    replies = rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "convert_csv", "arguments": {"csv": CSV, "mapping": MAP}},
        },
    )
    assert [r["id"] for r in replies] == [1, 2, 3]  # the notification gets no reply
    assert replies[0]["result"]["serverInfo"]["name"] == "datamold"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert names == {"convert_csv", "validate_mapping", "infer_mapping", "list_functions"}
    payload = json.loads(replies[2]["result"]["content"][0]["text"])
    assert payload["records"][1] == {"id": 2, "name": "Bob"}


def test_mcp_tool_errors_are_results_not_protocol_errors() -> None:
    (reply,) = rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "convert_csv", "arguments": {"csv": CSV, "mapping": "x <- nope"}},
        }
    )
    assert reply["result"]["isError"] is True
    assert "nope" in reply["result"]["content"][0]["text"]


def test_mcp_protocol_errors() -> None:
    replies = rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "nope"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "zzz"}},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    )
    assert replies[0]["error"]["code"] == -32601
    assert replies[1]["error"]["code"] == -32602
    assert replies[2]["result"] == {}


def test_mcp_bad_json_and_batch() -> None:
    out = io.StringIO()
    batch = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "x"}]
    mcp.serve(io.StringIO("{oops\n" + json.dumps(batch) + "\n"), out)
    first, second = (json.loads(line) for line in out.getvalue().splitlines())
    assert first["error"]["code"] == -32700
    assert [r["id"] for r in second] == [1]


def test_cli_convert_writes_file_and_reports(tmp_path, capsys) -> None:
    (tmp_path / "in.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "m.dm").write_text(MAP, encoding="utf-8")
    out = tmp_path / "out.json"
    csv_in, mapping = str(tmp_path / "in.csv"), str(tmp_path / "m.dm")
    code = cli.main(["convert", csv_in, "-m", mapping, "-o", str(out)])
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))[0]["name"] == "Ann"
    assert "2 records from 2 rows" in capsys.readouterr().err


def test_cli_ndjson_and_exit_codes(tmp_path, capsys) -> None:
    (tmp_path / "in.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "m.dm").write_text("n: int <- name", encoding="utf-8")
    args = ["convert", str(tmp_path / "in.csv"), "-m", str(tmp_path / "m.dm")]
    assert cli.main(args) == 1
    assert cli.main([*args, "--on-error", "null", "--ndjson"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line) for line in lines] == [{"n": None}, {"n": None}]
    (tmp_path / "m.dm").write_text("garbage", encoding="utf-8")
    assert cli.main(args) == 2
    assert cli.main(["convert", str(tmp_path / "missing.csv"), "-m", str(tmp_path / "m.dm")]) == 2


def test_cli_check_infer_functions(tmp_path, capsys) -> None:
    (tmp_path / "in.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "m.dm").write_text(MAP, encoding="utf-8")
    assert cli.main(["check", str(tmp_path / "m.dm"), "--csv", str(tmp_path / "in.csv")]) == 0
    assert "ok: 2 rules" in capsys.readouterr().out
    (tmp_path / "m.dm").write_text("a <- zzz", encoding="utf-8")
    assert cli.main(["check", str(tmp_path / "m.dm"), "--csv", str(tmp_path / "in.csv")]) == 2
    assert cli.main(["infer", str(tmp_path / "in.csv")]) == 0
    assert cli.main(["functions"]) == 0
    assert "split(sep)" in capsys.readouterr().out


def test_cli_bad_delimiter(tmp_path) -> None:
    (tmp_path / "in.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "m.dm").write_text(MAP, encoding="utf-8")
    csv_in, mapping = str(tmp_path / "in.csv"), str(tmp_path / "m.dm")
    code = cli.main(["convert", csv_in, "-m", mapping, "--delimiter", "ab"])
    assert code == 2


def test_module_entry_point_runs_end_to_end(tmp_path) -> None:
    (tmp_path / "in.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "m.dm").write_text(MAP, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "datamold", "convert", "-m", str(tmp_path / "m.dm"), "-"],
        input=CSV,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)[1] == {"id": 2, "name": "Bob"}


@pytest.mark.parametrize("bad", ["-1", "x", True])
def test_api_limit_validation(bad) -> None:
    from datamold import api
    from datamold.errors import DatamoldError

    with pytest.raises(DatamoldError):
        api.convert({"csv": CSV, "mapping": MAP, "limit": bad})


def test_cli_limit(tmp_path, capsys) -> None:
    (tmp_path / "in.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "m.dm").write_text(MAP, encoding="utf-8")
    args = ["convert", str(tmp_path / "in.csv"), "-m", str(tmp_path / "m.dm"), "--ndjson"]
    assert cli.main([*args, "--limit", "1"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1
    assert cli.main([*args, "--limit", "-2"]) == 2
