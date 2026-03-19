from __future__ import annotations

import re
from io import BytesIO
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

from paper_reader.config import AppConfig
from paper_reader.http import HTTPError, URLError, fetch_bytes, fetch_text
from paper_reader.papers import PaperLink


WHITESPACE_PATTERN = re.compile(r"\s+")
LINE_BREAK_PATTERN = re.compile(r"\r?\n+")
EQUATION_LINE_PATTERN = re.compile(
    r"(?:=|\\mathcal|\\lambda|\\sum|\\alpha|\\beta|\\gamma|\\theta|argmax|minimize|maximize|loss|objective)",
    re.IGNORECASE,
)
FIGURE_CAPTION_PATTERN = re.compile(r"\b(?:figure|fig\.)\s*\d+[:.]?\s+", re.IGNORECASE)
CONTRIBUTION_LINE_PATTERN = re.compile(
    r"^(?:we\s+(?:introduce|present|propose|develop|show)|our\s+(?:main\s+)?contributions?\s+(?:are|include)|in summary|to summarize)",
    re.IGNORECASE,
)
SECTION_PATTERNS = {
    "introduction": re.compile(r"\b(?:1\s+)?introduction\b", re.IGNORECASE),
    "method": re.compile(r"\b(?:2\s+)?(?:method|methods|approach|model|framework)\b", re.IGNORECASE),
    "architecture": re.compile(r"\b(?:architecture|model architecture|system overview)\b", re.IGNORECASE),
    "experiments": re.compile(r"\b(?:experiments|results|evaluation)\b", re.IGNORECASE),
    "limitations": re.compile(r"\b(?:limitations|discussion)\b", re.IGNORECASE),
    "conclusion": re.compile(r"\b(?:conclusion|conclusions)\b", re.IGNORECASE),
}


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}
        self.in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs if value is not None}
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = attrs_dict.get("name") or attrs_dict.get("property") or attrs_dict.get("http-equiv")
            content = attrs_dict.get("content")
            if key and content:
                self.meta.setdefault(key.lower(), []).append(content.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        clean = WHITESPACE_PATTERN.sub(" ", data).strip()
        if not clean:
            return
        if self.in_title:
            self.title_parts.append(clean)
        self.text_parts.append(clean)


@dataclass(slots=True)
class PaperMetadata:
    paper_key: str
    canonical_url: str
    title: str
    abstract: str
    authors: list[str]
    venue: str
    published_date: str
    pdf_url: str
    source_domain: str
    page_excerpt: str
    full_text_excerpt: str = ""
    section_snippets: dict[str, str] = field(default_factory=dict)
    equation_snippets: list[str] = field(default_factory=list)
    figure_snippets: list[str] = field(default_factory=list)
    contribution_snippets: list[str] = field(default_factory=list)
    fetch_error: str = ""
    signals: list[str] = field(default_factory=list)
    pdf_bytes: bytes = b""


def _first(meta: dict[str, list[str]], *keys: str) -> str:
    for key in keys:
        values = meta.get(key.lower())
        if values:
            return values[0].strip()
    return ""


def _all(meta: dict[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(meta.get(key.lower(), []))
    return [value.strip() for value in values if value.strip()]


def _normalize_text(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in LINE_BREAK_PATTERN.split(text) if line.strip()]


def _extract_section_snippets(text: str, snippet_chars: int = 1400) -> dict[str, str]:
    snippets: dict[str, str] = {}
    normalized = _normalize_text(text)
    for name, pattern in SECTION_PATTERNS.items():
        match = pattern.search(normalized)
        if not match:
            continue
        start = match.start()
        snippets[name] = normalized[start : start + snippet_chars].strip()
    return snippets


def _extract_equation_snippets(text: str, limit: int = 8) -> list[str]:
    snippets: list[str] = []
    for line in _split_lines(text):
        normalized = _normalize_text(line)
        if len(normalized) < 20:
            continue
        if EQUATION_LINE_PATTERN.search(normalized):
            snippets.append(normalized[:300])
        if len(snippets) >= limit:
            break
    return snippets


def _extract_figure_snippets(text: str, limit: int = 8) -> list[str]:
    snippets: list[str] = []
    for line in _split_lines(text):
        normalized = _normalize_text(line)
        if FIGURE_CAPTION_PATTERN.search(normalized):
            snippets.append(normalized[:300])
        if len(snippets) >= limit:
            break
    return snippets


def _extract_contribution_snippets(text: str, limit: int = 8) -> list[str]:
    snippets: list[str] = []
    for line in _split_lines(text):
        normalized = _normalize_text(line)
        if len(normalized) < 30:
            continue
        if CONTRIBUTION_LINE_PATTERN.search(normalized):
            snippets.append(normalized[:300])
        if len(snippets) >= limit:
            break
    return snippets


def _extract_pdf_text(pdf_bytes: bytes, max_pages: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception:  # noqa: BLE001
        return ""

    pages: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        if text:
            pages.append(text)
    return _normalize_text("\n".join(pages))


def _enrich_with_pdf(metadata: PaperMetadata, config: AppConfig) -> PaperMetadata:
    if not metadata.pdf_url:
        return metadata

    try:
        pdf_bytes = fetch_bytes(metadata.pdf_url, timeout=60)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return metadata

    metadata.pdf_bytes = pdf_bytes

    pdf_text = _extract_pdf_text(pdf_bytes, config.pdf_max_pages)
    if not pdf_text:
        return metadata

    metadata.full_text_excerpt = pdf_text[: config.pdf_text_char_limit]
    metadata.section_snippets = _extract_section_snippets(metadata.full_text_excerpt)
    metadata.equation_snippets = _extract_equation_snippets(pdf_text)
    metadata.figure_snippets = _extract_figure_snippets(pdf_text)
    metadata.contribution_snippets = _extract_contribution_snippets(pdf_text)
    return metadata


def fetch_paper_metadata(paper: PaperLink, config: AppConfig | None = None) -> PaperMetadata:
    empty = PaperMetadata(
        paper_key=paper.key,
        canonical_url=paper.canonical_url,
        title=paper.key,
        abstract="",
        authors=[],
        venue="",
        published_date="",
        pdf_url=paper.pdf_url,
        source_domain=urlparse(paper.canonical_url).netloc,
        page_excerpt="",
    )
    try:
        html = fetch_text(paper.canonical_url)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        empty.fetch_error = str(exc)
        return empty

    parser = _MetadataParser()
    parser.feed(html)
    page_text = " ".join(parser.text_parts)
    excerpt = page_text[:4000]
    title = _first(parser.meta, "citation_title", "og:title", "twitter:title")
    if not title:
        title = " ".join(parser.title_parts).strip() or paper.key

    abstract = _first(
        parser.meta,
        "citation_abstract",
        "description",
        "og:description",
        "twitter:description",
    )
    authors = _all(parser.meta, "citation_author", "author", "parsely-author")
    venue = _first(parser.meta, "citation_conference_title", "citation_journal_title")
    published_date = _first(parser.meta, "citation_publication_date", "article:published_time")
    pdf_url = _first(parser.meta, "citation_pdf_url")
    if not pdf_url:
        pdf_url = paper.pdf_url

    signals = []
    lower_text = f"{title} {abstract} {page_text[:6000]}".lower()
    for term in ("world model", "physical ai", "time series", "multimodal", "foundation model"):
        if term in lower_text:
            signals.append(term)

    metadata = PaperMetadata(
        paper_key=paper.key,
        canonical_url=paper.canonical_url,
        title=title,
        abstract=abstract,
        authors=authors,
        venue=venue,
        published_date=published_date,
        pdf_url=pdf_url,
        source_domain=urlparse(paper.canonical_url).netloc,
        page_excerpt=excerpt,
        signals=signals,
    )
    if config is not None:
        metadata = _enrich_with_pdf(metadata, config)
        if metadata.full_text_excerpt:
            signal_text = f"{lower_text} {metadata.full_text_excerpt[:6000].lower()}"
            metadata.signals = [
                term
                for term in ("world model", "physical ai", "time series", "multimodal", "foundation model")
                if term in signal_text
            ]
    return metadata
