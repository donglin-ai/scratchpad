"""HuggingFace Daily Papers client — fetches trending papers from huggingface.co/papers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from paper_reader.config import AppConfig
from paper_reader.arxiv_client import SourceRecord, ArxivRecord
from paper_reader.metadata import PaperMetadata, fetch_paper_metadata
from paper_reader.papers import PaperLink


_HF_API = "https://huggingface.co/api/daily_papers"


def _build_signals(title: str, summary: str, keywords: list[str]) -> list[str]:
    combined = f"{title} {summary} {' '.join(keywords)}".lower()
    signals = []
    for term in (
        "world model", "physical ai", "multimodal", "foundation model",
        "video generation", "vision-language", "robotics", "embodied",
        "video model", "diffusion", "3d generation", "time series",
    ):
        if term in combined:
            signals.append(term)
    return signals


def fetch_hf_daily_papers(config: AppConfig) -> list[ArxivRecord]:
    """Fetch today's HuggingFace daily papers and convert to ArxivRecord format."""
    from paper_reader.http import fetch_text

    try:
        raw = fetch_text(_HF_API, timeout=30)
        entries = json.loads(raw)
    except Exception:
        return []

    records: list[ArxivRecord] = []
    for entry in entries:
        paper = entry.get("paper", {})
        arxiv_id = paper.get("id", "")
        if not arxiv_id:
            continue

        title = paper.get("title", "")
        summary = paper.get("summary", "")
        upvotes = paper.get("upvotes", 0)
        keywords = paper.get("ai_keywords", [])
        org = paper.get("organization", {})
        org_name = org.get("fullname", "")

        authors = [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]
        published = paper.get("publishedAt", "")
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        canonical_url = f"https://arxiv.org/abs/{arxiv_id}"

        signals = _build_signals(title, summary, keywords)

        paper_link = PaperLink(
            key=f"arxiv:{arxiv_id}",
            canonical_url=canonical_url,
            host="arxiv",
            pdf_url=pdf_url,
        )

        metadata = PaperMetadata(
            paper_key=f"arxiv:{arxiv_id}",
            canonical_url=canonical_url,
            title=title,
            abstract=summary,
            authors=authors,
            venue=org_name,
            published_date=published,
            pdf_url=pdf_url,
            source_domain="huggingface.co",
            page_excerpt=f"{title}\n\n{summary}"[:4000],
            signals=signals,
        )

        source = SourceRecord(
            source_id=f"hf-daily:{arxiv_id}",
            source_name="HuggingFace Daily",
            title=title,
            text=summary,
            created_at=published,
            urls=[canonical_url],
        )

        # Store HF upvotes as a signal for ranking
        if upvotes >= 10:
            signals.append(f"hf_upvotes:{upvotes}")
            metadata.signals = signals

        records.append(ArxivRecord(paper=paper_link, metadata=metadata, source=source))

    return records
