from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedContent:
    texts: list[str]
    page_numbers: list[int] | None = None
