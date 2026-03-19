"""Generate concise PDF reports directly from paper analysis — no DOCX intermediate."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fpdf import FPDF

from paper_reader.reporting import Discovery, _slugify


_FIGURE_CAPTION_RE = re.compile(r"Figure\s+(\d+)\s*[:\.]", re.IGNORECASE)


def _get_dejavu_fonts() -> dict[str, str]:
    """Return paths to DejaVu Sans fonts bundled with matplotlib."""
    try:
        import matplotlib
        font_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        return {
            "regular": str(font_dir / "DejaVuSans.ttf"),
            "bold": str(font_dir / "DejaVuSans-Bold.ttf"),
            "italic": str(font_dir / "DejaVuSans-Oblique.ttf"),
            "mono": str(font_dir / "DejaVuSansMono.ttf"),
        }
    except Exception:
        return {}


def _make_pdf() -> FPDF:
    """Create an FPDF instance with Unicode font support."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)

    fonts = _get_dejavu_fonts()
    if fonts:
        pdf.add_font("DejaVu", "", fonts["regular"])
        pdf.add_font("DejaVu", "B", fonts["bold"])
        pdf.add_font("DejaVu", "I", fonts["italic"])
        pdf.add_font("Mono", "", fonts["mono"])
        pdf.set_font("DejaVu", "", 10)
    else:
        pdf.set_font("Helvetica", "", 10)

    return pdf


def _font(pdf: FPDF, style: str = "", size: int = 10) -> None:
    """Set font — use DejaVu if available, else Helvetica."""
    try:
        pdf.set_font("DejaVu", style, size)
    except Exception:
        pdf.set_font("Helvetica", style, size)


def _mono_font(pdf: FPDF, size: int = 8) -> None:
    try:
        pdf.set_font("Mono", "", size)
    except Exception:
        pdf.set_font("Courier", "", size)


# ── Figure extraction ────────────────────────────────────────────────────────

def _find_caption_end(page, fig_num: int) -> float | None:
    """Find the bottom y-coordinate of the full caption text for a figure."""
    import fitz

    blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
    caption_start_y = None
    caption_end_y = None

    for b in sorted(blocks, key=lambda x: x[1]):
        text = b[4] if len(b) > 4 else ""
        if caption_start_y is None:
            # Look for the block containing "Figure N"
            if re.search(rf"Figure\s+{fig_num}\b", text, re.IGNORECASE):
                caption_start_y = b[1]
                caption_end_y = b[3]
        elif caption_start_y is not None:
            # Caption may span multiple blocks if it wraps — include if close
            if b[1] - caption_end_y < 5:  # continuation of caption
                caption_end_y = b[3]
            else:
                break

    return caption_end_y


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
        fig_num_match = re.search(r"(\d+)", fig_id)
        fig_num = int(fig_num_match.group(1)) if fig_num_match else 0

        # Find full caption extent (including wrapped lines)
        caption_bottom = _find_caption_end(page, fig_num)

        if caption_bottom is not None:
            # Find content above caption: images and drawings
            min_y = caption_bottom
            for img_info in page.get_image_info():
                bbox = img_info["bbox"]
                if bbox[3] <= caption_bottom + 5:
                    min_y = min(min_y, bbox[1])
            for d in page.get_drawings():
                if d["rect"].y1 <= caption_bottom + 5:
                    min_y = min(min_y, d["rect"].y0)

            clip_y0 = max(0, min_y - 10)
            clip_y1 = min(page.rect.height, caption_bottom + 5)
            clip = fitz.Rect(0, clip_y0, page.rect.width, clip_y1)
        else:
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

    pdf = _make_pdf()
    pdf.add_page()

    # Extract figures
    figure_images = _extract_figure_cropped(
        discovery.metadata.pdf_bytes, discovery.analysis.key_figures,
    )

    # ── Title ────────────────────────────────────────────────────────────
    _font(pdf, "B", 13)
    pdf.multi_cell(0, 5, discovery.metadata.title, new_x="LMARGIN", new_y="NEXT")

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
        _font(pdf, "", 7)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 4, " | ".join(meta_parts), new_x="LMARGIN", new_y="NEXT")

    url = discovery.metadata.canonical_url or discovery.paper.canonical_url
    if url:
        pdf.set_text_color(5, 99, 193)
        _font(pdf, "", 7)
        pdf.cell(0, 4, url, new_x="LMARGIN", new_y="NEXT", link=url)
    pdf.ln(3)

    # ── Research Questions ───────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    _font(pdf, "B", 10)
    pdf.cell(0, 5, "Research Questions", new_x="LMARGIN", new_y="NEXT")
    _font(pdf, "", 9)
    for q in discovery.analysis.research_questions:
        pdf.cell(3)
        pdf.multi_cell(0, 4, f"\u2022 {q}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # ── Core Idea ────────────────────────────────────────────────────────
    if discovery.analysis.intuitive_explanation:
        _font(pdf, "B", 10)
        pdf.cell(0, 5, "Core Idea", new_x="LMARGIN", new_y="NEXT")
        _font(pdf, "", 9)
        paras = [p.strip() for p in discovery.analysis.intuitive_explanation.split("\n\n") if p.strip()]
        for para in paras[:2]:
            pdf.multi_cell(0, 4, para, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        pdf.ln(1)

    # ── Key Formula ──────────────────────────────────────────────────────
    if discovery.analysis.key_formulas:
        _font(pdf, "B", 10)
        pdf.cell(0, 5, "Key Formula", new_x="LMARGIN", new_y="NEXT")

        for formula in discovery.analysis.key_formulas[:2]:
            name = formula.get("name", "")
            latex = formula.get("latex", "")
            explanation = formula.get("explanation", "")

            if name:
                _font(pdf, "B", 9)
                pdf.cell(0, 4, name, new_x="LMARGIN", new_y="NEXT")

            if latex:
                img_path = _render_latex(latex)
                if img_path:
                    try:
                        pdf.image(img_path, x=pdf.l_margin + 10, w=min(140, pdf.epw - 20))
                        pdf.ln(2)
                    except Exception:
                        _mono_font(pdf, 8)
                        pdf.multi_cell(0, 4, latex, new_x="LMARGIN", new_y="NEXT")
                else:
                    _mono_font(pdf, 8)
                    pdf.multi_cell(0, 4, latex, new_x="LMARGIN", new_y="NEXT")

            if explanation:
                _font(pdf, "", 8)
                pdf.multi_cell(0, 3.5, explanation, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

    # ── Key Figure ───────────────────────────────────────────────────────
    if discovery.analysis.key_figures:
        fig = discovery.analysis.key_figures[0]
        fig_id = fig.get("figure_id", "")
        significance = fig.get("significance", "")
        img_path = figure_images.get(fig_id)

        _font(pdf, "B", 10)
        pdf.cell(0, 5, "Key Figure", new_x="LMARGIN", new_y="NEXT")

        if img_path:
            try:
                max_w = pdf.epw - 10
                pdf.image(img_path, x=pdf.l_margin + 5, w=max_w)
                pdf.ln(2)
            except Exception:
                pass

        if significance:
            _font(pdf, "I", 8)
            pdf.set_text_color(60, 60, 60)
            pdf.multi_cell(0, 3.5, f"{fig_id}: {significance}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

    # ── Limitations ──────────────────────────────────────────────────────
    if discovery.analysis.solution_limitations:
        _font(pdf, "B", 10)
        pdf.cell(0, 5, "Limitations", new_x="LMARGIN", new_y="NEXT")
        _font(pdf, "", 8)
        for item in discovery.analysis.solution_limitations[:4]:
            pdf.cell(3)
            pdf.multi_cell(0, 3.5, f"\u2022 {item}", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(pdf_path))

    # Clean up temp files
    for tmp_path in figure_images.values():
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return pdf_path
