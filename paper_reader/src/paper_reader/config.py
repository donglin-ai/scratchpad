from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    arxiv_api_url: str
    database_path: Path
    reports_dir: Path
    max_results: int
    lookback_hours: int
    topic_keywords: list[str]
    arxiv_categories: list[str]
    top_labs: list[str]
    prominent_people: list[str]
    top_conferences: list[str]
    focus_terms: list[str]
    analysis_model: str
    anthropic_api_key_env: str
    anthropic_base_url: str
    anthropic_version: str
    analysis_enabled: bool
    analysis_max_input_chars: int
    pdf_max_pages: int
    pdf_text_char_limit: int
    paper_details_dir: Path

    @property
    def anthropic_api_key(self) -> str:
        return os.environ.get(self.anthropic_api_key_env, "").strip()

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.paper_details_dir.mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    raw = tomllib.loads(config_path.read_text()) or {}
    return AppConfig(
        arxiv_api_url=raw.get("arxiv_api_url", "https://export.arxiv.org/api/query").rstrip("/"),
        database_path=Path(raw.get("database_path", "data/paper_reader.sqlite3")),
        reports_dir=Path(raw.get("reports_dir", "reports")),
        max_results=int(raw.get("max_results", 25)),
        lookback_hours=int(raw.get("lookback_hours", 24)),
        topic_keywords=list(raw.get("topic_keywords", [])),
        arxiv_categories=list(raw.get("arxiv_categories", ["cs.AI", "cs.CV", "cs.LG", "cs.RO"])),
        top_labs=list(raw.get("top_labs", [])),
        prominent_people=list(raw.get("prominent_people", [])),
        top_conferences=list(raw.get("top_conferences", [])),
        focus_terms=list(raw.get("focus_terms", [])),
        analysis_model=str(raw.get("analysis_model", "claude-sonnet-4-20250514")),
        anthropic_api_key_env=str(raw.get("anthropic_api_key_env", "ANTHROPIC_API_KEY")),
        anthropic_base_url=str(raw.get("anthropic_base_url", "https://api.anthropic.com/v1")).rstrip("/"),
        anthropic_version=str(raw.get("anthropic_version", "2023-06-01")),
        analysis_enabled=bool(raw.get("analysis_enabled", True)),
        analysis_max_input_chars=int(raw.get("analysis_max_input_chars", 16000)),
        pdf_max_pages=int(raw.get("pdf_max_pages", 8)),
        pdf_text_char_limit=int(raw.get("pdf_text_char_limit", 24000)),
        paper_details_dir=Path(raw.get("paper_details_dir", "reports/papers")),
    )
