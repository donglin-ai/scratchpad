import unittest

from paper_reader.papers import extract_candidate_urls, parse_paper_link


class PapersTest(unittest.TestCase):
    def test_extract_candidate_urls_deduplicates(self) -> None:
        urls = extract_candidate_urls(
            "check https://arxiv.org/abs/2401.12345 and https://arxiv.org/abs/2401.12345",
            ["https://t.co/short", "https://arxiv.org/abs/2401.12345"],
        )
        self.assertEqual(urls, ["https://t.co/short", "https://arxiv.org/abs/2401.12345"])

    def test_parse_arxiv_link(self) -> None:
        paper = parse_paper_link("https://arxiv.org/abs/2401.12345v2")
        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.key, "arxiv:2401.12345")

    def test_parse_openreview_link(self) -> None:
        paper = parse_paper_link("https://openreview.net/forum?id=abc123")
        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.key, "openreview:abc123")


if __name__ == "__main__":
    unittest.main()
