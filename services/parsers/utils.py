import re


def _join_spaced_alnum(match: re.Match) -> str:
    return re.sub(r"\s+", "", match.group(0))


def _join_common_short_terms(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    joined = f"{left}{right}"
    common_terms = {
        "ai",
        "io",
        "ip",
        "id",
        "db",
        "os",
        "fd",
        "ui",
        "ux",
        "cv",
        "nl",
        "qa",
    }
    return joined if joined.lower() in common_terms else match.group(0)


def clean_text(text: str) -> str:
    """
    1. 修复英文/数字被空格拆开的情况（如 "R e d i s"、"A O F"）
    2. 统一换行符
    3. 压缩多余空格
    4. 去掉过多空行（连续多个空行 → 保留1个）
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 修复 PDF 行尾英文断词，如 "fea-\ntures" -> "features"。
    text = re.sub(r"([A-Za-z])-\n\s*([A-Za-z])", r"\1\2", text)

    # 清理 LaTeX/PDF 解析残留的引用标记，保留公式主体文本。
    text = re.sub(
        r"\\\s*(?:l\s*a\s*b\s*e\s*l|r\s*e\s*f|c\s*i\s*t\s*e)\s*\{[^{}]*\}",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # 只合并 3 个及以上单字符英文/数字序列，避免把 "Redis is fast" 误伤成 "Redisisfast"。
    text = re.sub(
        r"(?<![a-zA-Z0-9])(?:[a-zA-Z0-9]\s+){2,}[a-zA-Z0-9](?![a-zA-Z0-9])",
        _join_spaced_alnum,
        text,
    )
    # 额外处理常见两字符技术词，如 "I O"、"f d"、"A I"。
    text = re.sub(
        r"(?<![a-zA-Z0-9])([a-zA-Z])\s+([a-zA-Z])(?![a-zA-Z0-9])",
        _join_common_short_terms,
        text,
    )

    cleaned_lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t\f\v\u00a0]+", " ", line)
        cleaned_lines.append(line.strip())

    result_lines = []
    prev_empty = False
    for line in cleaned_lines:
        is_empty = line == ""
        if is_empty and prev_empty:
            continue
        result_lines.append(line)
        prev_empty = is_empty

    return "\n".join(result_lines)


def _format_rows_as_markdown(rows: list[list[str | None]]) -> str:
    cleaned_rows = []
    for row in rows:
        cells = [
            clean_text(str(cell or "")).replace("\n", " ").strip()
            for cell in row
        ]
        if any(cells):
            cleaned_rows.append(cells)

    if not cleaned_rows:
        return ""

    max_columns = max(len(row) for row in cleaned_rows)
    normalized_rows = [
        row + [""] * (max_columns - len(row))
        for row in cleaned_rows
    ]
    header = normalized_rows[0]
    separator = ["---"] * max_columns
    markdown_rows = [header, separator, *normalized_rows[1:]]
    return "\n".join(
        "| " + " | ".join(row) + " |"
        for row in markdown_rows
    )
