import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from paper_reader.arxiv_client import ArxivClient
from paper_reader.config import AppConfig


SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <updated>2026-03-17T00:00:00Z</updated>
    <published>2026-03-17T00:00:00Z</published>
    <title>World Models for Multimodal Agents</title>
    <summary>This paper studies multimodal world models for physical AI.</summary>
    <author><name>Jane Doe</name></author>
    <link href="http://arxiv.org/abs/2401.12345v1" rel="alternate" type="text/html" />
    <link title="pdf" href="http://arxiv.org/pdf/2401.12345v1" rel="related" type="application/pdf" />
    <arxiv:primary_category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""


class ArxivClientTest(unittest.TestCase):
    def test_parse_entry(self) -> None:
        client = ArxivClient(
            AppConfig(
                arxiv_api_url="https://export.arxiv.org/api/query",
                database_path=Path("data/test.sqlite3"),
                reports_dir=Path("reports"),
                max_results=10,
                lookback_hours=24,
                topic_keywords=["multimodal"],
                arxiv_categories=["cs.LG"],
                top_labs=[],
                prominent_people=[],
                top_conferences=[],
                focus_terms=["world model"],
                analysis_model="claude-sonnet-4-20250514",
                anthropic_api_key_env="ANTHROPIC_API_KEY",
                anthropic_base_url="https://api.anthropic.com/v1",
                anthropic_version="2023-06-01",
                analysis_enabled=False,
                analysis_max_input_chars=1000,
                pdf_max_pages=4,
                pdf_text_char_limit=4000,
                paper_details_dir=Path("reports/papers"),
            )
        )
        root = ET.fromstring(SAMPLE)
        entry = root.find("{http://www.w3.org/2005/Atom}entry")
        assert entry is not None
        record = client._parse_entry(entry)
        self.assertEqual(record.paper.key, "arxiv:2401.12345")
        self.assertEqual(record.paper.canonical_url, "https://arxiv.org/abs/2401.12345")
        self.assertEqual(record.metadata.venue, "cs.LG")
        self.assertIn("world model", record.metadata.signals)
