"""OCR a PDF with GLM-OCR served by vLLM (the ciwc-ocr service in docker-compose)."""

import base64
import logging
import os
import re
from collections import Counter

import pymupdf
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

OCR_URL = os.environ.get("OCR_URL", "http://localhost:8001/v1")
DPI = 200
MAX_PARALLEL_PAGES = 2
MIN_TEXT_LAYER_CHARS = 50
PAGE_EDGE_LINES = 2
MIN_PAGES_FOR_REPEATS = 3

_PAGE_NUMBER = re.compile(r"^\s*(?:page\s*)?[-–(\[]?\s*\d{1,4}\s*(?:(?:of|/)\s*\d{1,4})?\s*[-–)\]]?\s*$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")

llm = ChatOpenAI(base_url=OCR_URL, api_key="EMPTY", model="zai-org/GLM-OCR", temperature=0, max_tokens=8192)

def pdf_to_images(pdf_bytes: bytes, dpi: int = DPI) -> list[bytes]:
    """Render each PDF page to PNG bytes, in page order."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]

def ocr_message(png: bytes) -> list[HumanMessage]:
    """Build the GLM-OCR request for one page image."""
    data_url = f"data:image/png;base64,{base64.b64encode(png).decode()}"
    return [HumanMessage(content=[
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": "Text Recognition:"},
    ])]

def ocr_pdf(pdf_bytes: bytes) -> list[str]:
    """OCR every page of a PDF and return the text of each page, in page order."""
    images = pdf_to_images(pdf_bytes)
    logger.info("OCR of %d pages", len(images))
    responses = llm.batch([ocr_message(png) for png in images], config={"max_concurrency": MAX_PARALLEL_PAGES})
    for page, resp in enumerate(responses, start=1):
        if resp.response_metadata.get("finish_reason") == "length":
            logger.warning("OCR of page %d was truncated; raise max_tokens or --max-model-len", page)
    return [resp.text for resp in responses]

def text_layer_pages(pdf_bytes: bytes) -> list[str] | None:
    """Return each page's embedded text, or None if any page has too little text (a scanned page)."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = [page.get_text() for page in doc]

    if pages and all(len(p.strip()) >= MIN_TEXT_LAYER_CHARS for p in pages):
        return pages

    return None

def _edge_lines(page: str) -> list[int]:
    """Indices of the first and last PAGE_EDGE_LINES non-blank lines of a page, where headers and footers sit."""
    filled = [i for i, line in enumerate(page.splitlines()) if line.strip()]
    return sorted(set(filled[:PAGE_EDGE_LINES] + filled[-PAGE_EDGE_LINES:]))


def _edge_key(line: str) -> str:
    """A header or footer line with its digits masked, so "Page 3 of 20" and "Page 4 of 20" are the same line."""
    return _DIGITS.sub("#", " ".join(line.split()).lower())


def strip_page_furniture(pages: list[str]) -> list[str]:
    """Remove running headers, footers and page numbers, so they do not land inside clause text.

    A line at the top or bottom of a page is removed when it is a bare page number, or when, digits masked,
    it sits at the top or bottom of at least half the pages of a document of MIN_PAGES_FOR_REPEATS or more.
    """
    counts = Counter(
        key for page in pages for key in {_edge_key(page.splitlines()[i]) for i in _edge_lines(page)}
    )
    repeated = {key for key, n in counts.items() if len(pages) >= MIN_PAGES_FOR_REPEATS and n >= len(pages) / 2}

    cleaned = []
    removed = 0
    for page in pages:
        lines = page.splitlines()
        drop = {
            i for i in _edge_lines(page)
            if _PAGE_NUMBER.match(lines[i]) or _edge_key(lines[i]) in repeated
        }
        removed += len(drop)
        cleaned.append("\n".join(line for i, line in enumerate(lines) if i not in drop))

    if removed:
        logger.info("removed %d header, footer and page number lines", removed)

    return cleaned


def read_pdf(pdf_bytes: bytes) -> list[str]:
    """Text of each page: the PDF's own text layer when every page has one, otherwise GLM-OCR of every page.

    The whole document uses one source so its line format is consistent for the outline code. Running
    headers, footers and page numbers are removed. Set FORCE_OCR=1 to always OCR.
    """
    pages = None if os.environ.get("FORCE_OCR") == "1" else text_layer_pages(pdf_bytes)

    if pages is not None:
        logger.info("using the PDF text layer of %d pages", len(pages))
    else:
        pages = ocr_pdf(pdf_bytes)

    return strip_page_furniture(pages)

if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)
    pages = ocr_pdf(Path(sys.argv[1]).read_bytes())
    print("\n\n".join(pages))
