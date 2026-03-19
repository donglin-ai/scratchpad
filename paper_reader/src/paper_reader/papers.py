from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


ARXIV_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?")
DOI_PATTERN = re.compile(r"doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
OPENREVIEW_PATTERN = re.compile(r"openreview\.net/forum")
ACL_PATTERN = re.compile(r"aclanthology\.org/([A-Z0-9.-]+)/?$", re.IGNORECASE)
TEXT_URL_PATTERN = re.compile(r"https?://\S+")


@dataclass(slots=True)
class PaperLink:
    key: str
    canonical_url: str
    host: str
    pdf_url: str = ""


def extract_candidate_urls(text: str, urls: list[str]) -> list[str]:
    text_urls = TEXT_URL_PATTERN.findall(text)
    ordered: list[str] = []
    for url in [*urls, *text_urls]:
        clean = url.rstrip(").,")
        if clean not in ordered:
            ordered.append(clean)
    return ordered


def parse_paper_link(url: str) -> PaperLink | None:
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    if match := ARXIV_PATTERN.search(url):
        paper_id = match.group(1)
        return PaperLink(
            key=f"arxiv:{paper_id}",
            canonical_url=f"https://arxiv.org/abs/{paper_id}",
            host="arxiv",
            pdf_url=f"https://arxiv.org/pdf/{paper_id}.pdf",
        )

    if match := DOI_PATTERN.search(url):
        doi = match.group(1)
        return PaperLink(
            key=f"doi:{doi.lower()}",
            canonical_url=f"https://doi.org/{doi}",
            host="doi",
        )

    if OPENREVIEW_PATTERN.search(url):
        query = parse_qs(parsed.query)
        paper_id = query.get("id", [None])[0]
        if paper_id:
            return PaperLink(
                key=f"openreview:{paper_id}",
                canonical_url=f"https://openreview.net/forum?id={paper_id}",
                host="openreview",
            )

    if match := ACL_PATTERN.search(normalized):
        paper_id = match.group(1)
        return PaperLink(
            key=f"acl:{paper_id.lower()}",
            canonical_url=f"https://aclanthology.org/{paper_id}/",
            host="acl",
        )

    return None
