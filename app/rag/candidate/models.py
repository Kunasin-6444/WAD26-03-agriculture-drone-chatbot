from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceType = Literal["knowledge_base", "web_fallback", "caat_portal", "bot_usage", "hybrid", "abstain"]


@dataclass
class EvidenceSelectionResult:
    """Records evidence before and after context relevance scoping."""
    pre_selection: list[dict] = field(default_factory=list)
    post_selection: list[dict] = field(default_factory=list)
    dropped_summaries: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Detailed non-destructive verification breakdown."""
    rendered_text: str = ""
    raw_text: str = ""
    used_source_ids: list[str] = field(default_factory=list)
    passed_citations: bool = True
    unverified_numbers: list[str] = field(default_factory=list)
    dropped_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_aspect: str = ""
    is_not_found: bool = False
    evidence_trace: list[dict] = field(default_factory=list)


@dataclass
class CandidateResponse:
    """Contract-compatible response from candidate RAG pipeline.

    Field compatibility with CragResponse is preserved so evaluation
    and inspection scripts can consume it directly without conversion.
    """
    answer: str
    source_type: SourceType
    grade: str
    grade_reason: str
    timings: dict[str, float] = field(default_factory=dict)
    evidence_trace: list[dict] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    error_code: str = ""

    # Rich candidate metadata
    raw_answer: str = ""
    generation_succeeded: bool = False
    citation_checks_passed: bool = False
    semantic_quality: str = "not_assessed"
    pre_selection_evidence: list[dict] = field(default_factory=list)
    post_selection_evidence: list[dict] = field(default_factory=list)
    dropped_reasons: list[str] = field(default_factory=list)
    missing_aspect: str = ""
