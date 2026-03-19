import unittest

from paper_reader.metadata import (
    _extract_contribution_snippets,
    _extract_equation_snippets,
    _extract_figure_snippets,
)


SAMPLE_TEXT = """
Introduction
We present a multimodal world model for robotics that improves long-horizon prediction.
Our main contributions are threefold: a new latent dynamics block, a cross-modal alignment loss, and a scalable training recipe.
Method
The objective is L = L_pred + lambda * L_align + beta * L_action.
Figure 2: Architecture overview showing the perception encoder, latent world model, and policy head.
Conclusion
We show better performance on control and forecasting benchmarks.
"""


class MetadataExtractionTest(unittest.TestCase):
    def test_extract_contribution_snippets(self) -> None:
        snippets = _extract_contribution_snippets(SAMPLE_TEXT)
        self.assertTrue(any("Our main contributions are threefold" in item for item in snippets))

    def test_extract_equation_snippets(self) -> None:
        snippets = _extract_equation_snippets(SAMPLE_TEXT)
        self.assertTrue(any("L = L_pred" in item for item in snippets))

    def test_extract_figure_snippets(self) -> None:
        snippets = _extract_figure_snippets(SAMPLE_TEXT)
        self.assertTrue(any("Figure 2" in item for item in snippets))


if __name__ == "__main__":
    unittest.main()
