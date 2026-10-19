import re

_SEPARATOR_CELL = re.compile(r":?-{2,}:?")


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL.fullmatch(c) for c in cells)


def parse_markdown_table(text: str) -> tuple[list[str], list[list[str]]] | None:
    headers: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if headers is not None:
                break  # 表格结束后的非表格行
            continue
        cells = _split_row(s)
        if _is_separator(cells):
            continue
        if headers is None:
            headers = cells
        else:
            rows.append(cells)
    if headers is None:
        return None
    return headers, rows
