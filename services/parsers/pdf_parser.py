import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from services.parsers.base import ParsedContent
from services.parsers.utils import _format_rows_as_markdown, clean_text


class PdfParser:
    TOP_BOUNDARY_RATIO = 0.12
    BOTTOM_BOUNDARY_RATIO = 0.88
    OCR_BLOCK_TOP_RATIO = 0.15
    OCR_BLOCK_BOTTOM_RATIO = 0.85
    MIN_IMAGE_BLOCK_WIDTH = 24
    MIN_IMAGE_BLOCK_HEIGHT = 24
    IMAGE_RECT_MERGE_GAP = 45
    IMAGE_OCR_PREFIX = "【图片OCR】"

    def __init__(
        self,
        ocr_provider=None,
        debug_overlay_dir: str | os.PathLike | None = None,
    ):
        self.ocr_provider = ocr_provider or PyMuPdfOcrProvider()
        self.debug_overlay_dir = Path(debug_overlay_dir) if debug_overlay_dir is not None else None

    def parse(self, file_path: str) -> ParsedContent:
        with pymupdf.open(file_path) as doc:
            pages = []
            for page in doc:
                blocks, image_rects = self._extract_text_blocks_with_debug(page)
                self._save_debug_overlay(page, blocks, file_path, image_rects)
                pages.append(blocks)

        repeated_top, repeated_bottom = self._find_repeated_boundary_blocks(pages)
        page_texts = []
        page_numbers = []
        for page_index, blocks in enumerate(pages, start=1):
            filtered_blocks = [
                block.text
                for block in blocks
                if not self._is_repeated_boundary_block(block, repeated_top, repeated_bottom)
            ]
            page_text = clean_text("\n\n".join(filtered_blocks))
            if not page_text:
                continue
            page_texts.append(page_text)
            page_numbers.append(page_index)

        return ParsedContent(texts=page_texts, page_numbers=page_numbers)

    def _extract_text_blocks(self, page) -> list["PdfTextBlock"]:
        blocks, _ = self._extract_text_blocks_with_debug(page)
        return blocks

    def _extract_text_blocks_with_debug(self, page) -> tuple[list["PdfTextBlock"], list[pymupdf.Rect]]:
        blocks = []
        page_height = float(page.rect.height)
        table_blocks = self._extract_table_blocks(page, page_height)
        image_rects = self._extract_image_rects(page, table_blocks)
        needs_raw_image_rects = bool(self._get_debug_overlay_dir())
        raw_image_rects = self._extract_image_rects(page, []) if needs_raw_image_rects else image_rects
        image_ocr_blocks = self._extract_image_ocr_blocks(
            page,
            page_height,
            table_blocks,
            image_rects=image_rects,
        )

        for raw_block in page.get_text("blocks", sort=True):
            block_type = raw_block[6] if len(raw_block) > 6 else 0
            if block_type != 0:
                continue
            if self._is_inside_any_table(raw_block, table_blocks):
                continue

            text = clean_text(raw_block[4])
            if not text:
                continue

            blocks.append(
                PdfTextBlock(
                    text=text,
                    x0=float(raw_block[0]),
                    y0=float(raw_block[1]),
                    x1=float(raw_block[2]),
                    y1=float(raw_block[3]),
                    page_height=page_height,
                    kind="text",
                )
            )

        blocks.extend(table_blocks)
        blocks.extend(image_ocr_blocks)
        # 只有普通文本、表格、图片区域 OCR 都抽不到时才整页 OCR，避免文字型 PDF 被慢速 OCR 拖累。
        if not blocks:
            ocr_block = self._extract_ocr_block(page, page_height)
            if ocr_block:
                blocks.append(ocr_block)
        return sorted(blocks, key=lambda block: (block.y0, block.x0)), raw_image_rects

    def _extract_ocr_block(self, page, page_height: float) -> "PdfTextBlock | None":
        text = clean_text(self.ocr_provider.extract_text(page))
        if not text:
            return None
        return PdfTextBlock(
            text=text,
            x0=0.0,
            y0=page_height * self.OCR_BLOCK_TOP_RATIO,
            x1=float(page.rect.width),
            y1=page_height * self.OCR_BLOCK_BOTTOM_RATIO,
            page_height=page_height,
            kind="page_ocr",
        )

    def _extract_image_ocr_blocks(
        self,
        page,
        page_height: float,
        table_blocks: list["PdfTextBlock"],
        image_rects: list[pymupdf.Rect] | None = None,
    ) -> list["PdfTextBlock"]:
        if image_rects is None:
            image_rects = self._extract_image_rects(page, table_blocks)
        if not image_rects:
            return []

        region_texts = self._extract_image_region_texts(page, image_rects)
        blocks = []
        for rect, text in zip(image_rects, region_texts):
            text = clean_text(text)
            if not text:
                continue
            blocks.append(
                PdfTextBlock(
                    text=f"{self.IMAGE_OCR_PREFIX}\n{text}",
                    x0=float(rect.x0),
                    y0=float(rect.y0),
                    x1=float(rect.x1),
                    y1=float(rect.y1),
                    page_height=page_height,
                    kind="image_ocr",
                )
            )
        return blocks

    def _extract_image_rects(
        self,
        page,
        table_blocks: list["PdfTextBlock"],
    ) -> list[pymupdf.Rect]:
        rects = []
        seen = set()

        def add_rect(raw_rect) -> None:
            rect = pymupdf.Rect(raw_rect) & page.rect
            if not self._is_valid_image_rect(rect, table_blocks):
                return
            key = tuple(round(value, 1) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
            if key in seen:
                return
            seen.add(key)
            rects.append(rect)

        try:
            for image_info in page.get_image_info(xrefs=True):
                bbox = image_info.get("bbox")
                if bbox:
                    add_rect(bbox)
        except Exception as exc:
            logging.getLogger(__name__).debug("PDF 图片区域识别失败，尝试 xref 降级: %s", exc)

        try:
            for image in page.get_images(full=True):
                xref = image[0]
                for rect in page.get_image_rects(xref):
                    add_rect(rect)
        except Exception as exc:
            logging.getLogger(__name__).debug("PDF 图片 xref 区域识别失败，跳过图片 OCR: %s", exc)

        return sorted(rects, key=lambda rect: (rect.y0, rect.x0))

    def _extract_image_region_texts(self, page, rects: list[pymupdf.Rect]) -> list[str]:
        extract_regions_text = getattr(self.ocr_provider, "extract_regions_text", None)
        if callable(extract_regions_text):
            texts = list(extract_regions_text(page, rects))
            if len(texts) >= len(rects):
                return texts[:len(rects)]
            return texts + [""] * (len(rects) - len(texts))

        extract_region_text = getattr(self.ocr_provider, "extract_region_text", None)
        if callable(extract_region_text):
            return [extract_region_text(page, rect) for rect in rects]

        return []

    def _is_valid_image_rect(
        self,
        rect: pymupdf.Rect,
        table_blocks: list["PdfTextBlock"],
    ) -> bool:
        if rect.is_empty or rect.is_infinite:
            return False
        if rect.width < self.MIN_IMAGE_BLOCK_WIDTH or rect.height < self.MIN_IMAGE_BLOCK_HEIGHT:
            return False
        for table_block in table_blocks:
            if self._rect_inside_block(rect, table_block):
                return False
        return True

    @staticmethod
    def _rect_inside_block(rect: pymupdf.Rect, block: "PdfTextBlock") -> bool:
        tolerance = 2.0
        return (
            rect.x0 >= block.x0 - tolerance
            and rect.y0 >= block.y0 - tolerance
            and rect.x1 <= block.x1 + tolerance
            and rect.y1 <= block.y1 + tolerance
        )

    def _extract_table_blocks(self, page, page_height: float) -> list["PdfTextBlock"]:
        try:
            tables = page.find_tables().tables
        except Exception as exc:
            logging.getLogger(__name__).warning("PDF 表格识别失败，降级为普通文本: %s", exc)
            return []

        table_blocks = []
        for table in tables:
            markdown = _format_rows_as_markdown(table.extract())
            if not markdown:
                continue
            x0, y0, x1, y1 = table.bbox
            table_blocks.append(
                PdfTextBlock(
                    text=markdown,
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                    page_height=page_height,
                    kind="table",
                )
            )
        return table_blocks

    def _save_debug_overlay(
        self,
        page,
        blocks: list["PdfTextBlock"],
        file_path: str,
        image_rects: list[pymupdf.Rect] | None = None,
    ) -> None:
        debug_overlay_dir = self._get_debug_overlay_dir()
        if not debug_overlay_dir:
            return

        try:
            debug_overlay_dir.mkdir(parents=True, exist_ok=True)
            debug_doc = pymupdf.open()
            debug_page = debug_doc.new_page(width=page.rect.width, height=page.rect.height)
            debug_page.show_pdf_page(page.rect, page.parent, page.number)

            raw_image_rects = image_rects or []
            merged_image_rects = [
                rect
                for rect in self._merge_image_rects(raw_image_rects)
                if not self._matches_any_rect(rect, raw_image_rects)
            ]
            for image_rect in raw_image_rects:
                rect = pymupdf.Rect(image_rect) & page.rect
                if rect.is_empty or rect.is_infinite:
                    continue
                color, label = self._debug_overlay_style("image")
                debug_page.draw_rect(rect, color=color, width=0.9)
                label_y = max(8, rect.y0 - 10)
                debug_page.insert_text((rect.x0, label_y), label, fontsize=6, color=color)

            for rect in merged_image_rects:
                if rect.is_empty or rect.is_infinite:
                    continue
                color, label = self._debug_overlay_style("merged_image")
                debug_page.draw_rect(rect, color=color, width=1.8)
                label_y = max(8, rect.y0 - 18)
                debug_page.insert_text((rect.x0, label_y), label, fontsize=6, color=color)

            for block in blocks:
                rect = pymupdf.Rect(block.x0, block.y0, block.x1, block.y1) & page.rect
                if rect.is_empty or rect.is_infinite:
                    continue
                color, label = self._debug_overlay_style(block.kind)
                debug_page.draw_rect(rect, color=color, width=1.2)
                label_y = max(8, rect.y0 - 2)
                debug_page.insert_text((rect.x0, label_y), label, fontsize=6, color=color)

            safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(file_path).stem).strip("_") or "pdf"
            output_path = debug_overlay_dir / f"{safe_stem}_page_{page.number + 1:03d}.png"
            pixmap = debug_page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
            pixmap.save(str(output_path))
            debug_doc.close()
        except Exception as exc:
            logging.getLogger(__name__).warning("PDF 调试可视化导出失败，跳过: %s", exc)

    def _merge_image_rects(self, rects: list[pymupdf.Rect]) -> list[pymupdf.Rect]:
        pending = [
            pymupdf.Rect(rect)
            for rect in sorted(rects, key=lambda rect: (rect.y0, rect.x0))
            if not rect.is_empty and not rect.is_infinite
        ]
        merged = []
        while pending:
            current = pending.pop(0)
            changed = True
            while changed:
                changed = False
                remaining = []
                for rect in pending:
                    if self._rects_are_near(current, rect, self.IMAGE_RECT_MERGE_GAP):
                        current = self._union_rect(current, rect)
                        changed = True
                    else:
                        remaining.append(rect)
                pending = remaining
            merged.append(current)
        return sorted(merged, key=lambda rect: (rect.y0, rect.x0))

    @staticmethod
    def _rects_are_near(left: pymupdf.Rect, right: pymupdf.Rect, gap: float) -> bool:
        expanded = pymupdf.Rect(left.x0 - gap, left.y0 - gap, left.x1 + gap, left.y1 + gap)
        return expanded.intersects(right)

    @staticmethod
    def _union_rect(left: pymupdf.Rect, right: pymupdf.Rect) -> pymupdf.Rect:
        return pymupdf.Rect(
            min(left.x0, right.x0),
            min(left.y0, right.y0),
            max(left.x1, right.x1),
            max(left.y1, right.y1),
        )

    @classmethod
    def _matches_any_rect(cls, rect: pymupdf.Rect, rects: list[pymupdf.Rect]) -> bool:
        return any(cls._same_rect(rect, other) for other in rects)

    @staticmethod
    def _same_rect(left: pymupdf.Rect, right: pymupdf.Rect, tolerance: float = 0.5) -> bool:
        return (
            abs(left.x0 - right.x0) <= tolerance
            and abs(left.y0 - right.y0) <= tolerance
            and abs(left.x1 - right.x1) <= tolerance
            and abs(left.y1 - right.y1) <= tolerance
        )

    def _get_debug_overlay_dir(self) -> Path | None:
        if self.debug_overlay_dir:
            return self.debug_overlay_dir
        debug_dir = os.getenv("PDF_PARSER_DEBUG_OVERLAY_DIR")
        return Path(debug_dir) if debug_dir else None

    @staticmethod
    def _debug_overlay_style(kind: str) -> tuple[tuple[float, float, float], str]:
        styles = {
            "image": ((0.62, 0.15, 0.85), "image"),
            "merged_image": ((0.95, 0.0, 0.75), "merged image"),
            "text": ((0.0, 0.25, 1.0), "text"),
            "table": ((0.0, 0.55, 0.2), "table"),
            "image_ocr": ((1.0, 0.45, 0.0), "image ocr"),
            "page_ocr": ((0.9, 0.0, 0.0), "page ocr"),
        }
        return styles.get(kind, ((0.5, 0.5, 0.5), kind or "block"))

    @staticmethod
    def _is_inside_any_table(raw_block, table_blocks: list["PdfTextBlock"]) -> bool:
        if not table_blocks:
            return False
        x0, y0, x1, y1 = map(float, raw_block[:4])
        tolerance = 2.0
        for table_block in table_blocks:
            if (
                x0 >= table_block.x0 - tolerance
                and y0 >= table_block.y0 - tolerance
                and x1 <= table_block.x1 + tolerance
                and y1 <= table_block.y1 + tolerance
            ):
                return True
        return False

    def _find_repeated_boundary_blocks(
        self,
        pages: list[list["PdfTextBlock"]],
    ) -> tuple[set[str], set[str]]:
        top_counts: dict[str, int] = {}
        bottom_counts: dict[str, int] = {}

        for blocks in pages:
            page_top_keys = set()
            page_bottom_keys = set()
            for block in blocks:
                key = self._normalize_boundary_text(block.text)
                if not key:
                    continue
                if block.is_top_boundary(self.TOP_BOUNDARY_RATIO):
                    page_top_keys.add(key)
                if block.is_bottom_boundary(self.BOTTOM_BOUNDARY_RATIO):
                    page_bottom_keys.add(key)

            for key in page_top_keys:
                top_counts[key] = top_counts.get(key, 0) + 1
            for key in page_bottom_keys:
                bottom_counts[key] = bottom_counts.get(key, 0) + 1

        page_count = len(pages)
        if page_count < 2:
            return set(), set()

        threshold = min(2, page_count)
        repeated_top = {key for key, count in top_counts.items() if count >= threshold}
        repeated_bottom = {key for key, count in bottom_counts.items() if count >= threshold}
        return repeated_top, repeated_bottom

    def _is_repeated_boundary_block(
        self,
        block: "PdfTextBlock",
        repeated_top: set[str],
        repeated_bottom: set[str],
    ) -> bool:
        key = self._normalize_boundary_text(block.text)
        if not key:
            return False
        if block.is_top_boundary(self.TOP_BOUNDARY_RATIO) and key in repeated_top:
            return True
        if block.is_bottom_boundary(self.BOTTOM_BOUNDARY_RATIO) and key in repeated_bottom:
            return True
        return False

    @staticmethod
    def _normalize_boundary_text(text: str) -> str:
        normalized = clean_text(text).lower()
        normalized = re.sub(r"\d+", "#", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return ""
        if len(normalized) < 3 and normalized != "#":
            return ""
        return normalized


@dataclass(frozen=True)
class PdfTextBlock:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page_height: float
    kind: str = "text"

    def is_top_boundary(self, ratio: float) -> bool:
        return self.y0 <= self.page_height * ratio

    def is_bottom_boundary(self, ratio: float) -> bool:
        return self.y1 >= self.page_height * ratio


class PyMuPdfOcrProvider:
    def extract_text(self, page) -> str:
        if not hasattr(page, "get_textpage_ocr"):
            return ""

        try:
            text_page = page.get_textpage_ocr(full=True, dpi=200)
            return page.get_text("text", textpage=text_page)
        except Exception as exc:
            logging.getLogger(__name__).debug("PDF OCR 失败，跳过该页 OCR: %s", exc)
            return ""

    def extract_regions_text(self, page, rects: list[pymupdf.Rect]) -> list[str]:
        if not rects or not hasattr(page, "get_textpage_ocr"):
            return []

        try:
            text_page = page.get_textpage_ocr(full=True, dpi=200)
        except Exception as exc:
            logging.getLogger(__name__).debug("PDF 区域 OCR 失败，跳过图片区域 OCR: %s", exc)
            return [""] * len(rects)

        results = []
        for rect in rects:
            try:
                results.append(page.get_text("text", clip=rect, textpage=text_page))
            except Exception as exc:
                logging.getLogger(__name__).debug("PDF 区域 OCR 文本提取失败，跳过该区域: %s", exc)
                results.append("")
        return results

    def extract_region_text(self, page, rect: pymupdf.Rect) -> str:
        texts = self.extract_regions_text(page, [rect])
        return texts[0] if texts else ""
