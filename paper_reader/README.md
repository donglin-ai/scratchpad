# paper-reader

`paper-reader` is a Python CLI that searches arXiv every day for newly posted papers, biases results toward top labs and top venues, extracts paper metadata, and writes ranked Markdown reports plus per-paper deep dives.

## What it does

- Queries the arXiv API on a schedule or as a one-off run.
- Searches by your AI topic keywords and arXiv categories.
- Uses arXiv metadata directly for title, abstract, authors, date, and PDF links.
- Ranks papers using configurable signals for top labs, prominent AI figures, top conferences, and topic-fit terms.
- Optionally calls the Anthropic Messages API to generate structured notes on research questions, key changes, architecture deltas, conclusions, and limitations.
- Stores seen papers in SQLite so daily runs stay deduplicated.
- Writes a daily ranked report to `reports/YYYY-MM-DD.md` and detailed paper notes under `reports/YYYY-MM-DD/`.
- Pulls PDF-derived contribution snippets, equation-like lines, figure captions, and section excerpts when available so each paper note can surface key contributions and stronger technical evidence.

## Quick start

1. Create a virtual environment and install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you prefer Conda, a reviewable environment file is included:

```bash
conda env create -f environment.yml
conda activate paper-reader
pip install -e .
```

For richer paper analysis, the project now uses `pypdf` to extract text from paper PDFs before sending context to Claude.

2. Copy the example config and fill in your Claude API key if you want deep analysis:

```bash
# Uncomment if config.example.toml is preferred
# cp config.example.toml config.toml
export ANTHROPIC_API_KEY="your-claude-api-key"
```

3. `config.toml` is already tuned for multimodal foundation models, world models, physical AI, and time series. Adjust keywords, arXiv categories, labs, people, and conference lists as needed.

4. Run it once:

```bash
paper-reader run --config config.toml
```

5. Or keep it running daily:

```bash
paper-reader daemon --config config.toml --daily-at 09:00
```

6. Analyze one paper on demand:

```bash
paper-reader analyze-paper "https://arxiv.org/abs/2401.12345"
```

7. Check your Anthropic API key and model:

```bash
paper-reader check-anthropic --config config.toml
```

## Configuration

`config.example.toml` documents all supported fields. The most important settings are:

- `topic_keywords`: terms that describe your research area.
- `arxiv_categories`: arXiv subject areas to search alongside your topic keywords.
- `top_labs`, `prominent_people`, `top_conferences`: ranking boosts for source quality.
- `focus_terms`: boosts for world models, physical AI, time series, and related themes.
- `analysis_enabled`, `analysis_model`, `anthropic_api_key_env`: structured paper analysis settings.
- `pdf_max_pages`, `pdf_text_char_limit`: how much PDF text to extract and feed into analysis.
- `paper_details_dir`: where detailed per-paper notes are written.

The paper-analysis step reads `ANTHROPIC_API_KEY` by default. arXiv search itself does not require a token.

## Scheduling

The `daemon` command is a simple built-in scheduler. For production use on a laptop or server, `cron` or `launchd` is usually more reliable. Example cron entry:

```cron
0 9 * * * cd ~/projects/scratchpad/paper_reader && paper-reader run
```

A review-only cron template is included at [deploy/paper_reader.cron](deploy/paper_reader.cron). Nothing is installed automatically. After you review it, you can install it with:

```bash
chmod +x scripts/install_cron.sh
./scripts/install_cron.sh
```

The single-paper CLI writes its output under `reports/papers/manual/`.

## Notes

- This project uses the arXiv API for daily discovery, so no X developer access is required.
- The deep-analysis stage is evidence-bound: it will only describe math or architecture changes when the fetched metadata supports them.
- PDF extraction improves the report substantially; if `pypdf` is unavailable, the tool falls back to metadata-only evidence.
- If `ANTHROPIC_API_KEY` is unset, the tool still runs and writes fallback metadata-only paper notes.
