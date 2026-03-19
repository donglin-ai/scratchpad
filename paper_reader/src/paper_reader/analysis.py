from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from io import BytesIO

from paper_reader.arxiv_client import SourceRecord
from paper_reader.config import AppConfig
from paper_reader.http import HTTPError, URLError, post_json
from paper_reader.metadata import PaperMetadata
from paper_reader.ranking import RankedPaper


@dataclass(slots=True)
class PaperAnalysis:
    research_questions: list[str]
    key_contributions: list[str]
    key_changes: list[dict[str, str]]
    math_formula_changes: list[str]
    architecture_before: str
    architecture_after: str
    architecture_before_mermaid: str
    architecture_after_mermaid: str
    key_conclusions: list[str]
    key_limitations: list[str]
    evidence_gaps: list[str]
    summary: str
    # New fields for improved reports
    intuitive_explanation: str = ""
    solution_limitations: list[str] = field(default_factory=list)
    key_formulas: list[dict[str, str]] = field(default_factory=list)
    key_figures: list[dict[str, str]] = field(default_factory=list)
    raw_json: dict = field(default_factory=dict)


def _default_analysis(metadata: PaperMetadata, ranking: RankedPaper) -> PaperAnalysis:
    questions = []
    if metadata.abstract:
        questions.append("Could not extract research questions — LLM analysis was unavailable.")
    else:
        questions.append("Metadata-only fallback: fetch richer paper text to answer precisely.")

    return PaperAnalysis(
        research_questions=questions,
        key_contributions=metadata.contribution_snippets[:5] or ["No reliable contribution bullets extracted from available evidence."],
        key_changes=[
            {
                "change_type": "unknown",
                "summary": "Automatic LLM analysis was unavailable, so only metadata and ranking signals were captured.",
                "before": "Unknown from metadata alone.",
                "after": metadata.abstract[:300] or "Unknown from metadata alone.",
                "evidence": "; ".join(ranking.reasons) or "No additional ranking evidence.",
            }
        ],
        math_formula_changes=[],
        architecture_before="Unknown from metadata alone.",
        architecture_after="Unknown from metadata alone.",
        architecture_before_mermaid="",
        architecture_after_mermaid="",
        key_conclusions=[metadata.abstract[:300] or "No abstract available."],
        key_limitations=["Needs paper text or stronger metadata extraction for faithful technical comparison."],
        evidence_gaps=["LLM analysis skipped or API key missing."],
        summary="Fallback metadata summary only.",
        intuitive_explanation="LLM analysis was unavailable.",
        solution_limitations=["Analysis unavailable — cannot determine solution limitations."],
        key_formulas=[],
        key_figures=[],
        raw_json={},
    )


_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE)
_FENCE_END_PATTERN = re.compile(r"\n?```\s*$")


def _truncate_pdf(pdf_bytes: bytes, max_pages: int = 20, max_bytes: int = 20_000_000) -> bytes:
    """Truncate a PDF to fit within the Claude API limits.

    Strategy:
    1. If small enough, just trim excess pages.
    2. If still too large, re-render pages as images into a new lightweight PDF.
    """
    if not pdf_bytes:
        return pdf_bytes

    try:
        import fitz
    except ImportError:
        return pdf_bytes

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return pdf_bytes

    n_pages = min(len(doc), max_pages)

    # Fast path: trim pages and check size
    if len(doc) > max_pages:
        while len(doc) > max_pages:
            doc.delete_page(-1)
        out = doc.tobytes(deflate=True)
        if len(out) <= max_bytes:
            doc.close()
            return out
        doc.close()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if len(pdf_bytes) <= max_bytes and n_pages == len(doc):
        doc.close()
        return pdf_bytes

    # Slow path: re-render pages as JPEG images into a new compact PDF
    new_doc = fitz.open()
    for i in range(n_pages):
        page = doc[i]
        # Render at 1.5x — readable but not huge
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        img_bytes = pix.tobytes("jpeg")
        # Create new page with same dimensions
        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)

    out = new_doc.tobytes(deflate=True)
    new_doc.close()
    doc.close()
    return out


def _pdf_to_base64(pdf_bytes: bytes) -> str | None:
    """Truncate and encode PDF bytes as base64 for the Claude document API."""
    if not pdf_bytes:
        return None
    pdf_bytes = _truncate_pdf(pdf_bytes)
    return base64.standard_b64encode(pdf_bytes).decode("ascii")


def _extract_output_text(payload: dict) -> str:
    texts: list[str] = []
    for item in payload.get("content", []):
        if item.get("type") == "text" and item.get("text"):
            texts.append(item["text"])
    raw = "\n".join(texts).strip()
    # Strip markdown code fences that models sometimes wrap around JSON
    raw = _JSON_FENCE_PATTERN.sub("", raw)
    raw = _FENCE_END_PATTERN.sub("", raw)
    return raw.strip()


def analyze_paper(
    config: AppConfig,
    metadata: PaperMetadata,
    source: SourceRecord,
    ranking: RankedPaper,
) -> PaperAnalysis:
    if not config.analysis_enabled or not config.anthropic_api_key:
        return _default_analysis(metadata, ranking)

    context = {
        "title": metadata.title,
        "abstract": metadata.abstract,
        "authors": metadata.authors,
        "venue": metadata.venue,
        "published_date": metadata.published_date,
        "paper_url": metadata.canonical_url,
        "pdf_url": metadata.pdf_url,
        "source_name": source.source_name,
        "source_title": source.title,
        "source_text": source.text,
        "ranking_reasons": ranking.reasons,
        "page_excerpt": metadata.page_excerpt[: config.analysis_max_input_chars],
        "full_text_excerpt": metadata.full_text_excerpt[: config.analysis_max_input_chars],
        "section_snippets": metadata.section_snippets,
        "equation_snippets": metadata.equation_snippets,
        "figure_snippets": metadata.figure_snippets,
        "contribution_snippets": metadata.contribution_snippets,
    }
    prompt_text = (
        "Analyze this paper for an experienced ML researcher. Return strict JSON with ONLY these keys:\n\n"
        "1. **research_questions** (list[str]): 2-3 specific questions THIS paper addresses.\n\n"
        "2. **intuitive_explanation** (str): 1-2 short paragraphs: core problem, key insight/trick, "
        "why it works. Skip standard background.\n\n"
        "3. **key_contributions** (list[str]): 3-5 concise contributions.\n\n"
        "4. **key_formulas** (list[object]): 1-2 formulas NOVEL to this paper only. "
        "Skip standard formulas (attention, softmax, CE, SGD) unless modified. "
        "Each: 'latex' (LaTeX), 'name' (short label), "
        "'explanation' (what each variable means, what it computes, why it matters). "
        "Empty list if no novel formulas.\n\n"
        "5. **key_figures** (list[object]): The single most informative figure from the PDF pages. "
        "Skip logos and generic diagrams. "
        "'figure_id' (e.g. 'Figure 2'), 'page_number' (0-indexed PDF page), "
        "'significance' (1 sentence why it matters). Return exactly 1.\n\n"
        "6. **solution_limitations** (list[str]): 3-4 specific limitations.\n\n"
        "7. **key_conclusions** (list[str]): 3-4 conclusions with quantitative results.\n\n"
        "8. **summary** (str): One-paragraph summary.\n\n"
        "Be terse. No filler.\n\n"
    )

    # Build multimodal message: send PDF directly + text context
    pdf_b64 = _pdf_to_base64(metadata.pdf_bytes)
    content_blocks: list[dict] = []

    if pdf_b64:
        content_blocks.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
        })

    content_blocks.append({
        "type": "text",
        "text": prompt_text + json.dumps(context, ensure_ascii=True),
    })

    payload = {
        "model": config.analysis_model,
        "system": (
            "You are a rigorous AI paper analyst writing for experienced ML researchers. "
            "Be concise — no background explanations of standard concepts. "
            "Return JSON only. Use only the supplied evidence. "
            "If a formula, architecture delta, or limitation is not supported by the evidence, say so explicitly instead of guessing."
        ),
        "messages": [{"role": "user", "content": content_blocks}],
        "max_tokens": 4096,
    }
    try:
        response = post_json(
            f"{config.anthropic_base_url}/messages",
            payload,
            headers={
                "x-api-key": config.anthropic_api_key,
                "anthropic-version": config.anthropic_version,
                "anthropic-beta": "pdfs-2024-09-25",
            },
            timeout=300,
        )
    except (HTTPError, URLError, TimeoutError, ValueError):
        return _default_analysis(metadata, ranking)
    raw_text = _extract_output_text(response)
    if not raw_text:
        return _default_analysis(metadata, ranking)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return _default_analysis(metadata, ranking)

    return PaperAnalysis(
        research_questions=list(parsed.get("research_questions", [])),
        key_contributions=list(parsed.get("key_contributions", [])),
        key_changes=list(parsed.get("key_changes", [])),
        math_formula_changes=list(parsed.get("math_formula_changes", [])),
        architecture_before=str(parsed.get("architecture_before", "")),
        architecture_after=str(parsed.get("architecture_after", "")),
        architecture_before_mermaid=str(parsed.get("architecture_before_mermaid", "")),
        architecture_after_mermaid=str(parsed.get("architecture_after_mermaid", "")),
        key_conclusions=list(parsed.get("key_conclusions", [])),
        key_limitations=list(parsed.get("key_limitations", parsed.get("solution_limitations", []))),
        evidence_gaps=list(parsed.get("evidence_gaps", [])),
        summary=str(parsed.get("summary", "")),
        intuitive_explanation=str(parsed.get("intuitive_explanation", "")),
        solution_limitations=list(parsed.get("solution_limitations", [])),
        key_formulas=list(parsed.get("key_formulas", [])),
        key_figures=list(parsed.get("key_figures", [])),
        raw_json=parsed,
    )
