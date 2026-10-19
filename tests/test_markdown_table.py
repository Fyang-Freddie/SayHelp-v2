from app.ingest.markdown_table import parse_markdown_table

SAMPLE = """\
# 标题
| a | b | c |
|---|---|---|
| 1 | 2 | 3 |
| 4 | 5 | 6 |

不属于表格的段落
"""


def test_parses_first_table():
    headers, rows = parse_markdown_table(SAMPLE)
    assert headers == ["a", "b", "c"]
    assert rows == [["1", "2", "3"], ["4", "5", "6"]]


def test_skips_alignment_separator():
    text = "| x | y |\n|:---|---:|\n| a | b |\n"
    headers, rows = parse_markdown_table(text)
    assert headers == ["x", "y"]
    assert rows == [["a", "b"]]


def test_no_table_returns_none():
    assert parse_markdown_table("只有文字，没有表格。") is None


def test_ignores_after_table_ends():
    text = "| a |\n|---|\n| 1 |\n\n后续非表格内容\n| 假 |\n"
    headers, rows = parse_markdown_table(text)
    assert headers == ["a"]
    assert rows == [["1"]]
