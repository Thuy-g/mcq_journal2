#!/usr/bin/env python3
############################################################################
# scripts/run_category_selector_v6.py
#
# Command-line driver for the v6 automatic candidate-source class selector
# (src/category_extractor_v6.py).
#
# THREE WAYS TO RUN IT
#   --answer-uri URI                 one Answer, full ranking printed
#   --input FILE  --alpha A          a batch at one alpha
#   --input FILE  --alphas A,B,C     a batch swept over several alphas
#
# WHAT THIS SCRIPT DECIDES AND WHAT IT DOES NOT
#   It decides which Answers are asked, in what order, and where the evidence is
#   written. It adds no threshold, no ranking rule and no class policy of its
#   own: every scientific decision belongs to category_extractor_v6.
#
# WHY THE SWEEP CANNOT COST SIX TIMES THE TRAFFIC
#   Features are extracted once per Answer and the six rankings are recomputed
#   from those frozen numbers. That is an efficiency property AND a scientific
#   one: six rankings over identical observations are comparable, six
#   independently refetched rankings are not.
#
# WHY COHORT LABELS NEVER REACH THE RANKER
#   Answers.txt groups Answers under "#COHORT:" headers. Those labels are
#   EVALUATION metadata — they say which experimental group a result belongs to.
#   Feeding one into the ranking would make the selector non-generic: it would
#   score an arbitrary DBpedia Answer differently depending on which list a human
#   happened to paste it into, and any resulting "the ranker prefers Nobel
#   categories" finding would be an artefact of the input file. The cohort is
#   carried through to the output rows and is never passed to
#   extract_answer_features().
#
# NETWORK GATE
#   No live client, no model load and no Wikipedia request exists until
#   --allow-network is given. Without it the run either serves everything from
#   cache or refuses, and says which.
#
# IMPORT-TIME PURITY: no file is created, no model loaded, no query issued
# until main() or a function is called.
############################################################################

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from category_extractor_v6 import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_CACHE_PATH,
    DEFAULT_ENDPOINT,
    DEFAULT_SBERT_MODEL,
    DEFAULT_WIKIPEDIA_CACHE_PATH,
    SCHEMA_VERSION as SELECTOR_SCHEMA_VERSION,
    SWEEP_ALPHAS,
    AnswerFeatures,
    AnswerRanking,
    IdfUniverse,
    SbertEncoder,
    SemanticSource,
    SemanticStatus,
    SparqlRunner,
    UNIVERSE_EXPLICIT,
    count_sentences,
    extract_answer_features,
    is_safe_uri,
    iso_utc,
    load_r1_leakage_policy,
    make_dbpedia_runner,
    rank_feasible_classes,
    resolve_idf_universe,
    validate_alpha,
)
from classes.wikipedia_lead import (  # noqa: E402
    DEFAULT_USER_AGENT,
    LeadStatus,
    RequestsWikipediaTransport,
    WikipediaLeadCache,
    WikipediaLeadClient,
)

__all__ = [
    "RUNNER_SCHEMA_VERSION",
    "AnswerRow",
    "ParsedAnswers",
    "parse_answers_file",
    "parse_alpha_list",
    "spearman_rho",
    "build_parser",
    "main",
]

RUNNER_SCHEMA_VERSION = "category_runner_v6.0"

ANSWER_URI_PREFIX = "http://dbpedia.org/resource/"
COHORT_MARKER = "#COHORT:"
COMMENT_MARKER = "#COMMENT:"

DEFAULT_PILOT_POLICY = REPO_ROOT / "data" / "pilot_class_policy_v1.json"
DEFAULT_INPUT = REPO_ROOT / "data" / "Answers.txt"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NETWORK_DENIED = 3
EXIT_NO_IDF_UNIVERSE = 4
EXIT_OUTPUT_EXISTS = 5


# ---------------------------------------------------------------------------
# 1) Answers.txt — the input grammar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerRow:
    """One Answer occurrence in the input file, with where it came from.

    ``uri_is_valid`` is a SECOND, independent judgement from the grammar. The
    grammar of §N classifies any line starting with the DBpedia resource prefix
    as an Answer row, and that classification is preserved exactly so the row
    counts are reproducible. But a row can satisfy the grammar and still not be
    a syntactically valid IRI — data/Answers.txt line 182 is
    ``...Magnesium_oxide"`` with a stray double quote — and such a row cannot be
    interpolated into a SPARQL query. It is reported, excluded from the run, and
    never silently dropped.
    """

    line_number: int
    answer_uri: str
    cohort: Optional[str]
    cohort_raw: Optional[str]
    is_duplicate: bool
    uri_is_valid: bool = True


@dataclass
class ParsedAnswers:
    """The complete, auditable result of reading one Answers.txt.

    ``unique_uris`` preserves FIRST-OCCURRENCE order: the first occurrence wins
    for the automatic run. ``rows`` keeps EVERY occurrence, so cross-cohort
    duplicate provenance survives — 14 of this file's duplicates are the same
    classical figures listed under both "HISTORY/ETHICS" and "ETHICS/CLASSICS",
    and silently dropping the second occurrence would erase the fact that those
    Answers belong to two experimental groups.
    """

    path: str
    rows: list[AnswerRow] = field(default_factory=list)
    unique_uris: list[str] = field(default_factory=list)
    cohorts_by_uri: dict[str, list[str]] = field(default_factory=dict)
    cohort_order: list[str] = field(default_factory=list)
    comment_lines: int = 0
    blank_lines: int = 0
    other_comment_lines: list[tuple[int, str]] = field(default_factory=list)
    malformed_rows: list[tuple[int, str]] = field(default_factory=list)
    invalid_uri_rows: list[tuple[int, str]] = field(default_factory=list)
    total_lines: int = 0

    @property
    def answer_row_count(self) -> int:
        return len(self.rows)

    @property
    def duplicate_row_count(self) -> int:
        return sum(1 for row in self.rows if row.is_duplicate)

    @property
    def input_problem_count(self) -> int:
        return len(self.malformed_rows) + len(self.invalid_uri_rows)

    def audit(self) -> dict[str, Any]:
        return {
            "input_path": self.path,
            "total_lines": self.total_lines,
            # Counted under the §N grammar exactly as specified: any line
            # starting with the DBpedia resource prefix is an Answer row.
            "answer_uri_rows": self.answer_row_count,
            "unique_answer_uris": len(
                {r.answer_uri for r in self.rows}),
            "duplicate_answer_rows": self.duplicate_row_count,
            # A second, independent judgement: how many of those rows can
            # actually be queried.
            "runnable_unique_answer_uris": len(self.unique_uris),
            "invalid_uri_rows": [
                {"line_number": n, "text": t} for n, t in self.invalid_uri_rows],
            "cohort_header_lines": len(self.cohort_order),
            "cohort_labels": list(self.cohort_order),
            "comment_lines": self.comment_lines,
            "other_comment_lines": len(self.other_comment_lines),
            "blank_lines": self.blank_lines,
            "malformed_rows": [
                {"line_number": n, "text": t} for n, t in self.malformed_rows],
        }


def parse_answers_file(path: str | os.PathLike[str]) -> ParsedAnswers:
    """Read Answers.txt under the grammar of Prompt §N.

    Every line falls into exactly one of six buckets and each bucket is counted,
    so the audit adds up: a row is never silently dropped. In particular a
    malformed non-comment, non-blank row becomes a reported INPUT ERROR rather
    than disappearing — a corpus whose denominator quietly shrinks makes every
    coverage percentage computed from it wrong.
    """
    target = Path(path)
    parsed = ParsedAnswers(path=str(target))
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    parsed.total_lines = len(lines)

    current_cohort: Optional[str] = None
    current_cohort_raw: Optional[str] = None
    seen: set[str] = set()

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            parsed.blank_lines += 1
            continue
        if stripped.startswith(COHORT_MARKER):
            raw = stripped[len(COHORT_MARKER):].strip()
            # One trailing ':' is decoration in this file ("CHEMISTRY: ACIDS:").
            label = raw[:-1].strip() if raw.endswith(":") else raw
            current_cohort, current_cohort_raw = (label or None), (raw or None)
            if label and label not in parsed.cohort_order:
                parsed.cohort_order.append(label)
            parsed.comment_lines += 1
            continue
        if stripped.startswith(COMMENT_MARKER):
            # A commented-out Answer is NOT an Answer, even though it contains a
            # URI. This is how the file records entities deliberately excluded.
            parsed.comment_lines += 1
            continue
        if stripped.startswith(ANSWER_URI_PREFIX):
            is_duplicate = stripped in seen
            valid = is_safe_uri(stripped)
            parsed.rows.append(AnswerRow(
                line_number=number, answer_uri=stripped, cohort=current_cohort,
                cohort_raw=current_cohort_raw, is_duplicate=is_duplicate,
                uri_is_valid=valid))
            if not valid:
                # Satisfies the grammar but cannot be interpolated into a SPARQL
                # query. Recorded, excluded from the run, never silently dropped.
                parsed.invalid_uri_rows.append((number, stripped))
            elif not is_duplicate:
                parsed.unique_uris.append(stripped)
            seen.add(stripped)
            memberships = parsed.cohorts_by_uri.setdefault(stripped, [])
            if current_cohort and current_cohort not in memberships:
                memberships.append(current_cohort)
            continue
        if stripped.startswith("#"):
            parsed.other_comment_lines.append((number, stripped))
            parsed.comment_lines += 1
            continue
        parsed.malformed_rows.append((number, stripped))

    return parsed


def parse_alpha_list(text: str) -> list[float]:
    """Parse ``--alphas 0,0.25,0.5``. Every value is validated; order preserved."""
    values: list[float] = []
    for token in str(text).split(","):
        token = token.strip()
        if not token:
            continue
        values.append(validate_alpha(float(token)))
    if not values:
        raise ValueError("--alphas needs at least one value")
    return values


# ---------------------------------------------------------------------------
# 2) Small deterministic helpers
# ---------------------------------------------------------------------------


def sha256_file(path: str | os.PathLike[str]) -> Optional[str]:
    target = Path(path)
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def spearman_rho(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """Spearman rank correlation between two rank vectors over the same items.

    Both alphas rank exactly the same feasible set, so the vectors are a genuine
    permutation comparison and no tie-handling beyond average ranks is needed.
    Returns ``None`` for fewer than two items, where correlation is undefined
    rather than 1.0 — reporting a perfect correlation for a single-class Answer
    would inflate the stability tables with meaningless certainty.
    """
    n = len(a)
    if n != len(b) or n < 2:
        return None
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = sum((x - mean_a) ** 2 for x in a)
    den_b = sum((y - mean_b) ** 2 for y in b)
    if den_a <= 0 or den_b <= 0:
        return None
    return num / ((den_a ** 0.5) * (den_b ** 0.5))


def _csv_text(columns: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> str:
    """Render CSV deterministically: fixed columns, LF endings, no locale."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns),
                            lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _cell(row.get(c)) for c in columns})
    return buffer.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        # Fixed precision so the same computation writes the same bytes on
        # every replay, which is what makes byte-identical replay checkable.
        return f"{value:.10f}"
    if isinstance(value, (list, tuple)):
        return "|".join(str(v) for v in value)
    return str(value)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return path


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True,
                             text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


# ---------------------------------------------------------------------------
# 3) Output row builders — one place per artifact
# ---------------------------------------------------------------------------

RANKING_COLUMNS = [
    "cohort", "answer_uri", "answer_display_label", "alpha", "scoring_mode",
    "semantic_source", "semantic_status", "wikipedia_title",
    "wikipedia_revision_id", "category_uri", "category_label", "feasible_rank",
    "remote_count", "eligible_remote_count", "raw_idf", "normalized_idf",
    "raw_sbert", "normalized_sbert", "combined_score", "leak_level",
    "leak_source", "leak_evidence",
]

REJECTED_COLUMNS = [
    "cohort", "answer_uri", "answer_display_label", "category_uri",
    "category_label", "rejected_code", "rejected_reason", "remote_count",
    "eligible_remote_count", "leak_level", "leak_source", "leak_evidence",
]

SUMMARY_COLUMNS = [
    "cohort", "answer_uri", "answer_display_label", "status", "alpha",
    "scoring_mode", "semantic_source", "semantic_status", "wikipedia_title",
    "wikipedia_revision_id", "categories_discovered", "categories_truncated",
    "feasible_count", "rejected_count", "top_ranked_class",
    "top_ranked_class_label", "top_ranked_combined_score", "idf_universe_n",
    "idf_universe_definition", "sparql_queries", "error",
]

COVERAGE_COLUMNS = [
    "cohort", "answer_uri", "answer_display_label", "dbpedia_categories_found",
    "dbpedia_description_available", "dbpedia_description_characters",
    "dbpedia_description_sentences", "wikipedia_page_resolved",
    "wikipedia_lead_available", "wikipedia_lead_status", "wikipedia_title",
    "wikipedia_page_id", "wikipedia_revision_id", "wikipedia_redirected_from",
    "wikipedia_lead_characters", "wikipedia_lead_sentences",
    "wikipedia_lead_sha256", "semantic_source_used", "semantic_status_used",
    "sbert_encoding_succeeded",
]


def _ranking_rows(ranking: AnswerRanking, cohort: Optional[str]) -> list[dict[str, Any]]:
    semantic = ranking.features.semantic
    rows = []
    for entry in ranking.ranked:
        feature = entry.feature
        rows.append({
            "cohort": cohort,
            "answer_uri": ranking.answer_uri,
            "answer_display_label": ranking.answer_label,
            "alpha": ranking.alpha,
            "scoring_mode": ranking.scoring_mode.value,
            "semantic_source": semantic.source.value if semantic else None,
            "semantic_status": semantic.status.value if semantic else None,
            "wikipedia_title": semantic.wikipedia_title if semantic else None,
            "wikipedia_revision_id": semantic.wikipedia_revision_id if semantic else None,
            "category_uri": feature.category_uri,
            "category_label": feature.category_label,
            "feasible_rank": entry.feasible_rank,
            "remote_count": feature.remote_count,
            "eligible_remote_count": feature.eligible_remote_count,
            "raw_idf": feature.raw_idf,
            "normalized_idf": entry.normalized_idf,
            "raw_sbert": feature.raw_sbert,
            "normalized_sbert": entry.normalized_sbert,
            "combined_score": entry.combined_score,
            "leak_level": feature.leak_level.value,
            "leak_source": feature.leak_source,
            "leak_evidence": feature.leak_evidence,
        })
    return rows


def _rejected_rows(features: AnswerFeatures, cohort: Optional[str]) -> list[dict[str, Any]]:
    """Rejected classes, WITHOUT a feasible rank.

    There is deliberately no rank column here. A rejected class did not go
    through the ranking policy, so any number in a rank column would be a
    fabricated position that a reader sorting the file could act on.
    """
    return [{
        "cohort": cohort,
        "answer_uri": features.answer_uri,
        "answer_display_label": features.answer_label,
        "category_uri": c.category_uri,
        "category_label": c.category_label,
        "rejected_code": c.rejected_code,
        "rejected_reason": c.rejected_reason,
        "remote_count": c.remote_count,
        "eligible_remote_count": c.eligible_remote_count,
        "leak_level": c.leak_level.value,
        "leak_source": c.leak_source,
        "leak_evidence": c.leak_evidence,
    } for c in features.rejected_classes]


def _summary_row(ranking: AnswerRanking, cohort: Optional[str]) -> dict[str, Any]:
    features = ranking.features
    semantic = features.semantic
    universe = features.idf_universe
    top = ranking.ranked[0] if ranking.ranked else None
    return {
        "cohort": cohort,
        "answer_uri": features.answer_uri,
        "answer_display_label": features.answer_label,
        "status": features.status,
        "alpha": ranking.alpha,
        "scoring_mode": ranking.scoring_mode.value,
        "semantic_source": semantic.source.value if semantic else None,
        "semantic_status": semantic.status.value if semantic else None,
        "wikipedia_title": semantic.wikipedia_title if semantic else None,
        "wikipedia_revision_id": semantic.wikipedia_revision_id if semantic else None,
        "categories_discovered": features.categories_discovered,
        "categories_truncated": features.categories_truncated,
        "feasible_count": len(features.feasible_classes),
        "rejected_count": len(features.rejected_classes),
        "top_ranked_class": top.category_uri if top else None,
        "top_ranked_class_label": top.feature.category_label if top else None,
        "top_ranked_combined_score": top.combined_score if top else None,
        "idf_universe_n": universe.total_entities if universe else None,
        "idf_universe_definition": universe.definition if universe else None,
        "sparql_queries": features.sparql_queries,
        "error": features.error,
    }


def _coverage_row(features: AnswerFeatures, cohort: Optional[str],
                  lead: Optional[Any]) -> dict[str, Any]:
    """One census row per Answer. Denominators stay honest because EVERY Answer
    gets a row, including those with no Wikipedia page and those whose request
    failed — the two are distinguished by ``wikipedia_lead_status``."""
    semantic = features.semantic
    description = (features.dbpedia_description or "").strip()
    return {
        "cohort": cohort,
        "answer_uri": features.answer_uri,
        "answer_display_label": features.answer_label,
        "dbpedia_categories_found": features.categories_discovered,
        "dbpedia_description_available": bool(description),
        "dbpedia_description_characters": len(description),
        "dbpedia_description_sentences": count_sentences(description),
        "wikipedia_page_resolved": bool(lead is not None and lead.page_id is not None),
        "wikipedia_lead_available": bool(lead is not None and lead.available),
        "wikipedia_lead_status": lead.status.value if lead is not None else "not_requested",
        "wikipedia_title": lead.canonical_title if lead is not None else None,
        "wikipedia_page_id": lead.page_id if lead is not None else None,
        "wikipedia_revision_id": lead.revision_id if lead is not None else None,
        "wikipedia_redirected_from": lead.redirected_from if lead is not None else None,
        "wikipedia_lead_characters": lead.character_length if lead is not None else 0,
        "wikipedia_lead_sentences": lead.sentence_count if lead is not None else 0,
        "wikipedia_lead_sha256": lead.lead_sha256 if lead is not None else None,
        "semantic_source_used": semantic.source.value if semantic else None,
        "semantic_status_used": semantic.status.value if semantic else None,
        "sbert_encoding_succeeded": bool(features.encoder_metadata.get("available")),
    }


# ---------------------------------------------------------------------------
# 4) Terminal report for a single Answer
# ---------------------------------------------------------------------------


def format_single_answer_report(ranking: AnswerRanking, cohort: Optional[str] = None) -> str:
    """The COMPLETE feasible ranking, never a top-5 excerpt.

    Truncating the printed ranking is what makes an operator believe a class was
    not considered when it was merely below the fold.
    """
    features = ranking.features
    semantic = features.semantic
    universe = features.idf_universe
    out: list[str] = []
    add = out.append

    add("=" * 100)
    add(f"Answer URI            : {features.answer_uri}")
    add(f"Answer display label  : {features.answer_label}")
    if cohort:
        add(f"Cohort (metadata only): {cohort}")
    add(f"Selector schema       : {SELECTOR_SCHEMA_VERSION}")
    add(f"Semantic text source  : {semantic.source.value if semantic else 'none'}")
    add(f"Semantic text status  : {semantic.status.value if semantic else 'none'}")
    if semantic and semantic.source is SemanticSource.WIKIPEDIA_LEAD:
        add(f"Wikipedia title       : {semantic.wikipedia_title}")
        add(f"Wikipedia revision ID : {semantic.wikipedia_revision_id}"
            f"  ({semantic.wikipedia_revision_timestamp})")
        if semantic.wikipedia_redirected_from:
            add(f"Wikipedia redirect    : {semantic.wikipedia_redirected_from} -> "
                f"{semantic.wikipedia_title}")
        add(f"Lead length           : {semantic.character_length} characters, "
            f"{semantic.sentence_count} sentences")
        if semantic.text_sha256:
            add(f"Lead SHA-256          : {semantic.text_sha256}")
    if semantic and semantic.detail:
        add(f"Semantic text detail  : {semantic.detail}")
    add(f"N used for IDF        : {universe.total_entities if universe else None}"
        f"   [{universe.definition if universe else 'none'}]")
    add(f"alpha                 : {ranking.alpha}")
    add(f"Scoring mode          : {ranking.scoring_mode.value}")
    add(f"Categories discovered : {features.categories_discovered}"
        f"{'  (TRUNCATED at the category limit)' if features.categories_truncated else ''}")
    add(f"Feasible / rejected   : {len(features.feasible_classes)} feasible, "
        f"{len(features.rejected_classes)} rejected")
    add(f"Selection status      : {features.status}")
    if features.error:
        add(f"Error                 : {features.error}")
    add("")
    add("NOTE: this is an automatic recommendation ranking of FEASIBLE "
        "candidate-source classes.")
    add("      The top-ranked class is not claimed to be globally optimal or "
        "educationally best.")
    add("")

    add("-" * 100)
    add(f"COMPLETE FEASIBLE RANKING ({len(ranking.ranked)} classes)")
    add("-" * 100)
    header = (f"{'rk':>3}  {'label':<46} {'n_c':>7} {'raw_idf':>8} {'nIDF':>6} "
              f"{'raw_sb':>7} {'nSB':>6} {'score':>7}  leak")
    add(header)
    for entry in ranking.ranked:
        feature = entry.feature
        raw_sb = "  n/a" if feature.raw_sbert is None else f"{feature.raw_sbert:7.4f}"
        n_sb = "   n/a" if entry.normalized_sbert is None else f"{entry.normalized_sbert:6.3f}"
        add(f"{entry.feasible_rank:>3}  {feature.category_label[:46]:<46} "
            f"{feature.remote_count:>7} {feature.raw_idf:8.4f} "
            f"{entry.normalized_idf:6.3f} {raw_sb} {n_sb} "
            f"{entry.combined_score:7.4f}  {feature.leak_level.value}")
        add(f"     {feature.category_uri}")
        add(f"     eligible members excluding the Answer: "
            f"{feature.eligible_remote_count}"
            + (f"   |  SOFT leak evidence: {', '.join(feature.leak_evidence)}"
               if feature.leak_evidence else ""))

    rejected = features.rejected_classes
    add("")
    add("-" * 100)
    add(f"REJECTED CLASSES ({len(rejected)}) — no feasible rank is assigned to these")
    add("-" * 100)
    for feature in sorted(rejected, key=lambda c: (c.rejected_code or "", c.category_uri)):
        add(f"  [{feature.rejected_code}] {feature.category_uri}")
        add(f"      {feature.rejected_reason}")
        if feature.leak_evidence:
            add(f"      leak evidence: {', '.join(feature.leak_evidence)}")
    add("=" * 100)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 5) The run
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    """Everything one run needs, constructed only after the network gate."""

    runner: SparqlRunner
    universe: IdfUniverse
    encoder: Optional[SbertEncoder]
    lead_client: Optional[WikipediaLeadClient]
    lead_cache: Optional[WikipediaLeadCache]
    semantic_source: SemanticSource
    policy: Any


def build_run_context(args: argparse.Namespace) -> RunContext:
    """Construct the live runner, the encoder and the Wikipedia client.

    Called only after the network gate has passed. The SBERT model is loaded
    lazily on first use and with ``local_files_only=True``, so a missing model
    raises rather than silently downloading weights.
    """
    runner = make_dbpedia_runner(
        endpoint=args.endpoint,
        cache_path=None if args.no_sparql_cache else args.cache_path,
        bypass=args.bypass,
        anytime_timeout_ms=args.anytime_timeout_ms)
    universe = resolve_idf_universe(runner, explicit_total=args.total_entities)

    encoder = None if args.no_sbert else SbertEncoder(name=args.sbert_model)

    lead_cache = WikipediaLeadCache(args.wikipedia_cache_path)
    lead_client = WikipediaLeadClient(
        transport=RequestsWikipediaTransport(user_agent=args.user_agent),
        cache=lead_cache, allow_network=args.allow_network)
    return RunContext(runner=runner, universe=universe, encoder=encoder,
                      lead_client=lead_client, lead_cache=lead_cache,
                      semantic_source=SemanticSource(args.semantic_source),
                      policy=load_r1_leakage_policy())


def extract_all_features(
    answer_uris: Sequence[str], context: RunContext, args: argparse.Namespace,
    *, progress: bool = True,
) -> tuple[dict[str, AnswerFeatures], dict[str, Any]]:
    """Extract features for every Answer exactly once. Returns (features, leads).

    Wikipedia leads are fetched first, batched and cached, so the whole corpus
    costs about one request per twenty Answers rather than one per Answer, and a
    rerun costs none at all.
    """
    leads: dict[str, Any] = {}
    if context.lead_client is not None:
        leads = context.lead_client.fetch_many(list(answer_uris))
        if context.lead_cache is not None:
            context.lead_cache.save()

    features: dict[str, AnswerFeatures] = {}
    for index, uri in enumerate(answer_uris, start=1):
        features[uri] = extract_answer_features(
            uri, runner=context.runner, idf_universe=context.universe,
            semantic_source=context.semantic_source,
            wikipedia_lead=leads.get(uri), encoder=context.encoder,
            quality_policy=context.policy,
            min_remote_candidates=args.min_remote_candidates,
            max_remote_candidates=args.max_remote_candidates,
            category_limit=args.category_limit)
        if progress:
            print(f"  [{index}/{len(answer_uris)}] {uri} -> "
                  f"{features[uri].status} "
                  f"({len(features[uri].feasible_classes)} feasible)",
                  file=sys.stderr, flush=True)
    return features, leads


def _pilot_diagnostic_rows(
    rankings_by_alpha: Mapping[float, Mapping[str, AnswerRanking]],
    policy_path: Path,
) -> list[dict[str, Any]]:
    """Development-only agreement of v6's ranking with the frozen nine-Answer
    P2 pilot policy.

    THE PILOT IS NOT GROUND TRUTH. Nine human-approved classes were chosen for an
    ENGINEERING pilot, under a policy this task must not modify and did not train
    on. They are reported here because a completely automatic method with no
    reference point at all is unreviewable — not because agreement with nine
    examples establishes that a class, or an alpha, is correct. Nine examples
    cannot support a claim of universal optimality for any alpha.
    """
    if not policy_path.is_file():
        return []
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for alpha in sorted(rankings_by_alpha):
        by_uri = rankings_by_alpha[alpha]
        for entry in policy.get("answers", ()):
            uri = str(entry["answer_uri"])
            ranking = by_uri.get(uri)
            preferred = str(entry.get("preferred_class") or "")
            fallbacks = [str(entry[k]) for k in ("fallback_class_1", "fallback_class_2")
                         if entry.get(k)]
            ranked = list(ranking.top_k(10 ** 6)) if ranking else []
            top1 = ranked[0] if ranked else None
            rows.append({
                "alpha": alpha,
                "pilot_slot": entry.get("pilot_slot"),
                "answer_uri": uri,
                "answer_display_label": entry.get("display_label"),
                "preferred_class": preferred,
                # Distinguishes "this Answer was not in the run" from "this
                # Answer was ranked and no approved class survived the gate".
                "answer_processed": ranking is not None,
                "v6_top1_class": top1,
                "v6_feasible_count": len(ranked),
                "preferred_is_top1": bool(top1 and top1 == preferred),
                "preferred_in_top3": preferred in ranked[:3],
                "preferred_in_top5": preferred in ranked[:5],
                "preferred_rank": (ranked.index(preferred) + 1
                                   if preferred in ranked else None),
                "preferred_is_feasible": preferred in ranked,
                "any_approved_class_is_top1": bool(
                    top1 and top1 in ([preferred] + fallbacks)),
                "any_approved_class_in_top3": any(
                    c in ranked[:3] for c in [preferred] + fallbacks),
                "any_approved_class_in_top5": any(
                    c in ranked[:5] for c in [preferred] + fallbacks),
                "approved_fallbacks": fallbacks,
                "scoring_mode": ranking.scoring_mode.value if ranking else None,
            })
    return rows


def _stability_rows(
    rankings_by_alpha: Mapping[float, Mapping[str, AnswerRanking]],
    answer_uris: Sequence[str], cohorts: Mapping[str, Optional[str]],
) -> list[dict[str, Any]]:
    """Per-Answer sensitivity of the ranking to alpha.

    Reports HOW MUCH the ranking moves, never which alpha is best: the tables
    below contain no criterion by which one alpha could be called correct.
    """
    alphas = sorted(rankings_by_alpha)
    rows: list[dict[str, Any]] = []
    for uri in answer_uris:
        rankings = {a: rankings_by_alpha[a].get(uri) for a in alphas}
        tops = [r.top_ranked_class for r in rankings.values() if r is not None]
        distinct_tops = sorted({t for t in tops if t})
        positions: dict[float, dict[str, int]] = {}
        for alpha, ranking in rankings.items():
            if ranking is None:
                continue
            positions[alpha] = {e.category_uri: e.feasible_rank for e in ranking.ranked}
        correlations: dict[str, Optional[float]] = {}
        rho_values: list[float] = []
        for i, a in enumerate(alphas):
            for b in alphas[i + 1:]:
                pa, pb = positions.get(a), positions.get(b)
                if not pa or not pb:
                    correlations[f"rho_alpha_{a}_vs_{b}"] = None
                    continue
                shared = sorted(set(pa) & set(pb))
                rho = spearman_rho([pa[c] for c in shared], [pb[c] for c in shared])
                correlations[f"rho_alpha_{a}_vs_{b}"] = rho
                if rho is not None:
                    rho_values.append(rho)
        any_ranking = next((r for r in rankings.values() if r is not None), None)
        rows.append({
            "cohort": cohorts.get(uri),
            "answer_uri": uri,
            "answer_display_label": any_ranking.answer_label if any_ranking else "",
            "feasible_count": len(any_ranking.ranked) if any_ranking else 0,
            "scoring_mode": any_ranking.scoring_mode.value if any_ranking else None,
            "distinct_top1_count": len(distinct_tops),
            "top1_invariant_to_alpha": len(distinct_tops) <= 1,
            "distinct_top1_classes": distinct_tops,
            "min_pairwise_spearman": min(rho_values) if rho_values else None,
            "mean_pairwise_spearman": (sum(rho_values) / len(rho_values)
                                       if rho_values else None),
            # Insertion order, i.e. ascending alpha pairs. Sorting these keys
            # as strings would put rho_0.75_1.0 before rho_0.7_0.75.
            **correlations,
        })
    return rows


def _manifest(args: argparse.Namespace, context: RunContext,
              parsed: Optional[ParsedAnswers], alphas: Sequence[float],
              answer_uris: Sequence[str], features: Mapping[str, AnswerFeatures],
              leads: Mapping[str, Any], outputs: Sequence[Path]) -> dict[str, Any]:
    lead_states: dict[str, int] = {}
    for lead in leads.values():
        lead_states[lead.status.value] = lead_states.get(lead.status.value, 0) + 1
    statuses: dict[str, int] = {}
    for f in features.values():
        statuses[f.status] = statuses.get(f.status, 0) + 1
    return {
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "selector_schema_version": SELECTOR_SCHEMA_VERSION,
        "generated_at": iso_utc(),
        "command_arguments": sys.argv[1:],
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "endpoint": args.endpoint,
        "allow_network": bool(args.allow_network),
        "semantic_source": args.semantic_source,
        "sbert_model": None if args.no_sbert else args.sbert_model,
        "alphas": list(alphas),
        "default_alpha": DEFAULT_ALPHA,
        "min_remote_candidates": args.min_remote_candidates,
        "max_remote_candidates": args.max_remote_candidates,
        "category_limit": args.category_limit,
        "sparql_cache_path": None if args.no_sparql_cache else str(args.cache_path),
        "wikipedia_cache_path": str(args.wikipedia_cache_path),
        "wikipedia_user_agent": args.user_agent,
        "idf_universe": context.universe.to_dict(),
        "r1_policy_path": str(
            Path(__file__).resolve().parents[1] / "src" / "rationale_v3"
            / "policies" / "predicate_policy.json"),
        "r1_policy_sha256": context.policy.policy_sha256,
        "r1_policy_version": context.policy.version,
        "input_path": parsed.path if parsed else None,
        "input_sha256": sha256_file(parsed.path) if parsed else None,
        "input_audit": parsed.audit() if parsed else None,
        "answers_requested": len(answer_uris),
        "answer_status_counts": dict(sorted(statuses.items())),
        "wikipedia_lead_status_counts": dict(sorted(lead_states.items())),
        "sparql_stats": context.runner.stats(),
        "wikipedia_stats": (context.lead_client.stats()
                            if context.lead_client else {}),
        "outputs": [str(p.name) for p in outputs],
        "claim_discipline_note": (
            "This run produces an AUTOMATIC RECOMMENDATION ranking of FEASIBLE "
            "candidate-source classes. No class here is claimed to be globally "
            "optimal, true, or educationally best, and no alpha is claimed to be "
            "optimal. Cohort labels are evaluation metadata and were never "
            "passed to the ranker."),
    }


def run_batch(args: argparse.Namespace, context: RunContext,
              parsed: Optional[ParsedAnswers], answer_uris: Sequence[str],
              cohorts: Mapping[str, Optional[str]], alphas: Sequence[float],
              features: Mapping[str, AnswerFeatures],
              leads: Mapping[str, Any]) -> int:
    """Rank the ALREADY-EXTRACTED features at every alpha and write every
    artifact.

    Feature extraction is deliberately not performed here: it happens once in
    :func:`main`, so no code path can extract the same Answer twice and no alpha
    can be scored against a second, later observation of the endpoint.
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rankings_by_alpha: dict[float, dict[str, AnswerRanking]] = {}
    for alpha in alphas:
        rankings_by_alpha[alpha] = {
            uri: rank_feasible_classes(features[uri], alpha) for uri in answer_uris}

    written: list[Path] = []
    sweep = len(alphas) > 1

    if parsed is not None:
        written.append(_write(output_dir / "answers_parsed.csv", _csv_text(
            ["line_number", "answer_uri", "cohort", "cohort_raw", "is_duplicate",
             "uri_is_valid", "used_in_run", "all_cohort_memberships"],
            [{"line_number": r.line_number, "answer_uri": r.answer_uri,
              "cohort": r.cohort, "cohort_raw": r.cohort_raw,
              "is_duplicate": r.is_duplicate, "uri_is_valid": r.uri_is_valid,
              "used_in_run": r.answer_uri in set(answer_uris) and not r.is_duplicate,
              "all_cohort_memberships": parsed.cohorts_by_uri.get(r.answer_uri, [])}
             for r in parsed.rows])))
        written.append(_write(output_dir / "malformed_rows.csv", _csv_text(
            ["line_number", "text", "problem"],
            [{"line_number": n, "text": t, "problem": "not_a_comment_blank_or_uri"}
             for n, t in parsed.malformed_rows]
            + [{"line_number": n, "text": t,
                "problem": "uri_prefix_present_but_not_a_valid_iri"}
               for n, t in parsed.invalid_uri_rows])))
        written.append(_write(output_dir / "duplicate_answers.csv", _csv_text(
            ["answer_uri", "occurrence_count", "line_numbers", "cohorts"],
            [{"answer_uri": uri,
              "occurrence_count": len([r for r in parsed.rows if r.answer_uri == uri]),
              "line_numbers": [r.line_number for r in parsed.rows if r.answer_uri == uri],
              "cohorts": parsed.cohorts_by_uri.get(uri, [])}
             for uri in sorted({r.answer_uri for r in parsed.rows
                                if r.is_duplicate})])))
        written.append(_write(output_dir / "answers_input_audit.json",
                              json.dumps(parsed.audit(), indent=1,
                                         ensure_ascii=False, sort_keys=True) + "\n"))

    written.append(_write(output_dir / "semantic_text_coverage.csv", _csv_text(
        COVERAGE_COLUMNS,
        [_coverage_row(features[uri], cohorts.get(uri), leads.get(uri))
         for uri in answer_uris])))

    written.append(_write(output_dir / "rejected_classes.csv", _csv_text(
        REJECTED_COLUMNS,
        [row for uri in answer_uris
         for row in _rejected_rows(features[uri], cohorts.get(uri))])))

    written.append(_write(output_dir / "idf_universe_provenance.json",
                          json.dumps(context.universe.to_dict(), indent=1,
                                     ensure_ascii=False, sort_keys=True) + "\n"))

    all_ranking_rows = [
        row for alpha in alphas for uri in answer_uris
        for row in _ranking_rows(rankings_by_alpha[alpha][uri], cohorts.get(uri))]
    summary_rows = [
        _summary_row(rankings_by_alpha[alpha][uri], cohorts.get(uri))
        for alpha in alphas for uri in answer_uris]

    written.append(_write(output_dir / "answer_summary.csv",
                          _csv_text(SUMMARY_COLUMNS, summary_rows)))

    if sweep:
        written.append(_write(output_dir / "alpha_sweep_all_rankings.csv",
                              _csv_text(RANKING_COLUMNS, all_ranking_rows)))
        written.append(_write(output_dir / "alpha_sweep_top1.csv", _csv_text(
            ["alpha", "cohort", "answer_uri", "answer_display_label",
             "scoring_mode", "top1_class_uri", "top1_class_label",
             "top1_combined_score", "feasible_count"],
            [{"alpha": alpha, "cohort": cohorts.get(uri), "answer_uri": uri,
              "answer_display_label": rankings_by_alpha[alpha][uri].answer_label,
              "scoring_mode": rankings_by_alpha[alpha][uri].scoring_mode.value,
              "top1_class_uri": rankings_by_alpha[alpha][uri].top_ranked_class,
              "top1_class_label": (rankings_by_alpha[alpha][uri].ranked[0]
                                   .feature.category_label
                                   if rankings_by_alpha[alpha][uri].ranked else None),
              "top1_combined_score": (rankings_by_alpha[alpha][uri].ranked[0]
                                      .combined_score
                                      if rankings_by_alpha[alpha][uri].ranked else None),
              "feasible_count": len(rankings_by_alpha[alpha][uri].ranked)}
             for alpha in alphas for uri in answer_uris])))
        written.append(_write(output_dir / "alpha_sweep_topk.csv", _csv_text(
            ["alpha", "cohort", "answer_uri", "answer_display_label", "k",
             "rank", "category_uri", "category_label", "combined_score"],
            [{"alpha": alpha, "cohort": cohorts.get(uri), "answer_uri": uri,
              "answer_display_label": rankings_by_alpha[alpha][uri].answer_label,
              "k": k, "rank": entry.feasible_rank,
              "category_uri": entry.category_uri,
              "category_label": entry.feature.category_label,
              "combined_score": entry.combined_score}
             for alpha in alphas for uri in answer_uris for k in (1, 3, 5)
             for entry in rankings_by_alpha[alpha][uri].ranked[:k]])))
        written.append(_write(output_dir / "alpha_rank_stability.csv", (lambda rows: _csv_text(
            list(rows[0].keys()) if rows else ["answer_uri"], rows))(
                _stability_rows(rankings_by_alpha, answer_uris, cohorts))))
    else:
        written.append(_write(output_dir / "class_rankings_all.csv",
                              _csv_text(RANKING_COLUMNS, all_ranking_rows)))

    pilot_rows = _pilot_diagnostic_rows(rankings_by_alpha, Path(args.pilot_policy))
    if pilot_rows:
        written.append(_write(output_dir / "pilot9_alpha_diagnostic.csv",
                              _csv_text(list(pilot_rows[0].keys()), pilot_rows)))

    manifest_name = "alpha_sweep_manifest.json" if sweep else "run_manifest.json"
    manifest = _manifest(args, context, parsed, alphas, answer_uris, features,
                         leads, written)
    written.append(_write(output_dir / manifest_name,
                          json.dumps(manifest, indent=1, ensure_ascii=False,
                                     sort_keys=True) + "\n"))

    print(f"\nWrote {len(written)} file(s) to {output_dir}:", file=sys.stderr)
    for path in written:
        print(f"  {path.name}", file=sys.stderr)
    print(f"SPARQL: {context.runner.stats()}", file=sys.stderr)
    if context.lead_client is not None:
        print(f"Wikipedia: {context.lead_client.stats()}", file=sys.stderr)
    return EXIT_OK


# ---------------------------------------------------------------------------
# 6) Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_category_selector_v6.py",
        description=(
            "Automatic candidate-source class selection (v6): Wikipedia-lead "
            "semantic similarity fused with standard IDF over DBpedia "
            "dcterms:subject categories."),
        epilog=(
            "Network access is denied unless --allow-network is given. The "
            "top-ranked class is an automatic recommendation, never a claim of "
            "global or educational optimality."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--answer-uri", type=str, default=None,
                        help="run ONE Answer and print its complete ranking")
    source.add_argument("--input", type=Path, default=None,
                        help="Answers.txt-format file to run as a batch")

    weight = parser.add_mutually_exclusive_group()
    weight.add_argument("--alpha", type=float, default=None,
                        help=f"semantic weight, 0 <= alpha <= 1 "
                             f"(default {DEFAULT_ALPHA}, a neutral equal "
                             f"weighting, NOT a claim of optimality)")
    weight.add_argument("--alphas", type=str, default=None,
                        help="comma-separated alphas for a sweep, e.g. "
                             "0,0.25,0.5,0.7,0.75,1")

    parser.add_argument("--output-dir", type=Path, default=None,
                        help="required for a batch run; ignored for --answer-uri")
    parser.add_argument("--semantic-source", choices=[s.value for s in SemanticSource],
                        default=SemanticSource.WIKIPEDIA_LEAD.value,
                        help="ONE source per run; the two are never mixed")
    parser.add_argument("--allow-network", action="store_true",
                        help="opt in to contacting DBpedia and Wikipedia")
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT)
    parser.add_argument("--cache-path", type=str, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--wikipedia-cache-path", type=str,
                        default=DEFAULT_WIKIPEDIA_CACHE_PATH)
    parser.add_argument("--no-sparql-cache", action="store_true",
                        help="do not read or write the SPARQL response cache")
    parser.add_argument("--bypass", action="store_true",
                        help="neither read nor write the SPARQL cache this run")
    parser.add_argument("--total-entities", type=int, default=None,
                        help="explicit IDF universe N; overrides the run-level "
                             "global-count query and makes an offline replay "
                             "reproduce a live run's raw_idf exactly")
    parser.add_argument("--anytime-timeout-ms", type=int, default=None,
                        help="Virtuoso anytime budget in ms for long queries")
    parser.add_argument("--sbert-model", type=str, default=DEFAULT_SBERT_MODEL)
    parser.add_argument("--no-sbert", action="store_true",
                        help="skip semantic scoring entirely; every row is then "
                             "stamped idf_only_semantic_unavailable")
    parser.add_argument("--user-agent", type=str, default=DEFAULT_USER_AGENT)
    parser.add_argument("--min-remote-candidates", type=int, default=10)
    parser.add_argument("--max-remote-candidates", type=int, default=5000)
    parser.add_argument("--category-limit", type=int, default=200)
    parser.add_argument("--pilot-policy", type=Path, default=DEFAULT_PILOT_POLICY,
                        help="frozen nine-Answer P2 pilot policy, READ ONLY, used "
                             "only as a development diagnostic")
    parser.add_argument("--limit", type=int, default=None,
                        help="process only the first N unique Answers")
    parser.add_argument("--strict-input", action="store_true",
                        help="refuse to run when the input file has any "
                             "malformed or unqueryable row (default: report "
                             "them, exclude them, and continue)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.alphas is not None:
        try:
            alphas = parse_alpha_list(args.alphas)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
    else:
        try:
            alphas = [validate_alpha(DEFAULT_ALPHA if args.alpha is None else args.alpha)]
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    parsed: Optional[ParsedAnswers] = None
    cohorts: dict[str, Optional[str]] = {}
    if args.input is not None:
        if args.output_dir is None:
            print("error: --output-dir is required with --input.", file=sys.stderr)
            return EXIT_USAGE
        if not Path(args.input).is_file():
            print(f"error: input file not found: {args.input}", file=sys.stderr)
            return EXIT_USAGE
        parsed = parse_answers_file(args.input)
        # Input problems are REPORTED, on stderr and in answers_input_audit.json
        # and malformed_rows.csv, and the offending rows are excluded from the
        # run because they cannot be queried. They are never silently dropped.
        # --strict-input turns the report into a refusal for an operator who
        # would rather fix the file than run a corpus with a known defect.
        if parsed.malformed_rows:
            print(f"INPUT PROBLEM: {len(parsed.malformed_rows)} malformed row(s) "
                  f"in {args.input} — neither comments, blanks, nor DBpedia "
                  f"resource URIs:", file=sys.stderr)
            for number, text in parsed.malformed_rows[:20]:
                print(f"  line {number}: {text!r}", file=sys.stderr)
        if parsed.invalid_uri_rows:
            print(f"INPUT PROBLEM: {len(parsed.invalid_uri_rows)} row(s) in "
                  f"{args.input} start with the DBpedia resource prefix but are "
                  f"not valid IRIs, so they cannot be queried and are EXCLUDED "
                  f"from this run:", file=sys.stderr)
            for number, text in parsed.invalid_uri_rows[:20]:
                print(f"  line {number}: {text!r}", file=sys.stderr)
        if parsed.input_problem_count and args.strict_input:
            print("refusing to run: --strict-input was given and the input file "
                  "has the problem(s) reported above.", file=sys.stderr)
            return EXIT_USAGE
        answer_uris = list(parsed.unique_uris)
        cohorts = {uri: (parsed.cohorts_by_uri.get(uri) or [None])[0]
                   for uri in answer_uris}
        if args.limit is not None:
            answer_uris = answer_uris[:max(0, args.limit)]
        if not answer_uris:
            print(f"error: {args.input} contains no usable Answer URIs.",
                  file=sys.stderr)
            return EXIT_USAGE
        print(f"Parsed {args.input}: {parsed.answer_row_count} Answer rows "
              f"(§N grammar), "
              f"{len({r.answer_uri for r in parsed.rows})} unique URIs, "
              f"{parsed.duplicate_row_count} duplicate rows, "
              f"{len(parsed.cohort_order)} cohorts; "
              f"{len(parsed.unique_uris)} unique URIs are runnable.",
              file=sys.stderr)
    else:
        answer_uris = [str(args.answer_uri).strip()]

    # ---- the network gate --------------------------------------------------
    # Everything above reads local files only. No live client, no model and no
    # Wikipedia request exists until this check has passed.
    if not args.allow_network:
        print("refusing to run: this would query "
              f"{args.endpoint} and en.wikipedia.org for {len(answer_uris)} "
              "Answer(s).\nNetwork access is denied by default. Re-run with "
              "--allow-network if you intend to contact them.", file=sys.stderr)
        return EXIT_NETWORK_DENIED

    context = build_run_context(args)
    if not context.universe.available:
        print("refusing to score: no IDF universe N could be measured and none "
              "was supplied.\n"
              f"  attempts: {json.dumps(context.universe.to_dict()['attempts'])}\n"
              "No value was invented. Re-run with --total-entities N to score "
              "against an explicit universe.", file=sys.stderr)
        return EXIT_NO_IDF_UNIVERSE

    # Features are extracted EXACTLY ONCE here, whatever the mode and however
    # many alphas were requested (Prompt §L).
    print(f"Extracting features for {len(answer_uris)} Answer(s) "
          f"(this happens ONCE, for all {len(alphas)} alpha value(s))...",
          file=sys.stderr)
    features, leads = extract_all_features(answer_uris, context, args,
                                           progress=args.input is not None)

    if args.input is None:
        uri = answer_uris[0]
        for alpha in alphas:
            print(format_single_answer_report(
                rank_feasible_classes(features[uri], alpha),
                cohorts.get(uri)))

    if args.output_dir is None:
        return EXIT_OK
    return run_batch(args, context, parsed, answer_uris, cohorts, alphas,
                     features, leads)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
