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
    from fpdf import FPDF

    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = report_dir / f"{run_at.date().isoformat()}.pdf"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Daily Papers - {run_at.date().isoformat()}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f"Generated: {run_at.strftime('%Y-%m-%d %H:%M UTC')}  |  Papers: {len(discoveries)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if not discoveries:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, "No new papers found.", new_x="LMARGIN", new_y="NEXT")
    else:
        for i, item in enumerate(discoveries, 1):
            pdf.set_text_color(0, 0, 0)

            # Paper title
            pdf.set_font("Helvetica", "B", 11)
            title = f"{i}. {item.metadata.title}"
            pdf.multi_cell(0, 5, title, new_x="LMARGIN", new_y="NEXT")

            # Authors + link
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(80, 80, 80)
            authors = ", ".join(item.metadata.authors[:4])
            if len(item.metadata.authors) > 4:
                authors += " et al."
            meta_line = f"{authors}  |  Score: {item.ranking.score}"
            pdf.cell(0, 4, meta_line, new_x="LMARGIN", new_y="NEXT")

            url = item.metadata.canonical_url or item.paper.canonical_url
            if url:
                pdf.set_text_color(5, 99, 193)
                pdf.cell(0, 4, url, new_x="LMARGIN", new_y="NEXT", link=url)

            # Summary
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "", 9)
            summary = item.analysis.summary or "No summary available."
            pdf.ln(1)
            pdf.multi_cell(0, 4, summary, new_x="LMARGIN", new_y="NEXT")

            # Ranking reasons
            if item.ranking.reasons:
                pdf.set_font("Helvetica", "I", 7)
                pdf.set_text_color(100, 100, 100)
                pdf.cell(0, 4, f"Why: {', '.join(item.ranking.reasons[:3])}", new_x="LMARGIN", new_y="NEXT")

            pdf.ln(4)

    pdf.output(str(pdf_path))
    return pdf_path
