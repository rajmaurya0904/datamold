import pytest

from datamold.dsl import parse_mapping
from datamold.errors import MappingSyntaxError


def test_parses_rule_with_type_and_pipeline() -> None:
    m = parse_mapping('id: int <- user_id | trim\nname <- first, last | join(" ")')
    assert [r.target for r in m.rules] == [("id",), ("name",)]
    assert [c.name for c in m.rules[0].pipeline] == ["trim", "int"]
    assert len(m.rules[1].sources) == 2
    assert m.rules[1].pipeline[0].args == (" ",)


def test_comments_and_blank_lines_are_ignored() -> None:
    m = parse_mapping("# hello\n\n  a <- b  \n")
    assert len(m.rules) == 1


def test_nested_and_list_targets() -> None:
    m = parse_mapping("a.b.c <- x\ntags[] <- t")
    assert m.rules[0].target == ("a", "b", "c")
    assert m.rules[1].as_list and m.rules[1].target == ("tags",)


def test_quoted_literal_with_pipe_and_comma_inside() -> None:
    m = parse_mapping('x <- "a|b,c"')
    assert m.rules[0].sources[0].kind == "literal"
    assert m.rules[0].sources[0].value == "a|b,c"


def test_function_args_may_contain_commas_in_quotes() -> None:
    m = parse_mapping('x <- a | replace(",", ";")')
    assert m.rules[0].pipeline[0].args == (",", ";")


def test_filters_and_passthrough() -> None:
    m = parse_mapping('@filter status == "on hold"\n@filter n >= 3\n@passthrough\na <- b')
    assert m.passthrough
    assert (m.filters[0].column, m.filters[0].op, m.filters[0].value) == ("status", "==", "on hold")
    assert m.filters[1].op == ">="


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("just words", "'<-'"),
        ("a <- b | nosuch", "unknown function"),
        ("a: wat <- b", "unknown type"),
        ("1bad <- b", "invalid target"),
        ('a <- "oops', "unterminated"),
        ("a <- b | split(", "unbalanced"),
        ("a <- b\na <- c", "already defined"),
        ("a <- b\na.x <- c", "already a value"),
        ("a.x <- b\na <- c", "also used as an object"),
        ("@wat x", "unknown directive"),
        ("@filter broken", "@filter needs"),
        ("# only a comment", "no rules"),
    ],
)
def test_syntax_errors_name_the_problem(text: str, fragment: str) -> None:
    with pytest.raises(MappingSyntaxError) as exc:
        parse_mapping(text)
    assert fragment in str(exc.value)


def test_error_carries_line_number() -> None:
    with pytest.raises(MappingSyntaxError) as exc:
        parse_mapping("a <- b\n\nc <- d | nosuch")
    assert exc.value.line == 3
    assert "line 3" in str(exc.value)
