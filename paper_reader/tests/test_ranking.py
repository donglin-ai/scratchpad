import unittest
from pathlib import Path

from paper_reader.arxiv_client import SourceRecord
from paper_reader.config import AppConfig
from paper_reader.metadata import PaperMetadata
from paper_reader.ranking import rank_paper


class RankingTest(unittest.TestCase):
    def test_rank_rewards_labs_conferences_and_focus_terms(self) -> None:
        config = AppConfig(
            arxiv_api_url="https://export.arxiv.org/api/query",
            database_path=Path("data/test.sqlite3"),
            reports_dir=Path("reports"),
            max_results=10,
            lookback_hours=24,
            topic_keywords=["multimodal"],
            arxiv_categories=["cs.LG"],
            top_labs=["OpenAI"],
            prominent_people=["Andrej Karpathy"],
                top_conferences=["NeurIPS"],
                focus_terms=["world model", "time series"],
                analysis_model="claude-sonnet-4-20250514",
                anthropic_api_key_env="ANTHROPIC_API_KEY",
                anthropic_base_url="https://api.anthropic.com/v1",
                anthropic_version="2023-06-01",
                analysis_enabled=True,
                analysis_max_input_chars=1000,
                pdf_max_pages=4,
                pdf_text_char_limit=4000,
                paper_details_dir=Path("reports/papers"),
        )
        source = SourceRecord(
            source_id="1",
            source_name="OpenAI",
            title="OpenAI paper",
            text="New paper on multimodal world models for time series, accepted at NeurIPS.",
            created_at="2026-03-18T00:00:00Z",
            urls=[],
        )
        metadata = PaperMetadata(
            paper_key="arxiv:1234.56789",
            canonical_url="https://arxiv.org/abs/1234.56789",
            title="A World Model for Multimodal Time Series",
            abstract="We present a multimodal world model.",
            authors=["Andrej Karpathy"],
            venue="NeurIPS",
            published_date="2026-03-01",
            pdf_url="https://arxiv.org/pdf/1234.56789.pdf",
            source_domain="arxiv.org",
            page_excerpt="",
            signals=["world model", "time series"],
        )
        ranked = rank_paper(config, source, metadata)
        self.assertGreaterEqual(ranked.score, 90)
        self.assertTrue(any("top lab" in reason for reason in ranked.reasons))


if __name__ == "__main__":
    unittest.main()
