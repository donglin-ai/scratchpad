"""Generate concise PDF reports directly from paper analysis — no DOCX intermediate."""

from __future__ import annotations

import re
import tempfile
from io import BytesIO
from pathlib import Path

from fpdf import FPDF

from paper_reader.reporting import Discovery, _slugify


_FIGURE_CAPTION_RE = re.compile(r"Figure\s+(\d+)\s*[:\.]", re.IGNORECASE)


def _latin(text: str) -> str:
    """Make text safe for fpdf2 built-in fonts (latin-1 only)."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Figure extraction ────────────────────────────────────────────────────────

def _extract_figure_cropped(pdf_bytes: bytes, figures: list[dict]) -> dict[str, str]:
    """Extract cropped figure images from PDF. Returns {figure_id: temp_png_path}."""
    try:
        import fitz
    except ImportError:
        return {}

    if not pdf_bytes or not figures:
        return {}

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return {}

    # Build caption page index as fallback
    caption_pages: dict[int, int] = {}
    for pn in range(min(len(doc), 18)):
        for m in _FIGURE_CAPTION_RE.finditer(doc[pn].get_text()):
            fn = int(m.group(1))
            if fn not in caption_pages:
                caption_pages[fn] = pn

    results: dict[str, str] = {}

    for fig in figures:
        fig_id = fig.get("figure_id", "")
        if not fig_id:
            continue

        # Determine page
        page_num = None
        if "page_number" in fig:
            try:
                page_num = int(fig["page_number"])
            except (ValueError, TypeError):
                pass
        if page_num is None:
            m = re.search(r"(\d+)", fig_id)
            if m:
                page_num = caption_pages.get(int(m.group(1)))
        if page_num is None or page_num < 0 or page_num >= len(doc):
            continue

        page = doc[page_num]

        # Find caption text position for cropping
        fig_num_match = re.search(r"(\d+)", fig_id)
        caption_pattern = f"Figure {fig_num_match.group(1)}" if fig_num_match else fig_id
        instances = page.search_for(caption_pattern)

        if instances:
            caption_y = instances[0].y1
            # Find content above caption: images and drawings
            min_y = caption_y  # start at caption, scan upward
            for img_info in page.get_image_info():
                bbox = img_info["bbox"]
                if bbox[3] <= caption_y + 5:  # image above or at caption
                    min_y = min(min_y, bbox[1])
            for d in page.get_drawings():
                if d["rect"].y1 <= caption_y + 5:
                    min_y = min(min_y, d["rect"].y0)

            # Add small margins
            clip_y0 = max(0, min_y - 10)
            clip_y1 = min(page.rect.height, caption_y + 25)
            clip = fitz.Rect(0, clip_y0, page.rect.width, clip_y1)
        else:
            # No caption found — render full page
            clip = page.rect

        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip)
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(pix.tobytes("png"))
            tmp.close()
            results[fig_id] = tmp.name
        except Exception:
            continue

    doc.close()
    return results


# ── Formula rendering ────────────────────────────────────────────────────────

def _render_latex(latex: str) -> str | None:
    """Render a LaTeX formula to a temp PNG file. Returns path or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 0.8))
        ax.text(0.5, 0.5, f"${latex}$", transform=ax.transAxes,
                fontsize=14, ha="center", va="center", math_fontfamily="cm")
        ax.axis("off")
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fig.savefig(tmp.name, format="png", bbox_inches="tight",
                    dpi=150, pad_inches=0.05, facecolor="white")
        plt.close(fig)
        return tmp.name
    except Exception:
        return None


# ── PDF writer ───────────────────────────────────────────────────────────────

def write_paper_pdf(details_dir: Path, discovery: Discovery) -> Path:
    """Generate a concise ~1-page PDF report for a paper."""
    details_dir.mkdir(parents=True, exist_ok=True)

    title_slug = _slugify(discovery.metadata.title or discovery.paper.key)
    if len(title_slug) > 80:
        title_slug = title_slug[:80].rstrip("-")
    pdf_path = details_dir / f"{title_slug}.pdf"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    # Extract figures and formulas
    figure_images = _extract_figure_cropped(
        discovery.metadata.pdf_bytes, discovery.analysis.key_figures,
    )

    # ── Title ────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 5, _latin(discovery.metadata.title), new_x="LMARGIN", new_y="NEXT")

    # Authors + link
    meta_parts = []
    if discovery.metadata.authors:
        authors = ", ".join(discovery.metadata.authors[:6])
        if len(discovery.metadata.authors) > 6:
            authors += " et al."
        meta_parts.append(authors)
    if discovery.metadata.venue:
        meta_parts.append(discovery.metadata.venue)
    if meta_parts:
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 4, _latin(" | ".join(meta_parts)), new_x="LMARGIN", new_y="NEXT")

    url = discovery.metadata.canonical_url or discovery.paper.canonical_url
    if url:
        pdf.set_text_color(5, 99, 193)
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4, url, new_x="LMARGIN", new_y="NEXT", link=url)
    pdf.ln(3)

    # ── Research Questions ───────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, "Research Questions", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for q in discovery.analysis.research_questions:
        pdf.cell(3)
        pdf.multi_cell(0, 4, _latin(f"- {q}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # ── Core Idea ────────────────────────────────────────────────────────
    if discovery.analysis.intuitive_explanation:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, "Core Idea", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        paras = [p.strip() for p in discovery.analysis.intuitive_explanation.split("\n\n") if p.strip()]
        for para in paras[:2]:
            pdf.multi_cell(0, 4, _latin(para), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        pdf.ln(1)

    # ── Key Formula ──────────────────────────────────────────────────────
    if discovery.analysis.key_formulas:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, "Key Formula", new_x="LMARGIN", new_y="NEXT")

        for formula in discovery.analysis.key_formulas[:2]:
            name = formula.get("name", "")
            latex = formula.get("latex", "")
            explanation = formula.get("explanation", "")

            if name:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 4, _latin(name), new_x="LMARGIN", new_y="NEXT")

            if latex:
                img_path = _render_latex(latex)
                if img_path:
                    try:
                        pdf.image(img_path, x=pdf.l_margin + 10, w=min(140, pdf.epw - 20))
                        pdf.ln(2)
                    except Exception:
                        # Fallback: show raw LaTeX
                        pdf.set_font("Courier", "", 8)
                        pdf.multi_cell(0, 4, _latin(latex), new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.set_font("Courier", "", 8)
                    pdf.multi_cell(0, 4, _latin(latex), new_x="LMARGIN", new_y="NEXT")

            if explanation:
                pdf.set_font("Helvetica", "", 8)
                pdf.multi_cell(0, 3.5, _latin(explanation), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

    # ── Key Figure ───────────────────────────────────────────────────────
    if discovery.analysis.key_figures:
        fig = discovery.analysis.key_figures[0]
        fig_id = fig.get("figure_id", "")
        significance = fig.get("significance", "")
        img_path = figure_images.get(fig_id)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, "Key Figure", new_x="LMARGIN", new_y="NEXT")

        if img_path:
            try:
                # Fit to page width with margin
                max_w = pdf.epw - 10
                pdf.image(img_path, x=pdf.l_margin + 5, w=max_w)
                pdf.ln(2)
            except Exception:
                pass

        if significance:
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(60, 60, 60)
            pdf.multi_cell(0, 3.5, _latin(f"{fig_id}: {significance}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # ── Limitations ──────────────────────────────────────────────────────
    if discovery.analysis.solution_limitations:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, "Limitations", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8)
        for item in discovery.analysis.solution_limitations[:4]:
            pdf.cell(3)
            pdf.multi_cell(0, 3.5, _latin(f"- {item}"), new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(pdf_path))

    # Clean up temp files
    for tmp_path in figure_images.values():
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return pdf_path
