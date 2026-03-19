import unittest

from paper_reader.main import build_parser


class MainCliTest(unittest.TestCase):
    def test_analyze_paper_command_is_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["analyze-paper", "https://arxiv.org/abs/2401.12345"])
        self.assertEqual(args.command, "analyze-paper")
        self.assertEqual(args.paper_url, "https://arxiv.org/abs/2401.12345")

    def test_check_anthropic_command_is_registered(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["check-anthropic"])
        self.assertEqual(args.command, "check-anthropic")


if __name__ == "__main__":
    unittest.main()
