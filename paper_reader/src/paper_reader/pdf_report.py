"""Convert DOCX reports to PDF for easy browser viewing."""

from __future__ import annotations

from pathlib import Path


def docx_to_pdf(docx_path: Path) -> Path | None:
    """Convert a DOCX file to PDF. Returns the PDF path or None on failure.

    Uses docx2pdf which leverages Microsoft Word (macOS) or LibreOffice.
    """
    pdf_path = docx_path.with_suffix(".pdf")
    try:
        from docx2pdf import convert
        convert(str(docx_path), str(pdf_path))
        return pdf_path
    except Exception as exc:
        # Fallback: try LibreOffice CLI directly
        try:
            import subprocess
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir",
                 str(docx_path.parent), str(docx_path)],
                capture_output=True, timeout=60,
            )
            if pdf_path.exists():
                return pdf_path
        except Exception:
            pass

        import sys
        print(f"Warning: PDF conversion failed ({exc}). Install Microsoft Word or LibreOffice.", file=sys.stderr)
        return None
