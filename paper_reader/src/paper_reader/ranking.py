from __future__ import annotations

import re
from dataclasses import dataclass, field

from paper_reader.arxiv_client import SourceRecord
from paper_reader.config import AppConfig
from paper_reader.metadata import PaperMetadata


# ── Category keywords ────────────────────────────────────────────────────────
# Order matters: first match wins. "fundamental" is intentionally broad to catch
# architecture/training papers that don't fit the applied categories.

_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    # world_model before robotics so "video world model for robots" → world_model
    ("world_model", [
        "world model", "video generation", "video prediction",
        "video diffusion", "4d ", "simulator", "physical ai",
        "dynamics model", "latent dynamics",
    ]),
    ("robotics", [
        "robot", "manipulation", "grasping", "locomotion", "sim-to-real",
        "embodied agent", "policy learning", "imitation learning",
        "dexterous", "navigation", "URDF",
    ]),
    ("multimodal", [
        "multimodal", "vision-language", "vision language",
        "VLM", "MLLM", "image-text", "video understanding",
        "visual question", "document intelligence", "OCR",
    ]),
    ("fundamental", [
        "attention mechanism", "transformer architecture", "gating",
        "activation function", "normalization", "optimizer",
        "training stability", "scaling law", "sparse mixture",
        "mixture of experts", "MoE", "quantization", "distillation",
        "positional encoding", "tokenizer", "token", "efficient inference",
        "KV cache", "speculative decoding", "architecture search",
        "pre-training", "pretraining", "self-supervised",
        "contrastive learning", "representation learning",
        "foundation model", "large language model", "LLM",
        "diffusion model", "flow matching", "rectified flow",
    ]),
]


def classify_paper(combined_text: str) -> str:
    """Classify a paper into a category based on keyword matching."""
    lowered = combined_text.lower()
    for category, keywords in _CATEGORY_PATTERNS:
        for kw in keywords:
            if kw.lower() in lowered:
                return category
    return "other"


@dataclass(slots=True)
class RankedPaper:
    score: int
    reasons: list[str] = field(default_factory=list)
    category: str = "other"


def _match_any(haystack: str, needles: list[str]) -> list[str]:
    lowered = haystack.lower()
    return [needle for needle in needles if needle.lower() in lowered]


def rank_paper(config: AppConfig, source: SourceRecord, metadata: PaperMetadata) -> RankedPaper:
    score = 0
    reasons: list[str] = []
    combined = " ".join(
        [
            source.source_name,
            source.title,
            source.text,
            metadata.title,
            metadata.abstract,
            metadata.venue,
            " ".join(metadata.authors),
            " ".join(metadata.signals),
        ]
    )

    lab_hits = _match_any(combined, config.top_labs)
    if lab_hits:
        score += 35
        reasons.append(f"top lab: {', '.join(lab_hits[:3])}")

    people_hits = _match_any(combined, config.prominent_people)
    if people_hits:
        score += 25
        reasons.append(f"prominent researcher: {', '.join(people_hits[:3])}")

    conference_hits = _match_any(combined, config.top_conferences)
    if conference_hits:
        score += 25
        reasons.append(f"top venue: {', '.join(conference_hits[:3])}")

    focus_hits = _match_any(combined, config.focus_terms)
    if focus_hits:
        score += 8 * min(len(focus_hits), 4)
        reasons.append(f"topic: {', '.join(focus_hits[:4])}")

    # HuggingFace upvotes signal (stored as "hf_upvotes:N" in signals)
    for sig in metadata.signals:
        m = re.match(r"hf_upvotes:(\d+)", sig)
        if m:
            upvotes = int(m.group(1))
            if upvotes >= 60:
                score += 30
                reasons.append(f"HF trending ({upvotes}↑)")
            elif upvotes >= 30:
                score += 20
                reasons.append(f"HF popular ({upvotes}↑)")
            elif upvotes >= 10:
                score += 10
                reasons.append(f"HF notable ({upvotes}↑)")

    if metadata.abstract:
        score += 5
        reasons.append("abstract available")
    if metadata.pdf_url:
        score += 5
        reasons.append("pdf available")
    if metadata.fetch_error:
        score -= 10
        reasons.append("metadata fetch failed")

    category = classify_paper(combined)

    # Derank pure robotics papers — user prefers foundation/multimodal/world model
    if category == "robotics":
        score -= 20
        reasons.append("deranked: robotics")

    return RankedPaper(score=score, reasons=reasons, category=category)


# ── Diversified selection ─────────────────────────────────────────────────────

# Category caps and priority for daily selection.
# Priority order: world_model > multimodal > fundamental > other.
# Robotics excluded (world_model catches robot+world-model papers).
_CATEGORY_PRIORITY = ["world_model", "multimodal", "fundamental", "other"]
_CATEGORY_CAPS: dict[str, int] = {
    "robotics": 0,
    "world_model": 2,
    "multimodal": 2,
    "fundamental": 2,
    "other": 1,
}


def select_diverse_top_n(
    ranked: list[tuple],  # list of (record, score, reasons, category)
    top_n: int = 3,
) -> list[tuple]:
    """Pick top_n papers with priority-based diversity.

    Phase 1 — Reserve: walk categories in priority order (world_model first),
              pick the highest-scored paper from each that has candidates.
              This guarantees the top category gets a slot even if its score
              is slightly lower than another category's best.
    Phase 2 — Fill:    fill remaining slots by global score, respecting caps.
    """
    # Group by category, preserving score order
    by_cat: dict[str, list[tuple]] = {}
    for item in ranked:
        cat = item[3]
        cap = _CATEGORY_CAPS.get(cat, 1)
        if cap <= 0:
            continue
        by_cat.setdefault(cat, []).append(item)

    selected: list[tuple] = []
    selected_keys: set[str] = set()
    category_counts: dict[str, int] = {}

    def _pick(item: tuple) -> bool:
        key = item[0].paper.key if item[0] else id(item)
        if key in selected_keys:
            return False
        cat = item[3]
        cap = _CATEGORY_CAPS.get(cat, 1)
        if category_counts.get(cat, 0) >= cap:
            return False
        selected.append(item)
        selected_keys.add(key)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        return True

    # Phase 1: reserve one slot per priority category
    for cat in _CATEGORY_PRIORITY:
        if len(selected) >= top_n:
            break
        for item in by_cat.get(cat, []):
            if _pick(item):
                break

    # Phase 2: fill remaining by global score
    for item in ranked:
        if len(selected) >= top_n:
            break
        _pick(item)

    return selected
