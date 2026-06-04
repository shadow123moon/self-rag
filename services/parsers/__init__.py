from services.parsers.base import ParsedContent
from services.parsers.docx_parser import DocxParser
from services.parsers.pdf_parser import PdfParser, PdfTextBlock, PyMuPdfOcrProvider
from services.parsers.text_parser import TxtParser
from services.parsers.utils import clean_text


PARSERS = {
    ".txt": TxtParser(),
    ".pdf": PdfParser(),
    ".docx": DocxParser(),
}


def parse_file_content(file_path: str, ext: str) -> ParsedContent:
    normalized_ext = ext.lower()
    parser = PARSERS.get(normalized_ext)
    if not parser:
        raise ValueError(f"不支持的文件类型: {ext}")
    return parser.parse(file_path)
