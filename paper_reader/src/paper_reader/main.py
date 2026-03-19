from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from paper_reader.analysis import analyze_paper
from paper_reader.arxiv_client import ArxivClient, ArxivRecord, SourceRecord
from paper_reader.config import load_config
from paper_reader.hf_client import fetch_hf_daily_papers
from paper_reader.http import HTTPError, URLError, post_json
from paper_reader.metadata import PaperMetadata, fetch_paper_metadata
from paper_reader.papers import PaperLink, parse_paper_link
from paper_reader.ranking import rank_paper, select_diverse_top_n
from paper_reader.pdf_report import write_paper_pdf
from paper_reader.reporting import Discovery, write_daily_summary_pdf
from paper_reader.storage import SeenPaper, Storage


def _direct_input_source(source_text: str, source_name: str) -> SourceRecord:
    return SourceRecord(
        source_id="manual-input",
        source_name=source_name,
        title="Manual paper analysis",
        text=source_text,
        created_at=datetime.now(UTC).isoformat(),
        urls=[],
    )


def analyze_single_paper(
    config_path: str | Path,
    paper_url: str,
    source_text: str = "",
    source_author: str = "manual",
    output_format: str = "docx",
) -> int:
    config = load_config(config_path)
    config.ensure_directories()

    paper = parse_paper_link(paper_url)
    if paper is None:
        paper = PaperLink(key=paper_url, canonical_url=paper_url, host="custom", pdf_url="")

    source = _direct_input_source(source_text or f"Manual analysis request for {paper_url}", source_author)
    metadata = fetch_paper_metadata(paper, config)
    ranking = rank_paper(config, source, metadata)
    analysis = analyze_paper(config, metadata, source, ranking)
    discovery = Discovery(
        paper=paper,
        source=source,
        metadata=metadata,
        ranking=ranking,
        analysis=analysis,
    )

    output_dir = config.paper_details_dir / "manual"
    pdf_path = write_paper_pdf(output_dir, discovery)
    print(f"Wrote paper analysis to {pdf_path}")
    return 0


def check_anthropic(config_path: str | Path, prompt: str = "Reply with OK.") -> int:
    config = load_config(config_path)
    if not config.anthropic_api_key:
        print(
            f"Missing {config.anthropic_api_key_env}. Export your Anthropic API key first.",
            file=sys.stderr,
        )
        return 2

    payload = {
        "model": config.analysis_model,
        "max_tokens": 32,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        response = post_json(
            f"{config.anthropic_base_url}/messages",
            payload,
            headers={
                "x-api-key": config.anthropic_api_key,
                "anthropic-version": config.anthropic_version,
            },
            timeout=60,
        )
    except HTTPError as exc:
        print(f"Anthropic API check failed with HTTP {exc.code}.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, ValueError) as exc:
        print(f"Anthropic API check failed: {exc}", file=sys.stderr)
        return 1

    parts = []
    for item in response.get("content", []):
        if item.get("type") == "text" and item.get("text"):
            parts.append(item["text"].strip())
    text = " ".join(part for part in parts if part).strip()

    print("Anthropic API check passed")
    print(f"Model: {response.get('model', config.analysis_model)}")
    print(f"Stop reason: {response.get('stop_reason', 'unknown')}")
    if text:
        print(f"Response: {text}")
    return 0


def _enrich_record(record: ArxivRecord, config) -> ArxivRecord:
    """Fetch full PDF for a record (needed for Claude vision analysis)."""
    if not record.metadata.pdf_bytes and record.metadata.pdf_url:
        enriched = fetch_paper_metadata(record.paper, config)
        # Merge: keep the richer fields
        meta = record.metadata
        if enriched.pdf_bytes:
            meta.pdf_bytes = enriched.pdf_bytes
        if enriched.full_text_excerpt and not meta.full_text_excerpt:
            meta.full_text_excerpt = enriched.full_text_excerpt
        if enriched.section_snippets and not meta.section_snippets:
            meta.section_snippets = enriched.section_snippets
        if enriched.equation_snippets and not meta.equation_snippets:
            meta.equation_snippets = enriched.equation_snippets
        if enriched.figure_snippets and not meta.figure_snippets:
            meta.figure_snippets = enriched.figure_snippets
        if enriched.contribution_snippets and not meta.contribution_snippets:
            meta.contribution_snippets = enriched.contribution_snippets
    return record


def run_once(config_path: str | Path, top_n: int = 3) -> int:
    """Fetch papers from arXiv + HuggingFace, rank, analyze top N, write DOCX reports."""
    config = load_config(config_path)
    config.ensure_directories()

    storage = Storage(config.database_path)
    try:
        # 1. Gather candidates from both sources
        all_records: list[ArxivRecord] = []

        # arXiv
        client = ArxivClient(config)
        last_run_at = storage.get_last_run_at()
        if last_run_at is None:
            last_run_at = datetime.now(UTC) - timedelta(hours=config.lookback_hours)

        try:
            arxiv_records = client.search(start_time=last_run_at)
            all_records.extend(arxiv_records)
            print(f"arXiv: {len(arxiv_records)} papers")
        except Exception as exc:
            print(f"arXiv fetch failed: {exc}", file=sys.stderr)

        # HuggingFace Daily Papers
        try:
            hf_records = fetch_hf_daily_papers(config)
            all_records.extend(hf_records)
            print(f"HuggingFace: {len(hf_records)} papers")
        except Exception as exc:
            print(f"HuggingFace fetch failed: {exc}", file=sys.stderr)

        # 2. Deduplicate by paper key
        seen_keys: set[str] = set()
        unique_records: list[ArxivRecord] = []
        for record in all_records:
            if record.paper.key in seen_keys:
                continue
            if storage.has_seen_paper(record.paper.key):
                continue
            seen_keys.add(record.paper.key)
            unique_records.append(record)

        print(f"Unique unseen papers: {len(unique_records)}")

        # 3. Rank and classify all candidates (cheap, no API calls)
        ranked: list[tuple[ArxivRecord, int, list[str], str]] = []
        for record in unique_records:
            r = rank_paper(config, record.source, record.metadata)
            ranked.append((record, r.score, r.reasons, r.category))

        ranked.sort(key=lambda x: x[1], reverse=True)

        # 4. Diversified selection: category caps (robotics≤1), prefer variety
        selected = select_diverse_top_n(ranked, top_n=top_n)

        # Show ranking summary
        print(f"\nTop {min(top_n * 3, len(ranked))} candidates (before diversity filter):")
        for record, score, reasons, cat in ranked[:top_n * 3]:
            print(f"  [{score:3d}] [{cat:12s}] {record.metadata.title[:70]}")
            print(f"        {', '.join(reasons[:3])}")

        print(f"\nSelected {len(selected)} papers (diversified):")
        for record, score, reasons, cat in selected:
            print(f"  [{score:3d}] [{cat:12s}] {record.metadata.title[:70]}")

        # 5. Analyze selected papers with Claude (expensive: PDF + LLM)
        discoveries: list[Discovery] = []
        today = datetime.now().strftime("%Y-%m-%d")
        output_dir = config.paper_details_dir / today

        for record, score, reasons, cat in selected:
            print(f"\nAnalyzing: {record.metadata.title[:80]}...")
            record = _enrich_record(record, config)
            ranking = rank_paper(config, record.source, record.metadata)
            analysis = analyze_paper(config, record.metadata, record.source, ranking)
            discovery = Discovery(
                paper=record.paper,
                source=record.source,
                metadata=record.metadata,
                ranking=ranking,
                analysis=analysis,
            )
            discoveries.append(discovery)

            # Write individual PDF report
            pdf_path = write_paper_pdf(output_dir, discovery)
            print(f"  → {pdf_path}")

            # Mark as seen
            storage.mark_paper_seen(
                SeenPaper(
                    key=record.paper.key,
                    paper_url=record.paper.canonical_url,
                    source_id=record.source.source_id,
                    source_name=record.source.source_name,
                    seen_at=datetime.now(UTC).isoformat(),
                )
            )

        # 6. Also write daily summary PDF
        run_at = datetime.now(UTC)
        report_path = write_daily_summary_pdf(
            config.reports_dir,
            run_at,
            discoveries,
            client.build_query(),
        )
        storage.set_last_run_at(run_at)
    finally:
        storage.close()

    print(f"\nWrote summary to {report_path}")
    print(f"Analyzed {len(discoveries)} papers → {output_dir}/")
    return 0


def sleep_until_next_time(daily_at: str) -> None:
    hour_text, minute_text = daily_at.split(":", maxsplit=1)
    hour = int(hour_text)
    minute = int(minute_text)

    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)

    time.sleep((next_run - now).total_seconds())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily paper discovery for ML researchers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Fetch, rank, and analyze top papers")
    run_parser.add_argument("--config", default="config.toml", help="Path to config TOML")
    run_parser.add_argument("--top", type=int, default=3, help="Number of top papers to analyze (default: 3)")

    daemon_parser = subparsers.add_parser("daemon", help="Run daily at a fixed time")
    daemon_parser.add_argument("--config", default="config.toml", help="Path to config TOML")
    daemon_parser.add_argument("--daily-at", default="09:00", help="Local time in HH:MM format")
    daemon_parser.add_argument("--top", type=int, default=3, help="Number of top papers to analyze (default: 3)")

    analyze_parser = subparsers.add_parser("analyze-paper", help="Analyze a single paper URL")
    analyze_parser.add_argument("paper_url", help="Paper URL (arXiv, OpenReview, DOI, etc.)")
    analyze_parser.add_argument("--config", default="config.toml", help="Path to config TOML")
    analyze_parser.add_argument("--source-text", default="", help="Optional source context")
    analyze_parser.add_argument("--source-author", default="manual", help="Source label")
    analyze_parser.add_argument("--format", default="docx", choices=["docx", "md"], dest="output_format")

    check_parser = subparsers.add_parser("check-anthropic", help="Verify the Anthropic API key")
    check_parser.add_argument("--config", default="config.toml", help="Path to config TOML")
    check_parser.add_argument("--prompt", default="Reply with OK.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        return run_once(args.config, top_n=args.top)

    if args.command == "daemon":
        while True:
            sleep_until_next_time(args.daily_at)
            try:
                run_once(args.config, top_n=args.top)
            except Exception as exc:  # noqa: BLE001
                print(f"Run failed: {exc}", file=sys.stderr)
        return 0

    if args.command == "analyze-paper":
        return analyze_single_paper(
            args.config,
            args.paper_url,
            source_text=args.source_text,
            source_author=args.source_author,
            output_format=args.output_format,
        )

    if args.command == "check-anthropic":
        return check_anthropic(args.config, prompt=args.prompt)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
