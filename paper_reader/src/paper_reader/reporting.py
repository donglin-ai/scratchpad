from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from paper_reader.analysis import PaperAnalysis
from paper_reader.arxiv_client import SourceRecord
from paper_reader.metadata import PaperMetadata
from paper_reader.papers import PaperLink
from paper_reader.ranking import RankedPaper


@dataclass(slots=True)
class Discovery:
    paper: PaperLink
    source: SourceRecord
    metadata: PaperMetadata
    ranking: RankedPaper
    analysis: PaperAnalysis


SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9]+")


def _slugify(text: str) -> str:
    slug = SLUG_PATTERN.sub("-", text).strip("-").lower()
    return slug or "paper"


def write_daily_summary_pdf(
    report_dir: Path,
    run_at: datetime,
    discoveries: list[Discovery],
    query: str,
) -> Path:
    """Write a concise PDF summary of today's top papers."""
    from paper_reader.pdf_report import _make_pdf, _font

    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = report_dir / f"{run_at.date().isoformat()}.pdf"

    pdf = _make_pdf()
    pdf.add_page()

    # Title
    _font(pdf, "B", 16)
    pdf.cell(0, 10, f"Daily Papers \u2014 {run_at.date().isoformat()}", new_x="LMARGIN", new_y="NEXT")
    _font(pdf, "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f"Generated: {run_at.strftime('%Y-%m-%d %H:%M UTC')}  |  Papers: {len(discoveries)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if not discoveries:
        _font(pdf, "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, "No new papers found.", new_x="LMARGIN", new_y="NEXT")
    else:
        for i, item in enumerate(discoveries, 1):
            pdf.set_text_color(0, 0, 0)

            _font(pdf, "B", 11)
            pdf.multi_cell(0, 5, f"{i}. {item.metadata.title}", new_x="LMARGIN", new_y="NEXT")

            _font(pdf, "", 7)
            pdf.set_text_color(80, 80, 80)
            authors = ", ".join(item.metadata.authors[:4])
            if len(item.metadata.authors) > 4:
                authors += " et al."
            pdf.cell(0, 4, f"{authors}  |  Score: {item.ranking.score}", new_x="LMARGIN", new_y="NEXT")

            url = item.metadata.canonical_url or item.paper.canonical_url
            if url:
                pdf.set_text_color(5, 99, 193)
                pdf.cell(0, 4, url, new_x="LMARGIN", new_y="NEXT", link=url)

            pdf.set_text_color(0, 0, 0)
            _font(pdf, "", 9)
            summary = item.analysis.summary or "No summary available."
            pdf.ln(1)
            pdf.multi_cell(0, 4, summary, new_x="LMARGIN", new_y="NEXT")

            if item.ranking.reasons:
                _font(pdf, "I", 7)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 4, f"Why: {', '.join(item.ranking.reasons[:3])}", new_x="LMARGIN", new_y="NEXT")

            pdf.ln(4)

    pdf.output(str(pdf_path))
    return pdf_path
