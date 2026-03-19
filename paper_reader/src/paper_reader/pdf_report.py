"""Convert DOCX reports to PDF via LibreOffice headless."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def docx_to_pdf(docx_path: Path) -> Path | None:
    """Convert a DOCX file to PDF using soffice --headless.

    Requires LibreOffice installed (brew install --cask libreoffice).
    """
    pdf_path = docx_path.with_suffix(".pdf")
    try:
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            capture_output=True, timeout=120,
            check=True,
        )
        if pdf_path.exists():
            return pdf_path
    except FileNotFoundError:
        print("Warning: soffice not found. Install LibreOffice: brew install --cask libreoffice", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("Warning: PDF conversion timed out.", file=sys.stderr)
    except subprocess.CalledProcessError as exc:
        print(f"Warning: PDF conversion failed: {exc.stderr.decode()[:200]}", file=sys.stderr)
    return None
