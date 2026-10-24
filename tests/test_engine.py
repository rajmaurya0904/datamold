import pytest

from datamold.engine import infer_mapping, read_csv, transform
from datamold.errors import DatamoldError, RowError

CSV = """id,name,age,status
1, Ann ,30,active
2,Bob,,inactive
3,Cy,41,active
"""


def test_basic_conversion_with_types_and_nesting() -> None:
    res = transform(CSV, "id: int <- id\nname <- name | trim\nmeta.age: int <- age")
    assert res.records[0] == {"id": 1, "name": "Ann", "meta": {"age": 30}}
    assert res.records[1]["meta"]["age"] is None
    assert res.summary() == {"rows_read": 3, "rows_filtered": 0, "records": 3, "errors": 0}


def test_filter_numeric_and_text_ops() -> None:
    res = transform(CSV, "@filter age > 35\nid <- id")
    assert [r["id"] for r in res.records] == ["3"]
    assert res.rows_filtered == 2
    res = transform(CSV, "@filter age empty\nid <- id")
    assert [r["id"] for r in res.records] == ["2"]
    res = transform(CSV, "@filter status contains act\nid <- id")
    assert len(res.records) == 3
    res = transform(CSV, "@filter status != active\n@filter id notempty\nid <- id")
    assert [r["id"] for r in res.records] == ["2"]


def test_multiple_sources_literals_and_row_number() -> None:
    res = transform(CSV, 'n <- $row\nlabel <- id, name | trim | join("-")\nsrc <- "csv"')
    assert res.records[0] == {"n": 1, "label": "1-Ann", "src": "csv"}
    assert res.records[2]["n"] == 3


def test_list_target_wraps_scalars_and_handles_none() -> None:
    res = transform(CSV, "ages[] <- age")
    assert res.records[0]["ages"] == ["30"]
    assert res.records[1]["ages"] == []


def test_passthrough_keeps_unmapped_columns() -> None:
    res = transform(CSV, "@passthrough\nid: int <- id")
    assert res.records[0] == {"name": " Ann ", "age": "30", "status": "active", "id": 1}


def test_on_error_modes() -> None:
    bad = "n: int <- name"
    with pytest.raises(RowError) as exc:
        transform(CSV, bad)
    assert exc.value.row == 1
    skipped = transform(CSV, bad, on_error="skip")
    assert skipped.records == [] and len(skipped.errors) == 3
    nulled = transform(CSV, bad, on_error="null")
    assert [r["n"] for r in nulled.records] == [None, None, None]
    assert nulled.errors[0].startswith("row 1:")


def test_invalid_on_error_value() -> None:
    with pytest.raises(DatamoldError):
        transform(CSV, "id <- id", on_error="explode")


def test_missing_column_is_reported_with_available_columns() -> None:
    with pytest.raises(DatamoldError) as exc:
        transform(CSV, "x <- nope")
    assert "nope" in str(exc.value) and "id, name, age, status" in str(exc.value)


def test_delimiter_sniffing_and_explicit() -> None:
    header, rows = read_csv("a;b\n1;2\n")
    assert header == ["a", "b"] and rows[0]["b"] == "2"
    header, rows = read_csv("a|b\n1|2\n", "|")
    assert rows[0]["a"] == "1"
    _, rows = read_csv("a\tb\n1\t2\n")
    assert rows[0]["b"] == "2"


def test_quoted_fields_bom_and_blank_lines() -> None:
    header, rows = read_csv('﻿a,b\n"x, y","line\nbreak"\n\n,\n')
    assert header == ["a", "b"]
    assert len(rows) == 1 and rows[0]["a"] == "x, y" and rows[0]["b"] == "line\nbreak"


def test_short_rows_are_padded_and_long_rows_rejected() -> None:
    _, rows = read_csv("a,b,c\n1,2\n")
    assert rows[0]["c"] == ""
    with pytest.raises(RowError, match="3 cells"):
        read_csv("a,b\n1,2,3\n")


def test_empty_and_duplicate_header_rejected() -> None:
    with pytest.raises(DatamoldError, match="empty"):
        read_csv("  \n")
    with pytest.raises(DatamoldError, match="duplicate"):
        read_csv("a,a\n1,2\n")


def test_infer_mapping_guesses_types_and_round_trips() -> None:
    text = infer_mapping("Id,Price,Active,Note\n1,2.5,true,hi\n2,3,false,\n")
    assert "id: int <- Id" in text
    assert "price: float <- Price" in text
    assert "active: bool <- Active" in text
    assert "note <- Note | trim" in text
    res = transform("Id,Price,Active,Note\n1,2.5,true,hi\n", text)
    assert res.records == [{"id": 1, "price": 2.5, "active": True, "note": "hi"}]


def test_distinct_keeps_first_row_per_key() -> None:
    text = "k,v\na,1\nb,2\na,3\n"
    res = transform(text, "@distinct k\nv <- v")
    assert [r["v"] for r in res.records] == ["1", "2"]
    assert res.rows_filtered == 1


def test_distinct_column_must_exist_and_needs_a_name() -> None:
    from datamold.errors import MappingSyntaxError

    with pytest.raises(DatamoldError, match="nope"):
        transform("a\n1\n", "@distinct nope\nx <- a")
    with pytest.raises(MappingSyntaxError):
        transform("a\n1\n", "@distinct\nx <- a")
