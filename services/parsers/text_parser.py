from services.parsers.base import ParsedContent
from services.parsers.utils import clean_text


class TxtParser:
    def parse(self, file_path: str) -> ParsedContent:
        with open(file_path, "r", encoding="utf-8") as f:
            return ParsedContent(texts=[clean_text(f.read())])
