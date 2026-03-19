from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from paper_reader.config import AppConfig
from paper_reader.metadata import PaperMetadata, fetch_paper_metadata
from paper_reader.papers import PaperLink


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


@dataclass(slots=True)
class SourceRecord:
    source_id: str
    source_name: str
    title: str
    text: str
    created_at: str
    urls: list[str]


@dataclass(slots=True)
class ArxivRecord:
    paper: PaperLink
    metadata: PaperMetadata
    source: SourceRecord


def _text(node: ET.Element | None, path: str, default: str = "") -> str:
    if node is None:
        return default
    child = node.find(path, ATOM_NS)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _all_text(node: ET.Element, path: str) -> list[str]:
    return [item.text.strip() for item in node.findall(path, ATOM_NS) if item.text]


def _build_signals(parts: Iterable[str]) -> list[str]:
    combined = " ".join(parts).lower()
    signals = []
    for term in ("world model", "physical ai", "time series", "multimodal", "foundation model", "robotics"):
        if term in combined:
            signals.append(term)
    return signals


class ArxivClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build_query(self) -> str:
        if not self.config.topic_keywords:
            raise ValueError("config.toml must define at least one topic keyword.")

        topic_clauses: list[str] = []
        for keyword in self.config.topic_keywords:
            safe = keyword.replace('"', "")
            topic_clauses.append(f'all:"{safe}"')
        query = "(" + " OR ".join(topic_clauses) + ")"

        if self.config.arxiv_categories:
            category_clause = "(" + " OR ".join(f"cat:{category}" for category in self.config.arxiv_categories) + ")"
            return f"{query} AND {category_clause}"
        return query

    def search(self, start_time: datetime | None = None) -> list[ArxivRecord]:
        if start_time is None:
            start_time = datetime.now(UTC) - timedelta(hours=self.config.lookback_hours)

        params = urlencode(
            {
                "search_query": self.build_query(),
                "start": 0,
                "max_results": self.config.max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        request = Request(
            f"{self.config.arxiv_api_url}?{params}",
            headers={"User-Agent": "paper-reader/0.3 (+arxiv-first)"},
        )
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")

        root = ET.fromstring(payload)
        records: list[ArxivRecord] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            record = self._parse_entry(entry)
            published = datetime.fromisoformat(record.metadata.published_date.replace("Z", "+00:00"))
            if published < start_time.astimezone(UTC):
                continue
            records.append(record)
        return records

    def _parse_entry(self, entry: ET.Element) -> ArxivRecord:
        entry_id = _text(entry, "atom:id")
        title = _text(entry, "atom:title")
        abstract = _text(entry, "atom:summary")
        authors = _all_text(entry, "atom:author/atom:name")
        published = _text(entry, "atom:published")
        updated = _text(entry, "atom:updated")
        primary_category = ""
        primary = entry.find("arxiv:primary_category", ATOM_NS)
        if primary is not None:
            primary_category = primary.attrib.get("term", "")

        links = [link.attrib.get("href", "") for link in entry.findall("atom:link", ATOM_NS)]
        pdf_url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
                break

        paper_id = entry_id.rsplit("/", maxsplit=1)[-1]
        base_paper_id = paper_id.split("v", maxsplit=1)[0]
        key = f"arxiv:{paper_id}"
        canonical_url = f"https://arxiv.org/abs/{base_paper_id}"
        paper = PaperLink(key=f"arxiv:{base_paper_id}", canonical_url=canonical_url, host="arxiv", pdf_url=pdf_url)
        metadata = PaperMetadata(
            paper_key=f"arxiv:{base_paper_id}",
            canonical_url=canonical_url,
            title=title,
            abstract=abstract,
            authors=authors,
            venue=primary_category,
            published_date=published,
            pdf_url=pdf_url,
            source_domain="arxiv.org",
            page_excerpt=f"{title}\n\n{abstract}"[:4000],
            signals=_build_signals([title, abstract, primary_category, " ".join(authors)]),
        )
        source = SourceRecord(
            source_id=entry_id,
            source_name="arXiv",
            title=title,
            text=abstract,
            created_at=updated or published,
            urls=[url for url in links if url],
        )
        enriched = fetch_paper_metadata(paper, self.config)
        if enriched.title == paper.key and metadata.title:
            enriched.title = metadata.title
        if not enriched.abstract and metadata.abstract:
            enriched.abstract = metadata.abstract
        if not enriched.authors and metadata.authors:
            enriched.authors = metadata.authors
        if not enriched.venue and metadata.venue:
            enriched.venue = metadata.venue
        if not enriched.published_date and metadata.published_date:
            enriched.published_date = metadata.published_date
        if not enriched.pdf_url and metadata.pdf_url:
            enriched.pdf_url = metadata.pdf_url
        if not enriched.page_excerpt and metadata.page_excerpt:
            enriched.page_excerpt = metadata.page_excerpt
        merged_signals = list(dict.fromkeys([*metadata.signals, *enriched.signals]))
        enriched.signals = merged_signals
        return ArxivRecord(paper=paper, metadata=enriched, source=source)
