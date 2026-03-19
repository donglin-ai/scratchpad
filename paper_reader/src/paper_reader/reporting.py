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


def write_paper_detail(details_dir: Path, discovery: Discovery) -> Path:
    """Write a Markdown report with restructured layout: problem/solution first, metadata at end."""
    paper_dir = details_dir
    paper_dir.mkdir(parents=True, exist_ok=True)
    detail_path = paper_dir / f"{_slugify(discovery.paper.key)}.md"
    lines = [
        f"# {discovery.metadata.title}",
        "",
        "## Research Questions",
        "",
    ]
    for item in discovery.analysis.research_questions:
        lines.append(f"- {item}")

    # Intuitive explanation right after research questions
    if discovery.analysis.intuitive_explanation:
        lines.extend(["", "## How This Paper Solves It", ""])
        lines.append(discovery.analysis.intuitive_explanation)

    lines.extend(["", "## Key Contributions", ""])
    for item in discovery.analysis.key_contributions:
        lines.append(f"- {item}")

    # Key formulas section
    if discovery.analysis.key_formulas:
        lines.extend(["", "## Key Formulas", ""])
        for formula in discovery.analysis.key_formulas:
            name = formula.get("name", "Formula")
            latex = formula.get("latex", "")
            explanation = formula.get("explanation", "")
            lines.extend([f"### {name}", ""])
            if latex:
                lines.append(f"$$\n{latex}\n$$")
            if explanation:
                lines.extend(["", explanation])
            lines.append("")

    # Key figures section
    if discovery.analysis.key_figures:
        lines.extend(["", "## Key Figures", ""])
        for fig in discovery.analysis.key_figures:
            fig_id = fig.get("figure_id", "Figure")
            desc = fig.get("description", "")
            sig = fig.get("significance", "")
            lines.extend([f"### {fig_id}", ""])
            if desc:
                lines.append(f"**Description:** {desc}")
            if sig:
                lines.append(f"**Significance:** {sig}")
            lines.append("")

    # Solution limitations
    if discovery.analysis.solution_limitations:
        lines.extend(["## Limitations of the Proposed Solution", ""])
        for item in discovery.analysis.solution_limitations:
            lines.append(f"- {item}")

    lines.extend(["", "## Key Changes", ""])
    for change in discovery.analysis.key_changes:
        lines.extend(
            [
                f"### {change.get('change_type', 'unknown')}",
                "",
                f"- Summary: {change.get('summary', '')}",
                f"- Before: {change.get('before', '')}",
                f"- After: {change.get('after', '')}",
                f"- Evidence: {change.get('evidence', '')}",
                "",
            ]
        )

    lines.extend(["## Architecture", "", f"Before: {discovery.analysis.architecture_before}", "", f"After: {discovery.analysis.architecture_after}", ""])
    if discovery.analysis.architecture_before_mermaid:
        lines.extend(["```mermaid", discovery.analysis.architecture_before_mermaid, "```", ""])
    if discovery.analysis.architecture_after_mermaid:
        lines.extend(["```mermaid", discovery.analysis.architecture_after_mermaid, "```", ""])

    lines.extend(["## Conclusions", ""])
    lines.extend(f"- {item}" for item in discovery.analysis.key_conclusions)

    lines.extend(["", "## General Limitations", ""])
    lines.extend(f"- {item}" for item in discovery.analysis.key_limitations)

    if discovery.analysis.evidence_gaps:
        lines.extend(["", "## Evidence Gaps", ""])
        lines.extend(f"- {item}" for item in discovery.analysis.evidence_gaps)

    # Metadata section at the end
    lines.extend([
        "",
        "---",
        "",
        "## Paper Metadata",
        "",
        f"- Paper key: `{discovery.paper.key}`",
        f"- Paper URL: {discovery.paper.canonical_url}",
        f"- PDF URL: {discovery.metadata.pdf_url or 'N/A'}",
        f"- Venue: {discovery.metadata.venue or 'Unknown'}",
        f"- Authors: {', '.join(discovery.metadata.authors) or 'Unknown'}",
        f"- Source: {discovery.source.source_name}",
        f"- Ranking score: {discovery.ranking.score}",
        f"- Ranking reasons: {', '.join(discovery.ranking.reasons) or 'None'}",
    ])

    if discovery.metadata.abstract:
        lines.extend(["", "## Abstract", "", discovery.metadata.abstract, ""])

    detail_path.write_text("\n".join(lines).strip() + "\n")
    return detail_path


def write_single_paper_analysis(output_dir: Path, discovery: Discovery) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return write_paper_detail(output_dir, discovery)


def write_report(
    report_dir: Path,
    details_root_dir: Path,
    run_at: datetime,
    discoveries: list[Discovery],
    query: str,
) -> Path:
    report_path = report_dir / f"{run_at.date().isoformat()}.md"
    details_dir = details_root_dir / run_at.date().isoformat()
    lines = [
        f"# Daily paper report for {run_at.date().isoformat()}",
        "",
        f"- Generated at: {run_at.isoformat()}",
        f"- Query: `{query}`",
        f"- New papers found: {len(discoveries)}",
        "",
    ]

    if not discoveries:
        lines.append("No new papers found in this run.")
    else:
        for index, item in enumerate(discoveries, start=1):
            detail_path = write_paper_detail(details_dir, item)
            lines.extend(
                [
                    f"## {index}. {item.metadata.title}",
                    "",
                    f"- Paper key: `{item.paper.key}`",
                    f"- Paper URL: {item.paper.canonical_url}",
                    f"- Source: {item.source.source_name}",
                    f"- Source time: {item.source.created_at}",
                    f"- Venue: {item.metadata.venue or 'Unknown'}",
                    f"- Ranking score: {item.ranking.score}",
                    f"- Ranking reasons: {', '.join(item.ranking.reasons) or 'None'}",
                    f"- Detail report: {detail_path.name}",
                    "",
                    item.analysis.summary or "No summary available.",
                    "",
                    item.source.text.strip(),
                    "",
                ]
            )

    report_path.write_text("\n".join(lines).strip() + "\n")
    return report_path
