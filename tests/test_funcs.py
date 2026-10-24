import pytest

from datamold.funcs import FUNCTIONS


def call(name: str, value, *args):
    return FUNCTIONS[name](value, *args)


def test_string_functions_pass_none_through() -> None:
    for name in ("trim", "lower", "upper", "title"):
        assert call(name, None) is None


def test_string_functions_work_elementwise_on_lists() -> None:
    assert call("trim", [" a ", " b"]) == ["a", "b"]
    assert call("upper", ["a", None]) == ["A", None]


def test_int_handles_thousands_separators_and_whole_floats() -> None:
    assert call("int", "1,200") == 1200
    assert call("int", "3.0") == 3
    assert call("int", "") is None


def test_int_rejects_fractions_and_garbage() -> None:
    with pytest.raises(ValueError, match="fraction"):
        call("int", "3.5")
    with pytest.raises(ValueError, match="cannot convert"):
        call("int", "abc")


def test_float_and_bool() -> None:
    assert call("float", "1,234.5") == 1234.5
    assert call("bool", "Yes") is True
    assert call("bool", "off") is False
    with pytest.raises(ValueError):
        call("bool", "maybe")


def test_split_and_join() -> None:
    assert call("split", "a; b ;c", ";") == ["a", "b", "c"]
    assert call("split", None) == []
    assert call("join", ["a", None, "b"], "-") == "a-b"
    assert call("join", [None, ""], "-") is None


def test_default_replace_regex() -> None:
    assert call("default", None, "x") == "x"
    assert call("default", "y", "x") == "y"
    assert call("replace", "a-b", "-", "_") == "a_b"
    assert call("regex", "tel: 555-1234", r"\D", "") == "5551234"
    with pytest.raises(ValueError, match="bad regex"):
        call("regex", "x", "(")


def test_map_with_wildcard_and_literal_coercion() -> None:
    assert call("map", "A", "A=true", "*=false") is True
    assert call("map", "Z", "A=true", "*=false") is False
    assert call("map", "n", "n=5") == 5
    with pytest.raises(ValueError, match="no map"):
        call("map", "Z", "A=1")
    with pytest.raises(ValueError, match="key=value"):
        call("map", "Z", "oops")


def test_date_reformat() -> None:
    assert call("date", "03/04/2024", "%d/%m/%Y", "%Y-%m-%d") == "2024-04-03"
    with pytest.raises(ValueError, match="date format"):
        call("date", "2024-04-03", "%d/%m/%Y")


def test_required_and_nullif_and_round() -> None:
    with pytest.raises(ValueError, match="required"):
        call("required", None)
    assert call("nullif", "N/A", "N/A") is None
    assert call("round", "2.567", "1") == 2.6
