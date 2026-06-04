from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from services.parsers.base import ParsedContent
from services.parsers.utils import _format_rows_as_markdown, clean_text


class DocxParser:
    def parse(self, file_path: str) -> ParsedContent:
        doc = DocxDocument(file_path)
        blocks = []

        for block in self._iter_blocks(doc):
            if isinstance(block, Paragraph):
                text = clean_text(block.text)
                if text:
                    blocks.append(text)
            elif isinstance(block, Table):
                table_text = self._format_table(block)
                if table_text:
                    blocks.append(table_text)

        return ParsedContent(texts=["\n\n".join(blocks)])

    @staticmethod
    def _iter_blocks(doc):
        for child in doc.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, doc)
            elif isinstance(child, CT_Tbl):
                yield Table(child, doc)

    @staticmethod
    def _format_table(table) -> str:
        return _format_rows_as_markdown([
            [cell.text for cell in row.cells]
            for row in table.rows
        ])
