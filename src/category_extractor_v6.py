############################################################################
# src/category_extractor_v6.py
#
# Journal 2 — automatic candidate-source class selection, version 6.
#
# WHAT THIS MODULE IS
#   Given one DBpedia Answer URI it discovers the Answer's ``dcterms:subject``
#   categories, applies a HARD feasibility gate, and produces an automatic,
#   reproducible RANKING of the feasible candidate-source classes. That is all.
#
#   The ranking is a P0-style automatic recommendation. It is NOT a claim that
#   the top-ranked class is globally optimal, educationally best, or "the true
#   class" (CLAUDE.md item 9). Downstream local mapping still decides whether a
#   ranked class can actually supply enough candidates from the pinned KG, and a
#   human may still override the ranking entirely.
#
# WHAT CHANGED RELATIVE TO category_extractor_ClaudeWeb_v5.py (4,028 lines)
#   v5 stays byte-identical and frozen (CLAUDE.md file safety). v6 is a separate,
#   much smaller module. Four substantive scientific changes and one large
#   subtraction:
#
#   C1  SEMANTIC SOURCE. v5's semantic branch encodes ``dbo:abstract``. Measured
#       during Prompt 8H-B2-B, the current public DBpedia endpoint serves NO
#       abstracts at all — Albert Einstein has 1,166 outgoing triples there and
#       zero abstracts in any language — so the v5 Einstein run was in fact
#       IDF-only while being reported as an IDF+SBERT run. v6's primary semantic
#       text is the English WIKIPEDIA LEAD SECTION, retrieved through an official
#       MediaWiki API (``classes.wikipedia_lead``). It is never called
#       "abstract": see WHY WIKIPEDIA IS RANKING EVIDENCE below.
#
#   C2  STANDARD IDF. v5 records ``raw_idf = log(N/n_c) / log(N)`` — standard IDF
#       divided by the positive constant ``log(N)`` — under a name that suggests
#       it is the textbook quantity. v6 records the conventional
#       ``IDF(c) = log(N / n_c)``. No ablation between the two is run or needed:
#       for a FIXED N they differ by a positive constant factor, hence are
#       strictly monotonic transformations of one another, hence induce exactly
#       the same ordering, hence are IDENTICAL after the within-Answer rank
#       normalisation both versions apply. An "ablation" between them could only
#       ever measure floating-point noise.
#
#   C3  A COMPATIBLE IDF UNIVERSE, MEASURED ONCE. v5's ``total_entities`` is the
#       documented constant 6,000,000. v6 measures N from the SAME universe n_c
#       comes from — resources carrying a DBpedia ``dcterms:subject`` category
#       membership — with ONE run-level query whose result, endpoint, timestamp,
#       query hash and cache status are recorded. It is never the pinned local
#       KG's 6,685,753 node count: that is the March-2023 *infobox* node
#       universe, a different population from the live category-membership
#       universe n_c is counted in, and mixing them would make log(N/n_c) a ratio
#       between two different denominators. When no measured, cached or
#       explicitly supplied N exists, the run REFUSES to score rather than
#       inventing 6,000,000 or 6,685,753.
#
#   C4  ALPHA IS A PRE-SPECIFIED 0.7 AND A SWEEP REUSES FROZEN FEATURES. Ranking
#       is split into (a) feature extraction, which performs every network call
#       exactly once, and (b) :func:`rank_feasible_classes`, a pure function of
#       those frozen features and one alpha. A six-alpha sweep therefore costs
#       the same traffic as a single run and is guaranteed to compare six
#       rankings of the SAME observations. The executable default is 0.7, the
#       researcher's PRE-SPECIFIED main working configuration fixed after the
#       development sensitivity analysis and before the ~100-Answer experiment;
#       it is not claimed to be an optimum. See DEFAULT_ALPHA below.
#
#   S   SUBTRACTION. v6 drops v5's manual/first_feasible modes, its WordNet and
#       spaCy hooks, its v4-compatible ``detect_leak`` and its redirect
#       machinery, its local-KG probing, its batched member-roster pagination,
#       its ``PerAnswerRunner`` counter view, and its v2/v3/v4 compatibility
#       wrappers. None of them is needed by an automatic P0-style ranker, and
#       every one of them was a place a reader had to check before trusting the
#       ranking.
#
# WHY WIKIPEDIA LEAD TEXT IS RANKING EVIDENCE AND NEVER RATIONALE-TRUTH EVIDENCE
#   The rationale layer argues over the PINNED March-2023 DBpedia infobox graph
#   under an Open-World Assumption. A Wikipedia lead fetched today belongs to a
#   later, unpinned corpus and its revision changes without notice. Using it to
#   support a rationale would import present-day prose into a frozen-snapshot
#   argument. Here it does exactly one thing: it supplies the query vector whose
#   cosine similarity to a class LABEL orders candidate-source classes. Nothing
#   downstream of this ranking reads the text.
#
# WHY dbo:description IS NOT MIXED INTO A WIKIPEDIA-LEAD RUN
#   ``dbo:description`` is a one-line gloss ("German-born theoretical physicist
#   (1879-1955)"); a Wikipedia lead is a paragraph. Their embeddings occupy
#   different regions of the sentence-encoder's space, so a corpus scored partly
#   from one and partly from the other would have per-Answer scores that are not
#   comparable — and the incomparability would correlate with which Answers
#   happen to lack a Wikipedia page, i.e. with the very population any coverage
#   claim is about. ``--semantic-source`` therefore selects ONE source for a
#   whole run. The census in the runner reports the availability of both, which
#   is a coverage statement and not a quality comparison.
#
# WHY HARD LEAKAGE IS THE FROZEN R1 RULE PLUS ONE EXPLICIT CLASS-ONLY RULE
#   ``rationale_v3.quality.detect_answer_leakage`` ("R1") is imported and called,
#   never paraphrased. It is deterministic, model-free, and reads its four
#   thresholds from the SHA-256-pinned ``predicate_policy.json``.
#
#   R1 alone is not sufficient for a CLASS LABEL. R1's HARD branch requires that
#   one complete token be a prefix of the other, which is right for a rationale
#   counterpart and leaves ``Aristotle`` / ``Category:Aristotelian_philosophers``
#   at SOFT — an answer-revealing class name that would remain feasible. So a
#   SECOND, CLASS-ONLY rule is composed on top: ``classes.class_leakage``, a
#   deterministic derivational/eponymic detector with an explicit suffix list, a
#   minimum stem length and a bounded edit distance. It can only RAISE a verdict
#   to HARD, it never contradicts or modifies R1, and by construction it is
#   almost empty on top of R1 (a suffix that attaches without altering the stem
#   is already a LONG_PREFIX hard leak).
#
#   WordNet, spaCy, embeddings and LLMs cannot participate in a HARD rejection
#   here — they are not imported by this module or by ``classes.class_leakage``,
#   which is a structural guarantee rather than a policy someone must remember.
#   SOFT leakage annotates and may inform ranking; it never rejects.
#
# WHY A SIZE-REJECTED CLASS STILL CARRIES A TRUTHFUL LEAKAGE ANNOTATION
#   Feasibility and leakage are INDEPENDENT diagnostics and are computed
#   independently. Before this version the leakage gate ran only on classes that
#   had already survived the size gates, so ``Aristotle`` / ``Category:Aristotle``
#   was published as ``leak_level = no_leak`` purely because it was too small to
#   reach the leakage test — a scientifically false annotation, even though the
#   class was (correctly) excluded on its size. Leakage is now evaluated for
#   every syntactically valid, non-administrative candidate class, whatever else
#   later rejects it, and a class whose URI cannot be adapted for the comparison
#   is stamped NOT_EVALUATED rather than defaulted to ``no_leak``.
#
# IMPORT-TIME PURITY
#   Importing this module opens no socket, creates no file, loads no model and
#   reads no policy. Every one of those happens inside an explicitly called
#   function.
############################################################################

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, Sequence

# The frozen R1 lexical leakage rule and the frozen display normaliser. Imported
# from the pinned rationale_v3 package, never re-derived: re-deriving the token /
# prefix arithmetic here would create a NEW, unmeasured rule wearing the old
# rule's name. ``display_label`` is the same audited normaliser the rationale
# layer renders choices with, so a class label shown here and a counterpart label
# shown there are produced by one function.
from rationale_v3.quality import (
    QualityPolicy,
    detect_answer_leakage,
    display_label,
    load_quality_policy,
)
from classes.wikipedia_lead import (
    LeadStatus,
    WikipediaLead,
    WikipediaLeadClient,
    count_sentences,
    iso_utc,
    sha256_text,
)
# The CLASS-ONLY leakage extension. It imports R1 and composes on top of it; it
# never re-implements or relaxes R1. Kept in its own module so the extra rule can
# be read, tested and audited without reading the selector, and so this module's
# "no model participates in a HARD rejection" guarantee stays inspectable as an
# import list.
from classes.class_leakage import (
    LEAK_STATUS_EVALUATED,
    LEAK_STATUS_NOT_EVALUATED,
    DEFAULT_DERIVATIONAL_POLICY,
    ClassLeakVerdict,
    DerivationalPolicy,
    classify_class_leakage_extended as _classify_class_leakage_extended,
    not_evaluated_verdict,
)

__all__ = [
    "SCHEMA_VERSION",
    "CACHE_SCHEMA_VERSION",
    "DEFAULT_ALPHA",
    "SWEEP_ALPHAS",
    "DEFAULT_ENDPOINT",
    "DEFAULT_SBERT_MODEL",
    "SemanticSource",
    "SemanticStatus",
    "ScoringMode",
    "QueryStatus",
    "CacheStatus",
    "LeakLevel",
    "RejectCode",
    "QueryResult",
    "SparqlCache",
    "SqliteSparqlCache",
    "InMemorySparqlCache",
    "SparqlRunner",
    "HttpSparqlClient",
    "make_dbpedia_runner",
    "normalize_category",
    "category_uri_to_resource_uri",
    "category_display_label",
    "load_r1_leakage_policy",
    "classify_class_leakage",
    "classify_class_leakage_extended",
    "LeakVerdict",
    "LeakStatus",
    "DEFAULT_DERIVATIONAL_POLICY",
    "DerivationalPolicy",
    "standard_idf",
    "rank_normalize",
    "combine_alpha",
    "validate_alpha",
    "IdfUniverse",
    "resolve_idf_universe",
    "SemanticText",
    "SbertEncoder",
    "TextEncoder",
    "chunk_text",
    "split_sentences",
    "cosine",
    "encode_semantic_similarity",
    "ClassFeature",
    "AnswerFeatures",
    "RankedClass",
    "AnswerRanking",
    "extract_answer_features",
    "rank_feasible_classes",
    "build_answer_info_query",
    "build_answer_categories_query",
    "build_category_counts_query",
    "build_idf_universe_query",
    "build_idf_universe_query_unfiltered",
    "JUNK_CATEGORY_PATTERNS",
]

# ---------------------------------------------------------------------------
# 0) CONFIGURATION — plain constants. Nothing here performs I/O.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "category_selector_v6.0"
CACHE_SCHEMA_VERSION = "category_v6_sparql_cache_v1"

DEFAULT_ENDPOINT = os.environ.get("DBPEDIA_ENDPOINT", "https://dbpedia.org/sparql")
DEFAULT_LANGUAGE = "en"

DEFAULT_CACHE_PATH = os.environ.get(
    "CATEGORY_V6_SPARQL_CACHE", "./cache/category_v6_sparql.sqlite"
)
DEFAULT_WIKIPEDIA_CACHE_PATH = os.environ.get(
    "CATEGORY_V6_WIKIPEDIA_CACHE", "./cache/category_v6_wikipedia_leads.json"
)

# The locally cached model. v6 never asks for a different one: swapping encoders
# would change every raw_sbert value in the corpus, and no measurement in this
# project justifies that cost.
DEFAULT_SBERT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# HARD feasibility thresholds, unchanged from v5 so that a v5 and a v6 rejection
# of the same class mean the same thing.
DEFAULT_MIN_REMOTE_CANDIDATES = 10     # eligible members, i.e. excluding the Answer
DEFAULT_MAX_REMOTE_CANDIDATES = 5000   # the declared broad-category maximum

DEFAULT_CATEGORY_LIMIT = 200           # max dcterms:subject values fetched per Answer
DEFAULT_COUNT_BATCH_SIZE = 100         # categories per COUNT query

# WHY 0.7 IS THE DEFAULT AND WHY THAT IS NOT AN OPTIMALITY CLAIM
#   0.7 is the PRE-SPECIFIED MAIN WORKING CONFIGURATION selected by the
#   researcher after the development sensitivity analysis and fixed BEFORE the
#   ~100-Answer downstream experiment. It is not claimed to be an optimum, is not
#   claimed to be statistically better than any other value, and was not selected
#   by optimising a downstream outcome: choosing a "best" alpha from a handful of
#   development Answers would be fitting a hyper-parameter on a sample far too
#   small to support the claim.
#
#   Fixing it in advance is what the pre-specification buys. A class choice made
#   after inspecting six weightings would be a post-hoc selection; a class choice
#   made at one declared weighting is a measurement whose configuration is on the
#   record. Earlier development runs used 0.5, the neutral equal weighting, and
#   that evidence is retained — SWEEP_ALPHAS still contains 0.5 and the recorded
#   six-alpha sweeps are not deleted or re-run.
DEFAULT_ALPHA = 0.7

# The exact sensitivity grid this phase reports (Prompt §K). Unchanged: the
# sweep is the sensitivity evidence and its grid must not move when the main
# working configuration is chosen from inside it.
SWEEP_ALPHAS: tuple[float, ...] = (0.0, 0.25, 0.5, 0.7, 0.75, 1.0)

CATEGORY_PREFIX = "http://dbpedia.org/resource/Category:"
RESOURCE_PREFIX = "http://dbpedia.org/resource/"
ALLOWED_CATEGORY_PREFIXES = (
    CATEGORY_PREFIX,
    "https://dbpedia.org/resource/Category:",
)

DEFAULT_QUALITY_POLICY_PATH = (
    Path(__file__).resolve().parent
    / "rationale_v3" / "policies" / "predicate_policy.json"
)

LEAKAGE_SOURCE_R1 = "rationale_v3_r1"

# Wikipedia maintenance / administrative categories. Copied verbatim from v5 so
# that "junk" means exactly what it already meant; changing the set would change
# the denominator of every feasibility statistic in the project.
JUNK_CATEGORY_PATTERNS = (
    r"^Living_people$",
    r"^\d{3,4}_births$",
    r"^\d{3,4}_deaths$",
    r"^Year_of_(birth|death)_",
    r"^People_from_",
    r"^Date_of_(birth|death)_",
    r"^(All|Articles|Pages|Wikipedia|CS1|Use_|Webarchive|Commons)",
    r"_stubs$",
    r"_missing$",
    r"_needing_",
    r"_with_unsourced_",
    r"^\d{1,2}(st|nd|rd|th)-century_(births|deaths)$",
)
_JUNK_RE = re.compile("|".join(JUNK_CATEGORY_PATTERNS))


class RejectCode(str, Enum):
    """Why a class was refused. A rejected class NEVER receives a feasible rank.

    Giving a rejected class a rank would put a number the ranking policy never
    computed next to a class the policy already excluded, and any reader sorting
    by that column would silently resurrect it.
    """

    INVALID_URI = "invalid_category_uri"
    JUNK = "junk_category"
    COUNT_UNAVAILABLE = "remote_count_unavailable"
    TOO_SMALL = "insufficient_remote_candidates"
    TOO_GENERIC = "too_generic"
    HARD_LEAK = "hard_leak"


class QueryStatus(str, Enum):
    """Four SPARQL outcomes that must never be collapsed into one another.

    ``PARTIAL`` exists because the public DBpedia endpoint is a Virtuoso
    "anytime" server: when a query exceeds its result timeout it returns HTTP
    200 with a syntactically valid but INCOMPLETE answer, flagged only in the
    ``X-SQL-State: S1TAT`` response header. Measured on this endpoint, the
    category-universe COUNT returned 590,799 on one attempt and 3,099,179 on
    another, both marked incomplete. Treating either as a measurement would put
    a number in the provenance record that the endpoint itself disclaims.
    """

    OK = "ok"
    ZERO_RESULTS = "zero_results"
    PARTIAL = "partial_results"
    FAILED = "query_failed"


class CacheStatus(str, Enum):
    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"
    DISABLED = "disabled"


class LeakLevel(str, Enum):
    NONE = "no_leak"
    SOFT = "soft_overlap"
    HARD = "hard_leak"


class LeakStatus(str, Enum):
    """Whether a leakage verdict was COMPUTED for this class.

    ``LeakLevel.NONE`` means "the rules ran and found nothing". It must never be
    readable as "the rules did not run": the two license opposite conclusions,
    and conflating them is what published ``Aristotle`` / ``Category:Aristotle``
    as ``no_leak`` when the class had simply been rejected on size before the
    leakage test was reached.
    """

    EVALUATED = LEAK_STATUS_EVALUATED
    NOT_EVALUATED = LEAK_STATUS_NOT_EVALUATED


class SemanticSource(str, Enum):
    """Which text supplies the semantic query vector. One per run, never mixed."""

    WIKIPEDIA_LEAD = "wikipedia_lead"
    DBPEDIA_DESCRIPTION = "dbpedia_description"


class SemanticStatus(str, Enum):
    """Whether a usable semantic text exists, and if not, why not.

    ``UNAVAILABLE`` is deliberately NOT representable as a cosine similarity.
    Encoding "no text" as 0.0 would make an Answer with no Wikipedia page
    indistinguishable from an Answer whose lead is genuinely orthogonal to every
    class label, and the two support opposite conclusions about coverage.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "SEMANTIC_TEXT_UNAVAILABLE"
    ENCODER_UNAVAILABLE = "SEMANTIC_ENCODER_UNAVAILABLE"


class ScoringMode(str, Enum):
    """How ``combined_score`` was actually produced for one Answer.

    Stamped on every output row so that an IDF-only fallback can never be read
    as a rank-fusion result. This is the field that would have made the
    Prompt 8H-B2-B Einstein run self-describing.
    """

    RANK_FUSION = "rank_fusion_idf_and_sbert"
    IDF_ONLY_BY_ALPHA = "idf_only_alpha_zero"
    IDF_ONLY_SEMANTIC_UNAVAILABLE = "idf_only_semantic_unavailable"
    # No class survived Stage 1, so there was nothing to score. Kept distinct
    # from IDF_ONLY_SEMANTIC_UNAVAILABLE because the causes are opposite: here
    # the semantic text may be perfectly available and there is simply nothing
    # to compare it against. Merging the two would report a semantic-coverage
    # gap that does not exist.
    NO_FEASIBLE_CLASS = "no_feasible_class_to_score"


# ---------------------------------------------------------------------------
# 1) URI VALIDATION AND SPARQL QUERY BUILDERS — pure, testable offline
#
# Values are REFUSED rather than escaped. An escaping bug can produce a query
# that parses differently than intended; a refusal cannot.
# ---------------------------------------------------------------------------

# SPARQL 1.1 IRIREF grammar rule [139] forbids exactly this set inside <...>,
# widened here to Unicode whitespace and C1 controls. An apostrophe is legal and
# is deliberately absent, so <.../Shin'ichirō_Tomonaga> is accepted.
_UNSAFE_IRIREF_CHARS = re.compile(r"""[\s<>"{}|\\^`]|[\x00-\x20\x7f-\x9f]""")
_SCHEME_RE = re.compile(r"^https?://[^/]+/")


def strip_brackets(uri: str) -> str:
    return (uri or "").strip().strip("<>").strip()


def is_safe_uri(value: Optional[str]) -> bool:
    """True when ``value`` is an http(s) IRI safe to interpolate inside ``<...>``.

    The Unicode string is preserved exactly. A value that passes is interpolated
    verbatim and never percent-encoded, because a percent-encoded spelling is a
    DIFFERENT RDF term, not an encoding of the same one.
    """
    if not value:
        return False
    text = strip_brackets(str(value))
    if not text or _UNSAFE_IRIREF_CHARS.search(text):
        return False
    return bool(_SCHEME_RE.match(text))


def validate_iri(value: Optional[str], *, what: str = "URI") -> str:
    if not is_safe_uri(value):
        raise ValueError(f"unsafe or malformed {what}: {value!r}")
    return strip_brackets(str(value))


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Canonicalise ``dbc:X`` / ``Category:X`` / a full category URI / a bare name.

    Returns the canonical full category URI, or ``None`` when the value cannot
    denote a DBpedia category. Strict, because the result is interpolated into a
    query: another host, a resource URI that merely CONTAINS "Category:", a local
    name containing "/", and anything with an IRI-terminating character are all
    refused. A ``:`` inside the local name is legitimate and preserved, so
    ``Category:Star_Trek:_Voyager_episodes`` survives — only the LEADING
    ``dbc:``/``Category:`` token is treated as a namespace marker.
    """
    if value is None:
        return None
    raw = strip_brackets(str(value))
    if not raw:
        return None

    if "://" in raw or raw.lower().startswith(("http:", "https:", "ftp:", "file:")):
        if _UNSAFE_IRIREF_CHARS.search(raw):
            return None
        for prefix in ALLOWED_CATEGORY_PREFIXES:
            if raw.startswith(prefix):
                local = raw[len(prefix):]
                break
        else:
            return None
    else:
        if raw.startswith("dbc:"):
            local = raw[4:]
        elif raw.startswith("Category:"):
            local = raw[len("Category:"):]
        else:
            local = raw
        local = local.strip().replace(" ", "_")

    if not local or _UNSAFE_IRIREF_CHARS.search(local) or "/" in local:
        return None
    candidate = CATEGORY_PREFIX + local
    return candidate if is_safe_uri(candidate) else None


QID_PREFIX = "#qid:"
_PREFIXES = (
    "PREFIX dct:  <http://purl.org/dc/terms/>\n"
    "PREFIX dbo:  <http://dbpedia.org/ontology/>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>"
)


def query_id(query: str) -> Optional[str]:
    """The ``#qid:`` marker of a query, so provenance need not substring-match."""
    for line in query.splitlines():
        stripped = line.strip()
        if stripped.startswith(QID_PREFIX):
            return stripped[len(QID_PREFIX):].strip()
    return None


def build_answer_info_query(answer_uri: str, *, language: str = DEFAULT_LANGUAGE) -> str:
    """The Answer's English label and English ``dbo:description``, in one query.

    ``dbo:description`` is fetched on EVERY run, whatever ``--semantic-source``
    says, because the coverage census must compare the availability of both
    semantic sources over the same Answers. Fetching it only in
    ``dbpedia_description`` mode would make the census a comparison between two
    different populations.
    """
    subject = validate_iri(answer_uri, what="answer URI")
    lang = _validate_language(language)
    return f"""{QID_PREFIX} answer_info
{_PREFIXES}
SELECT ?label ?description WHERE {{
  OPTIONAL {{ <{subject}> rdfs:label ?label . FILTER(lang(?label) = '{lang}') }}
  OPTIONAL {{ <{subject}> dbo:description ?description . FILTER(lang(?description) = '{lang}') }}
}}
"""


def build_answer_categories_query(
    answer_uri: str, *, limit: int = DEFAULT_CATEGORY_LIMIT
) -> str:
    """Every ``dcterms:subject`` category of the Answer, deterministically ordered.

    ``ORDER BY`` accompanies ``LIMIT`` so that a truncated list is the same
    prefix on every run rather than an arbitrary sample.
    """
    subject = validate_iri(answer_uri, what="answer URI")
    return f"""{QID_PREFIX} answer_categories
{_PREFIXES}
SELECT DISTINCT ?cat WHERE {{
  <{subject}> dct:subject ?cat .
  FILTER(STRSTARTS(STR(?cat), "{CATEGORY_PREFIX}"))
}} ORDER BY ?cat LIMIT {int(limit)}
"""


def build_category_counts_query(category_uris: Sequence[str]) -> str:
    """``n_c`` for a batch of categories: COUNT(DISTINCT entity) per category.

    This is the quantity the IDF denominator uses, and it counts the FULL class
    including the Answer. The eligible-candidate threshold is applied to a
    different number (``remote_count - 1``); the two are kept separate because
    conflating them would silently change either the size gate or the IDF.
    """
    if not category_uris:
        raise ValueError("at least one category URI is required")
    values = " ".join(
        f"<{validate_iri(c, what='category URI')}>" for c in category_uris
    )
    return f"""{QID_PREFIX} category_counts
{_PREFIXES}
SELECT ?cat (COUNT(DISTINCT ?x) AS ?c) WHERE {{
  VALUES ?cat {{ {values} }}
  ?x dct:subject ?cat .
}} GROUP BY ?cat ORDER BY ?cat
"""


def build_idf_universe_query() -> str:
    """The SPECIFIED IDF universe: distinct resources with a Category membership.

    This is the query §G asks for. Measured against the live public endpoint it
    does NOT complete: Virtuoso's anytime limit interrupts it and returns an
    incomplete count (see :class:`QueryStatus`). v6 therefore tries it first,
    detects the incompleteness, and falls back to
    :func:`build_idf_universe_query_unfiltered` with that fallback recorded
    explicitly in the provenance file — it never passes an incomplete count off
    as a measurement.
    """
    return f"""{QID_PREFIX} idf_universe_category_filtered
SELECT (COUNT(DISTINCT ?e) AS ?N) WHERE {{
  ?e <http://purl.org/dc/terms/subject> ?c .
  FILTER(STRSTARTS(STR(?c), "{CATEGORY_PREFIX}"))
}}
"""


def build_idf_universe_query_unfiltered() -> str:
    """The answerable IDF universe: distinct resources with ANY ``dct:subject``.

    The ``STRSTARTS`` filter above is what makes the specified query intractable
    for the endpoint; without it the same COUNT completes in about 27 seconds and
    is not flagged incomplete. Because a small number of ``dct:subject`` objects
    on this endpoint are not Category URIs, this count is a strict UPPER BOUND on
    the Category-only universe, and the provenance record says so in those words.

    Using an upper bound costs nothing for the purpose N serves here. IDF(c) =
    log(N) - log(n_c) is strictly decreasing in n_c for any fixed N > 0, so with
    N held constant across the whole run the class ORDER — which is the only
    thing the selector consumes — is completely invariant to which admissible N
    was chosen. N affects only the printed magnitude of ``raw_idf``.
    """
    return f"""{QID_PREFIX} idf_universe_unfiltered
SELECT (COUNT(DISTINCT ?e) AS ?N) WHERE {{
  ?e <http://purl.org/dc/terms/subject> ?c .
}}
"""


_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")


def _validate_language(value: Optional[str]) -> str:
    text = (value or "").strip()
    if not _LANGUAGE_RE.match(text):
        raise ValueError(f"unsafe or malformed language tag: {value!r}")
    return text


def binding_value(row: Mapping[str, Any], key: str) -> Optional[str]:
    """Read one SPARQL-JSON binding cell, tolerating the plain-string shape."""
    cell = row.get(key)
    if isinstance(cell, Mapping):
        value = cell.get("value")
        return None if value is None else str(value)
    return None if cell is None else str(cell)


# ---------------------------------------------------------------------------
# 2) SPARQL TRANSPORT — injectable client, injectable cache, no import-time I/O
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryResult:
    """Outcome of one SPARQL request, with the provenance an audit needs.

    ``rows`` uses the SPARQL-JSON binding shape ``{"var": {"value": "..."}}`` so
    that a fake client in a unit test has the same shape as the real endpoint.
    """

    status: QueryStatus
    rows: tuple[Mapping[str, Any], ...] = ()
    error: Optional[str] = None
    query_hash: str = ""
    query_id: Optional[str] = None
    endpoint: str = ""
    retrieved_at: Optional[str] = None
    cache_status: CacheStatus = CacheStatus.DISABLED
    http_status: Optional[int] = None
    sql_state: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status is QueryStatus.OK

    @property
    def usable(self) -> bool:
        """True when the rows may be read as a complete answer.

        A PARTIAL result is explicitly NOT usable: it is a prefix of an answer
        the endpoint declined to finish computing.
        """
        return self.status in (QueryStatus.OK, QueryStatus.ZERO_RESULTS)


class SparqlCache(Protocol):
    def get(self, key: str) -> Optional[Mapping[str, Any]]:  # pragma: no cover
        ...

    def put(self, key: str, record: Mapping[str, Any]) -> bool:  # pragma: no cover
        ...


def compute_query_hash(endpoint: str, query: str) -> str:
    return hashlib.sha256(f"{endpoint}\n{query}".encode("utf-8")).hexdigest()


def _cacheable(status_value: str) -> bool:
    """Only a COMPLETE answer may be cached.

    A failure must not be replayed as data, and a Virtuoso partial result must
    not be frozen into the cache — a cached partial count would be reused
    forever as though the endpoint had finished the query.
    """
    return status_value in (QueryStatus.OK.value, QueryStatus.ZERO_RESULTS.value)


class InMemorySparqlCache:
    """Process-local cache. Used by tests and by an offline replay harness."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Mapping[str, Any]]:
        return self._rows.get(key)

    def put(self, key: str, record: Mapping[str, Any]) -> bool:
        if not _cacheable(str(record.get("query_status"))):
            return False
        self._rows[key] = dict(record)
        return True

    def __len__(self) -> int:
        return len(self._rows)


class SqliteSparqlCache:
    """SQLite response cache. The connection opens on first use, never at import.

    A file whose ``meta.schema_version`` was not written by THIS version is
    refused rather than migrated or repaired, which is what protects the v3/v5
    caches from being altered by a v6 run.
    """

    _REQUIRED_TABLES = frozenset({"responses", "meta"})

    def __init__(self, path: str | os.PathLike[str] = DEFAULT_CACHE_PATH, *,
                 endpoint: str = DEFAULT_ENDPOINT) -> None:
        self.path = str(path)
        self.endpoint = endpoint
        self.schema_version = CACHE_SCHEMA_VERSION
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        target = Path(self.path)
        if str(target.parent) not in ("", "."):
            target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)

        def refuse(reason: str) -> RuntimeError:
            conn.close()
            return RuntimeError(f"{self.path!r} {reason}")

        try:
            existing = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")
            }
        except sqlite3.DatabaseError as exc:
            raise refuse(f"is not a readable SQLite database: {exc}") from exc

        if existing:
            # An existing database is validated COMPLETELY before anything is
            # written to it, so a file that turns out to be foreign is never
            # left with a v6 table stamped into it.
            if "meta" not in existing:
                raise refuse(
                    f"contains tables {sorted(existing)} but no 'meta' table; "
                    "refusing to write to a cache produced by another schema")
            row = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None or row[0] != self.schema_version:
                raise refuse(
                    f"has schema_version {None if row is None else row[0]!r}, "
                    f"expected {self.schema_version!r}")
            missing = sorted(self._REQUIRED_TABLES - existing)
            if missing:
                raise refuse(f"is missing table(s) {missing}")
            self._conn = conn
            return conn

        conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " query_hash TEXT PRIMARY KEY,"
            " endpoint TEXT NOT NULL,"
            " query_id TEXT,"
            " response_json TEXT NOT NULL,"
            " query_status TEXT NOT NULL,"
            " retrieved_at TEXT NOT NULL,"
            " schema_version TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            [("schema_version", self.schema_version),
             ("created_at", iso_utc()),
             ("endpoint", self.endpoint)],
        )
        conn.commit()
        self._conn = conn
        return conn

    def get(self, key: str) -> Optional[Mapping[str, Any]]:
        row = self._connect().execute(
            "SELECT endpoint, query_id, response_json, query_status, retrieved_at"
            " FROM responses WHERE query_hash=?", (key,)).fetchone()
        if row is None:
            return None
        return {"endpoint": row[0], "query_id": row[1], "response_json": row[2],
                "query_status": row[3], "retrieved_at": row[4]}

    def put(self, key: str, record: Mapping[str, Any]) -> bool:
        if not _cacheable(str(record.get("query_status"))):
            return False
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?,?,?)",
            (key, record["endpoint"], record.get("query_id"),
             record["response_json"], record["query_status"],
             str(record.get("retrieved_at") or iso_utc()), self.schema_version))
        conn.commit()
        return True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __len__(self) -> int:
        return int(self._connect().execute(
            "SELECT COUNT(*) FROM responses").fetchone()[0])


class SparqlClientProtocol(Protocol):
    endpoint: str

    def run(self, query: str) -> QueryResult:  # pragma: no cover
        ...


# Virtuoso reports an interrupted anytime query in these two headers. S1TAT is
# the SQL state for "result timeout"; the message repeats it in prose. Both are
# checked, because relying on a single vendor header to stay stable would make a
# silent regression into a silent scientific error.
_VIRTUOSO_PARTIAL_SQL_STATES = frozenset({"S1TAT"})
_VIRTUOSO_PARTIAL_MESSAGE = "returning incomplete results"


@dataclass
class HttpSparqlClient:
    """Live DBpedia transport that can SEE a partial result.

    WHY NOT SPARQLWrapper
        SPARQLWrapper hands back the parsed body and discards the response
        headers, which is exactly where Virtuoso records that it interrupted the
        query. A client that cannot read ``X-SQL-State`` cannot tell a finished
        COUNT from an abandoned one, and this project needs that distinction for
        the single most important run-level constant it measures.

    ``requests`` is imported lazily inside :meth:`run`, so importing this module
    pulls in no HTTP machinery.
    """

    endpoint: str = DEFAULT_ENDPOINT
    user_agent: str = (
        "mcq-journal2-category-selector-v6/1.0 "
        "(research: MCQ distractor generation from knowledge graphs; "
        "contact: redaiprojects289@gmail.com)"
    )
    connect_timeout: float = 10.0
    read_timeout: float = 180.0
    anytime_timeout_ms: Optional[int] = None
    retries: int = 3
    backoff_cap: float = 30.0
    sleep: Any = time.sleep
    _session: Any = field(default=None, repr=False, compare=False)

    def run(self, query: str) -> QueryResult:
        import requests  # lazy: keeps module import network-free

        if self._session is None:
            self._session = requests.Session()
        data = {"query": query, "format": "application/sparql-results+json"}
        if self.anytime_timeout_ms:
            data["timeout"] = str(int(self.anytime_timeout_ms))

        last_error: Optional[str] = None
        last_status: Optional[int] = None
        for attempt in range(max(1, self.retries)):
            try:
                response = self._session.post(
                    self.endpoint, data=data,
                    headers={"User-Agent": self.user_agent,
                             "Accept": "application/sparql-results+json"},
                    timeout=(self.connect_timeout, self.read_timeout))
            except Exception as exc:  # noqa: BLE001 - transport errors are data
                last_error = f"transport_exception: {exc!r}"
            else:
                last_status = int(response.status_code)
                if last_status in (200, 206):
                    # 206 is how this Virtuoso reports an anytime query it
                    # interrupted: the body parses but is incomplete. It is
                    # classified as PARTIAL, never retried (repeating it would
                    # only spend another 30-120 endpoint-seconds to be
                    # interrupted again) and never cached.
                    return self._classify(response)
                last_error = f"http_status: {last_status}"
            if attempt < self.retries - 1:
                self.sleep(min(2.0 ** attempt, self.backoff_cap))
        return QueryResult(status=QueryStatus.FAILED, error=last_error,
                           endpoint=self.endpoint, query_id=query_id(query),
                           http_status=last_status)

    def _classify(self, response: Any) -> QueryResult:
        """Decide OK / ZERO_RESULTS / PARTIAL / FAILED from status AND headers.

        Three independent signals mark an interrupted anytime query, and any one
        of them is enough: HTTP 206, ``X-SQL-State: S1TAT``, or an
        ``X-SQL-Message`` saying the results are incomplete. Requiring all three
        would let a single vendor change turn a truncated count into a silently
        accepted measurement.
        """
        status_code = int(response.status_code)
        sql_state = response.headers.get("X-SQL-State")
        message = (response.headers.get("X-SQL-Message") or "").lower()
        partial = (status_code == 206
                   or sql_state in _VIRTUOSO_PARTIAL_SQL_STATES
                   or _VIRTUOSO_PARTIAL_MESSAGE in message)
        try:
            payload = response.json()
            rows = tuple(payload["results"]["bindings"])
        except Exception as exc:  # noqa: BLE001
            return QueryResult(status=QueryStatus.FAILED,
                               error=f"malformed_sparql_results: {exc!r}",
                               endpoint=self.endpoint, http_status=status_code,
                               sql_state=sql_state)
        if partial:
            return QueryResult(
                status=QueryStatus.PARTIAL, rows=rows, endpoint=self.endpoint,
                http_status=status_code, sql_state=sql_state,
                error=(response.headers.get("X-SQL-Message")
                       or f"endpoint reported incomplete results "
                          f"(HTTP {status_code})"))
        return QueryResult(
            status=QueryStatus.OK if rows else QueryStatus.ZERO_RESULTS,
            rows=rows, endpoint=self.endpoint, http_status=status_code,
            sql_state=sql_state)


@dataclass
class SparqlRunner:
    """A client plus an optional cache plus provenance counters.

    Only complete answers are read from or written to the cache, so a replay can
    never inherit a failure or a partial result from an earlier run.
    """

    client: SparqlClientProtocol
    cache: Optional[SparqlCache] = None
    bypass: bool = False
    n_queries: int = 0
    n_cache_hits: int = 0
    n_client_calls: int = 0
    n_failed: int = 0
    n_partial: int = 0
    n_zero_results: int = 0

    @property
    def endpoint(self) -> str:
        return getattr(self.client, "endpoint", DEFAULT_ENDPOINT)

    def run(self, query: str) -> QueryResult:
        self.n_queries += 1
        key = compute_query_hash(self.endpoint, query)
        qid = query_id(query)

        if self.cache is not None and not self.bypass:
            record = self.cache.get(key)
            if record is not None:
                self.n_cache_hits += 1
                status = QueryStatus(record["query_status"])
                if status is QueryStatus.ZERO_RESULTS:
                    self.n_zero_results += 1
                return QueryResult(
                    status=status,
                    rows=tuple(json.loads(record["response_json"])),
                    query_hash=key, query_id=qid,
                    endpoint=record.get("endpoint", self.endpoint),
                    retrieved_at=record.get("retrieved_at"),
                    cache_status=CacheStatus.HIT)

        self.n_client_calls += 1
        try:
            result = self.client.run(query)
        except Exception as exc:  # noqa: BLE001
            result = QueryResult(status=QueryStatus.FAILED, error=repr(exc))

        status = result.status
        if status is QueryStatus.OK and not result.rows:
            status = QueryStatus.ZERO_RESULTS
        if status is QueryStatus.FAILED:
            self.n_failed += 1
        elif status is QueryStatus.PARTIAL:
            self.n_partial += 1
        elif status is QueryStatus.ZERO_RESULTS:
            self.n_zero_results += 1

        retrieved_at = iso_utc()
        if self.cache is None:
            cache_status = CacheStatus.DISABLED
        elif self.bypass:
            cache_status = CacheStatus.BYPASS
        else:
            cache_status = CacheStatus.MISS
            self.cache.put(key, {
                "endpoint": self.endpoint,
                "query_id": qid,
                "response_json": json.dumps([dict(r) for r in result.rows]),
                "query_status": status.value,
                "retrieved_at": retrieved_at,
            })

        return QueryResult(
            status=status, rows=tuple(result.rows), error=result.error,
            query_hash=key, query_id=qid, endpoint=self.endpoint,
            retrieved_at=retrieved_at, cache_status=cache_status,
            http_status=result.http_status, sql_state=result.sql_state)

    def stats(self) -> dict[str, int]:
        return {"queries": self.n_queries, "cache_hits": self.n_cache_hits,
                "client_calls": self.n_client_calls, "failed": self.n_failed,
                "partial": self.n_partial, "zero_results": self.n_zero_results}


def make_dbpedia_runner(*, endpoint: str = DEFAULT_ENDPOINT,
                        cache_path: Optional[str] = DEFAULT_CACHE_PATH,
                        bypass: bool = False,
                        anytime_timeout_ms: Optional[int] = None) -> SparqlRunner:
    """Build a LIVE runner. Calling this is the explicit opt-in to network use."""
    cache = SqliteSparqlCache(cache_path, endpoint=endpoint) if cache_path else None
    client = HttpSparqlClient(endpoint=endpoint, anytime_timeout_ms=anytime_timeout_ms)
    return SparqlRunner(client=client, cache=cache, bypass=bypass)


# ---------------------------------------------------------------------------
# 3) LABELS AND THE FROZEN R1 HARD-LEAKAGE GATE
# ---------------------------------------------------------------------------


def category_uri_to_resource_uri(category_uri: Optional[str]) -> Optional[str]:
    """Adapt a category URI to the resource-style spelling R1 was measured on.

    ``.../resource/Category:Einstein_family`` -> ``.../resource/Einstein_family``

    R1 was built for RATIONALE-FACT counterparts, whose URIs already live
    directly under ``/resource/``. Its tokeniser reads a URI's local name, so
    handing it a raw category URI would tokenise ``Category:Einstein_family`` —
    a shape R1 was never measured against, and one that is not obviously safe for
    a category whose own local name contains a colon.

    Exactly one mechanical, reversible rewrite is performed: the LEADING
    ``Category:`` namespace marker is removed. Nothing is stemmed, no
    parenthetical or Roman numeral is touched, and no percent escape is decoded
    or re-encoded, so a legitimately encoded local name passes through
    byte-for-byte. The result feeds :func:`classify_class_leakage` and nothing
    else; it is never displayed and never denotes a real resource.
    """
    canonical = normalize_category(category_uri)
    if canonical is None or not canonical.startswith(CATEGORY_PREFIX):
        return None
    resource_uri = RESOURCE_PREFIX + canonical[len(CATEGORY_PREFIX):]
    return resource_uri if is_safe_uri(resource_uri) else None


def category_display_label(category_uri: str) -> str:
    """Human-readable label for a category, via the frozen display normaliser.

    Underscores become spaces and percent escapes are decoded; parentheses,
    Roman numerals, digits, diacritics and case survive unchanged, so
    ``Iron(III)_compounds`` does not become ``Iron compounds``. This is
    :func:`rationale_v3.quality.display_label` — the same function the rationale
    layer renders choices with — applied after the ``Category:`` marker is
    dropped. Display normalisation and leakage normalisation stay separate
    functions answering separate questions ("what should a human read?" versus
    "is this comparable for leakage?").
    """
    canonical = normalize_category(category_uri)
    if canonical is None:
        return display_label(str(category_uri))
    return display_label(RESOURCE_PREFIX + canonical[len(CATEGORY_PREFIX):])


def answer_display_label(answer_uri: str, rdfs_label: Optional[str] = None) -> str:
    """The Answer's label: its English ``rdfs:label`` when the endpoint has one,
    otherwise the same deterministic URI-derived label used for classes."""
    if rdfs_label and str(rdfs_label).strip():
        return str(rdfs_label).strip()
    return display_label(str(answer_uri))


@dataclass(frozen=True)
class LeakVerdict:
    """R1's verdict for one Answer/class pair, with its own evidence."""

    level: LeakLevel
    reason: Optional[str] = None
    evidence: tuple[str, ...] = ()
    source: str = LEAKAGE_SOURCE_R1

    @property
    def is_hard(self) -> bool:
        return self.level is LeakLevel.HARD


_R1_POLICY_CACHE: dict[str, QualityPolicy] = {}


def load_r1_leakage_policy(
    path: Optional[str | os.PathLike[str]] = None,
) -> QualityPolicy:
    """Load (and memoise) the frozen R1 quality/leakage policy.

    Lazy on purpose: reading the policy file is an action a caller takes when it
    first needs a leakage decision, never a side effect of importing this module.
    The four thresholds (minimum token length, HARD/SOFT prefix lengths, plural
    suffixes) are read from this pinned, SHA-256-recorded file and are never
    duplicated as constants here.
    """
    target = Path(path) if path is not None else DEFAULT_QUALITY_POLICY_PATH
    key = str(target)
    cached = _R1_POLICY_CACHE.get(key)
    if cached is None:
        cached = load_quality_policy(target)
        _R1_POLICY_CACHE[key] = cached
    return cached


def classify_class_leakage(answer_uri: str, category_uri: str, *,
                           policy: QualityPolicy) -> LeakVerdict:
    """The AUTHORITATIVE HARD/SOFT/NONE verdict for one Answer/class pair.

    The verdict comes exclusively from
    :func:`rationale_v3.quality.detect_answer_leakage` run over the Answer URI
    and the resource-style adaptation of the category URI. No model of any kind
    participates: WordNet, spaCy, sentence embeddings and LLMs are not imported
    by this module, so a HARD rejection cannot be produced or overturned by one.

    HARD rejects the class. SOFT only annotates and may inform ranking — a
    4-character shared prefix (``Carbon``/``Boron_carbide`` sharing ``carb``) is
    not evidence that the class names the Answer, and rejecting on it would
    narrow the candidate pool on a false-positive-prone signal.

    A category URI that cannot be adapted returns ``NONE`` rather than raising,
    so this function is total; in this module it is only ever reached by a URI
    that already passed :func:`normalize_category`.
    """
    adapted = category_uri_to_resource_uri(category_uri)
    if adapted is None:
        return LeakVerdict(LeakLevel.NONE,
                           "category URI could not be adapted for the R1 comparison")
    result = detect_answer_leakage(answer_uri, adapted, policy)
    if result.hard_leak:
        level = LeakLevel.HARD
    elif result.soft_leak:
        level = LeakLevel.SOFT
    else:
        level = LeakLevel.NONE
    return LeakVerdict(
        level=level, reason=result.reason_code,
        evidence=tuple(f"{a}~{b}:{kind}" for a, b, kind in result.matches))


def classify_class_leakage_extended(
    answer_uri: str, category_uri: str, *, policy: QualityPolicy,
    derivational: DerivationalPolicy = DEFAULT_DERIVATIONAL_POLICY,
) -> ClassLeakVerdict:
    """The verdict the SELECTOR acts on: frozen R1, then the class-only rule.

    This is the only leakage entry point the feasibility gate calls.
    :func:`classify_class_leakage` above is kept unchanged and R1-only, because
    the delta audit needs to report both verdicts for the same pair, and because
    "what did the frozen rule alone say?" must remain answerable without
    reconstructing an earlier version of this module.

    The returned :class:`ClassLeakVerdict` carries BOTH verdicts plus a
    ``status``: an unadaptable category URI yields
    ``NOT_EVALUATED_UNADAPTABLE_CATEGORY_URI``, never a silent ``no_leak``. In
    this module that branch is unreachable — every URI reaching here already
    passed :func:`normalize_category` — but it is the branch that keeps the
    function total and keeps the output vocabulary honest for any other caller.
    """
    adapted = category_uri_to_resource_uri(category_uri)
    if adapted is None:
        return not_evaluated_verdict(
            "category URI could not be adapted for the leakage comparison")
    return _classify_class_leakage_extended(
        answer_uri, adapted, policy, derivational=derivational)


# ---------------------------------------------------------------------------
# 4) SCORING PRIMITIVES — pure functions
#
# TF is 1 for every category-membership relation under consideration, so the
# lexical component is IDF, not TF-IDF.
# ---------------------------------------------------------------------------


def standard_idf(member_count: int, total_entities: int) -> float:
    """Conventional inverse document frequency: ``log(N / n_c)``.

    v5 recorded ``log(N/n_c)/log(N)`` under the name ``raw_idf``. That is this
    quantity divided by the positive constant ``log(N)``. For a FIXED N the two
    are strictly monotonic transformations of each other and induce the same
    ordering, and after the within-Answer rank normalisation both versions apply
    they are numerically identical — which is why no ablation between them is run
    or would be meaningful.

    Raises ``ValueError`` rather than substituting a default for a
    non-positive count or universe: a silently defaulted N is precisely the
    failure this version exists to remove.
    """
    if member_count is None or int(member_count) < 1:
        raise ValueError(f"member count must be >= 1, got {member_count!r}")
    if total_entities is None or int(total_entities) < 1:
        raise ValueError(f"total entities must be >= 1, got {total_entities!r}")
    return math.log(int(total_entities) / int(member_count))


def rank_normalize(values: Sequence[float]) -> list[float]:
    """Average-rank normalisation onto [0, 1]; larger is better.

    Rank normalisation rather than raw values, because IDF spreads over a wide
    range while SBERT cosine similarity concentrates in a narrow band: adding the
    raw quantities would let IDF dominate at every alpha. Ties receive the same
    normalised value, which makes the result independent of the order the
    endpoint happened to return the categories in.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: (values[i], i))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return [r / (n - 1) for r in ranks]


def validate_alpha(alpha: float) -> float:
    """Accept only ``0 <= alpha <= 1``. Anything else is a usage error."""
    try:
        value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"alpha must be a number, got {alpha!r}") from exc
    if not (0.0 <= value <= 1.0) or math.isnan(value):
        raise ValueError(f"alpha must satisfy 0 <= alpha <= 1, got {value!r}")
    return value


def combine_alpha(normalized_sbert: Optional[float], normalized_idf: float,
                  alpha: float) -> float:
    """``alpha * normalized_sbert + (1 - alpha) * normalized_idf``.

    ``normalized_sbert is None`` means no semantic feature exists for this
    Answer. The score then falls back to the IDF component alone — and the caller
    MUST stamp :attr:`ScoringMode.IDF_ONLY_SEMANTIC_UNAVAILABLE` on the row, so
    that the fallback is visible in the output rather than hidden inside a number
    that looks like a fusion score.
    """
    alpha = validate_alpha(alpha)
    if normalized_sbert is None:
        return normalized_idf
    return alpha * float(normalized_sbert) + (1.0 - alpha) * float(normalized_idf)


# ---------------------------------------------------------------------------
# 5) THE IDF UNIVERSE — measured ONCE per run, never once per Answer
# ---------------------------------------------------------------------------

UNIVERSE_EXPLICIT = "EXPLICIT_CLI_OVERRIDE"
UNIVERSE_CATEGORY_FILTERED = "DCTERMS_SUBJECT_CATEGORY_FILTERED"
UNIVERSE_UNFILTERED_UPPER_BOUND = "DCTERMS_SUBJECT_ANY_OBJECT_UPPER_BOUND"
UNIVERSE_UNAVAILABLE = "IDF_UNIVERSE_UNAVAILABLE"


@dataclass(frozen=True)
class IdfUniverse:
    """The single run-level N, with everything needed to reproduce or refuse it.

    WHY ONE QUERY PER RUN AND NOT ONE PER ANSWER
        N is a property of the endpoint's whole graph, not of an Answer. Querying
        it per Answer would multiply a ~30-second query by the corpus size AND
        would let N drift mid-run, so two Answers scored in the same experiment
        could carry incomparable IDF values. One measurement, recorded once,
        applied to every Answer.

    WHY THE RANKING DOES NOT DEPEND ON WHICH ADMISSIBLE N WAS USED
        ``IDF(c) = log(N) - log(n_c)`` is strictly decreasing in n_c for any
        fixed N > 0. Holding N constant across the run therefore fixes the class
        ORDER completely: N shifts every raw_idf by the same additive constant
        and vanishes entirely under rank normalisation. N is reported because a
        published IDF should be reproducible, not because the ranking is
        sensitive to it.
    """

    total_entities: Optional[int]
    definition: str
    endpoint: Optional[str] = None
    query_text: Optional[str] = None
    query_hash: Optional[str] = None
    query_status: Optional[str] = None
    cache_status: Optional[str] = None
    retrieved_at: Optional[str] = None
    note: str = ""
    attempts: tuple[Mapping[str, Any], ...] = ()

    @property
    def available(self) -> bool:
        return self.total_entities is not None and self.total_entities >= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_entities": self.total_entities,
            "universe_definition": self.definition,
            "endpoint": self.endpoint,
            "query_text": self.query_text,
            "query_sha256": self.query_hash,
            "query_status": self.query_status,
            "cache_status": self.cache_status,
            "retrieved_at": self.retrieved_at,
            "note": self.note,
            "attempts": [dict(a) for a in self.attempts],
        }


_UNFILTERED_NOTE = (
    "The Category-filtered universe query specified for this task is not "
    "answerable by the live public DBpedia endpoint: Virtuoso's anytime limit "
    "interrupts it and returns an INCOMPLETE count (X-SQL-State S1TAT). The "
    "unfiltered COUNT(DISTINCT ?e) over any dcterms:subject object completes "
    "and is not flagged incomplete, and it is a strict UPPER BOUND on the "
    "Category-only universe because a small number of dcterms:subject objects "
    "on this endpoint are not Category URIs. This is recorded as an upper bound, "
    "never as the Category-only count. Class ORDER is unaffected: with N fixed "
    "across the run, log(N/n_c) is strictly decreasing in n_c, so N shifts every "
    "raw_idf by one additive constant and vanishes under rank normalisation."
)


def resolve_idf_universe(
    runner: Optional[SparqlRunner],
    *,
    explicit_total: Optional[int] = None,
    allow_unfiltered_fallback: bool = True,
) -> IdfUniverse:
    """Determine N once, in a fixed precedence order, recording every attempt.

    1. ``explicit_total`` (the ``--total-entities`` override) wins outright. It
       is what makes an offline replay reproduce a live run's raw_idf exactly.
    2. Otherwise the SPECIFIED Category-filtered query is attempted.
    3. If that returns a PARTIAL or failed answer, the answerable unfiltered
       query is attempted and its result recorded as an explicit UPPER BOUND.
    4. If nothing succeeds, N is ``None`` and the universe is
       ``IDF_UNIVERSE_UNAVAILABLE``. Scoring then REFUSES rather than falling
       back to 6,000,000 (v5's documented constant) or 6,685,753 (the pinned
       local KG's node count, a different population entirely).
    """
    if explicit_total is not None:
        if int(explicit_total) < 1:
            raise ValueError(
                f"--total-entities must be >= 1, got {explicit_total!r}")
        return IdfUniverse(
            total_entities=int(explicit_total),
            definition=UNIVERSE_EXPLICIT,
            note=("N supplied explicitly by the operator; no global-count query "
                  "was issued. Use this to replay a previous run's raw_idf."),
        )

    if runner is None:
        return IdfUniverse(
            total_entities=None, definition=UNIVERSE_UNAVAILABLE,
            note=("no SPARQL runner and no --total-entities override, so N was "
                  "neither measured nor supplied"))

    attempts: list[Mapping[str, Any]] = []
    plan = [(build_idf_universe_query(), UNIVERSE_CATEGORY_FILTERED, "")]
    if allow_unfiltered_fallback:
        plan.append((build_idf_universe_query_unfiltered(),
                     UNIVERSE_UNFILTERED_UPPER_BOUND, _UNFILTERED_NOTE))

    for query, definition, note in plan:
        result = runner.run(query)
        value = None
        if result.usable and result.rows:
            raw = binding_value(result.rows[0], "N")
            try:
                value = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
        attempts.append({
            "universe_definition": definition,
            "query_id": result.query_id,
            "query_status": result.status.value,
            "cache_status": result.cache_status.value,
            "sql_state": result.sql_state,
            "value": value,
            "error": result.error,
        })
        if value is not None and value >= 1:
            return IdfUniverse(
                total_entities=value, definition=definition,
                endpoint=result.endpoint, query_text=query,
                query_hash=result.query_hash, query_status=result.status.value,
                cache_status=result.cache_status.value,
                retrieved_at=result.retrieved_at, note=note,
                attempts=tuple(attempts))

    return IdfUniverse(
        total_entities=None, definition=UNIVERSE_UNAVAILABLE,
        endpoint=runner.endpoint,
        note=("every global-count attempt failed or returned an incomplete "
              "result; no N was invented. Supply --total-entities to score."),
        attempts=tuple(attempts))


# ---------------------------------------------------------------------------
# 6) SEMANTIC TEXT AND ENCODING
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticText:
    """The text that produces the semantic query vector, plus its provenance.

    ``status`` is the field a consumer must branch on. ``text`` being ``None`` and
    ``text`` being ``""`` are both unavailability, and neither is a similarity.
    """

    source: SemanticSource
    status: SemanticStatus
    text: Optional[str] = None
    text_sha256: Optional[str] = None
    character_length: int = 0
    sentence_count: int = 0
    wikipedia_title: Optional[str] = None
    wikipedia_page_id: Optional[int] = None
    wikipedia_revision_id: Optional[int] = None
    wikipedia_revision_timestamp: Optional[str] = None
    wikipedia_redirected_from: Optional[str] = None
    retrieved_at: Optional[str] = None
    detail: Optional[str] = None

    @property
    def available(self) -> bool:
        return self.status is SemanticStatus.AVAILABLE and bool(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_source": self.source.value,
            "semantic_status": self.status.value,
            "semantic_text_sha256": self.text_sha256,
            "semantic_character_length": self.character_length,
            "semantic_sentence_count": self.sentence_count,
            "wikipedia_title": self.wikipedia_title,
            "wikipedia_page_id": self.wikipedia_page_id,
            "wikipedia_revision_id": self.wikipedia_revision_id,
            "wikipedia_revision_timestamp": self.wikipedia_revision_timestamp,
            "wikipedia_redirected_from": self.wikipedia_redirected_from,
            "semantic_retrieved_at": self.retrieved_at,
            "semantic_detail": self.detail,
        }


def semantic_text_from_lead(lead: WikipediaLead) -> SemanticText:
    """Adapt a :class:`WikipediaLead` into the selector's semantic-text record.

    An unavailable lead — page missing, empty intro, or a failed request — becomes
    ``SEMANTIC_TEXT_UNAVAILABLE`` carrying the reason. The three causes stay
    distinguishable in ``detail`` because a coverage census that merged "Wikipedia
    has no such page" with "our request failed" would understate coverage by
    exactly the number of transient failures.
    """
    if lead.available:
        return SemanticText(
            source=SemanticSource.WIKIPEDIA_LEAD,
            status=SemanticStatus.AVAILABLE,
            text=lead.lead_text,
            text_sha256=lead.lead_sha256,
            character_length=lead.character_length,
            sentence_count=lead.sentence_count,
            wikipedia_title=lead.canonical_title,
            wikipedia_page_id=lead.page_id,
            wikipedia_revision_id=lead.revision_id,
            wikipedia_revision_timestamp=lead.revision_timestamp,
            wikipedia_redirected_from=lead.redirected_from,
            retrieved_at=lead.retrieved_at,
        )
    return SemanticText(
        source=SemanticSource.WIKIPEDIA_LEAD,
        status=SemanticStatus.UNAVAILABLE,
        wikipedia_title=lead.canonical_title,
        wikipedia_page_id=lead.page_id,
        wikipedia_revision_id=lead.revision_id,
        wikipedia_revision_timestamp=lead.revision_timestamp,
        wikipedia_redirected_from=lead.redirected_from,
        retrieved_at=lead.retrieved_at,
        detail=f"{lead.status.value}: {lead.error}" if lead.error else lead.status.value,
    )


def semantic_text_from_description(description: Optional[str]) -> SemanticText:
    """Adapt an English ``dbo:description`` literal into a semantic-text record."""
    text = (description or "").strip()
    if not text:
        return SemanticText(
            source=SemanticSource.DBPEDIA_DESCRIPTION,
            status=SemanticStatus.UNAVAILABLE,
            detail="the endpoint returned no English dbo:description")
    return SemanticText(
        source=SemanticSource.DBPEDIA_DESCRIPTION,
        status=SemanticStatus.AVAILABLE,
        text=text, text_sha256=sha256_text(text),
        character_length=len(text), sentence_count=count_sentences(text))


class TextEncoder(Protocol):
    name: str
    max_seq_length: int

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:  # pragma: no cover
        ...


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Regex sentence splitter. No NLTK punkt download, hence no network."""
    if not text:
        return []
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]


def estimate_tokens(text: str) -> int:
    """Rough word-piece estimate: whitespace tokens x 1.3, floor 1.

    An ESTIMATE, not the model tokenizer; a chunk may still be truncated by the
    model itself, which is why the docstring of :func:`encode_semantic_similarity`
    refuses to claim lossless processing.
    """
    return max(1, int(round(len(text.split()) * 1.3)))


def chunk_text(text: str, *, max_tokens: int, safety_ratio: float = 0.8) -> list[str]:
    """Pack sentences into chunks that should fit the encoder's token window.

    A Wikipedia lead is routinely longer than all-MiniLM-L6-v2's 256-token
    window. Character-slicing it would throw prose away silently; here a sentence
    that is itself over budget is split on word boundaries instead of dropped, so
    no part of the lead is discarded before encoding. The CACHE always keeps the
    full lead — chunking happens only at encoding time.
    """
    if not text or not text.strip():
        return []
    budget = max(1, int(max(1, int(max_tokens)) * safety_ratio))
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if current:
            chunks.append(" ".join(current))
            current = []
            current_tokens = 0

    for sentence in split_sentences(text):
        size = estimate_tokens(sentence)
        if size > budget:
            flush()
            words = sentence.split()
            per_chunk = max(1, int(budget * len(words) / max(1, size)))
            for start in range(0, len(words), per_chunk):
                chunks.append(" ".join(words[start:start + per_chunk]))
            continue
        if current_tokens + size > budget:
            flush()
        current.append(sentence)
        current_tokens += size
    flush()
    return chunks


@dataclass
class SbertEncoder:
    """Lazy sentence-transformers wrapper.

    The model loads on the first :meth:`encode` call or the first read of
    :attr:`max_seq_length` — never at import, never during test collection.
    ``local_files_only`` defaults to True so that a run cannot quietly download
    weights: an absent model raises instead, and the operator decides.
    """

    name: str = DEFAULT_SBERT_MODEL
    device: Optional[str] = None
    local_files_only: bool = True
    _model: Any = field(default=None, init=False, repr=False)

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy

            self._model = SentenceTransformer(
                self.name, device=self.device,
                local_files_only=self.local_files_only)
        return self._model

    @property
    def max_seq_length(self) -> int:
        return int(getattr(self.model, "max_seq_length", 256) or 256)

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        vectors = self.model.encode(list(texts), batch_size=64, convert_to_numpy=True)
        return [list(map(float, v)) for v in vectors]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _mean(vectors: Sequence[Sequence[float]]) -> list[float]:
    width = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]


def encode_semantic_similarity(
    encoder: Optional[TextEncoder], semantic: SemanticText, labels: Sequence[str],
) -> tuple[Optional[list[float]], dict[str, Any]]:
    """Cosine similarity between the chunk-aggregated semantic text and each label.

    Returns ``(similarities, metadata)``. ``similarities`` is ``None`` — not a
    list of zeros — whenever no genuine similarity could be computed, so a caller
    physically cannot mistake unavailability for orthogonality.

    The Answer's text is encoded ONCE per Answer and every class label ONCE, in a
    single batched call; the six-alpha sweep then reuses these numbers without
    re-encoding anything.
    """
    metadata: dict[str, Any] = {
        "encoder": getattr(encoder, "name", None) if encoder is not None else None,
        "max_seq_length": None,
        "chunk_strategy": "sentence_pack",
        "aggregation": "mean_chunks",
        "text_chunks": 0,
        "available": False,
        "note": ("Chunking removes character-level truncation of the semantic "
                 "text. Each chunk is still subject to the model's own token "
                 "limit, so this is not a claim of lossless processing."),
    }
    if encoder is None:
        metadata["reason"] = SemanticStatus.ENCODER_UNAVAILABLE.value
        return None, metadata
    if not semantic.available or not labels:
        metadata["reason"] = SemanticStatus.UNAVAILABLE.value
        return None, metadata

    max_tokens = int(getattr(encoder, "max_seq_length", 256) or 256)
    metadata["max_seq_length"] = max_tokens
    chunks = chunk_text(str(semantic.text), max_tokens=max_tokens)
    if not chunks:
        metadata["reason"] = SemanticStatus.UNAVAILABLE.value
        return None, metadata
    metadata["text_chunks"] = len(chunks)

    vectors = list(encoder.encode(list(chunks) + list(labels)))
    if len(vectors) != len(chunks) + len(labels):
        metadata["reason"] = "encoder returned an unexpected number of vectors"
        return None, metadata
    query_vector = _mean(vectors[:len(chunks)])
    metadata["available"] = True
    return [cosine(query_vector, v) for v in vectors[len(chunks):]], metadata


# ---------------------------------------------------------------------------
# 7) FEATURES — everything the network is asked for, computed exactly once
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassFeature:
    """One candidate class with its RAW, alpha-independent features.

    ``raw_sbert`` is ``Optional[float]``: ``None`` means "no semantic feature
    exists", which is a different statement from 0.0 ("the encoder measured no
    similarity"). Everything in this record is fixed before any alpha is chosen,
    which is what makes the six-alpha sweep a comparison of six rankings over
    identical observations rather than six separate experiments.

    LEAKAGE AND FEASIBILITY ARE SEPARATE AXES AND ARE RECORDED SEPARATELY.
    ``rejected_code`` is the PRIMARY reason, i.e. the first gate that fired in
    the declared gate order, and ``rejection_reasons`` lists every independent
    reason the class was refused. A class can be simultaneously too small AND an
    answer-revealing name, and forcing those two facts into one mutually
    exclusive field destroys information a reviewer needs. ``leak_status``
    distinguishes "the rules ran and found nothing" from "the rules could not
    run"; ``r1_leak_level`` preserves what the frozen rule alone said, so the
    effect of the class-only extension is always recoverable from the row.
    """

    category_uri: str
    category_label: str
    remote_count: Optional[int] = None
    eligible_remote_count: Optional[int] = None
    raw_idf: Optional[float] = None
    raw_sbert: Optional[float] = None
    leak_level: LeakLevel = LeakLevel.NONE
    leak_status: LeakStatus = LeakStatus.NOT_EVALUATED
    leak_reason: Optional[str] = None
    leak_source: str = LEAKAGE_SOURCE_R1
    leak_evidence: tuple[str, ...] = ()
    r1_leak_level: LeakLevel = LeakLevel.NONE
    r1_leak_evidence: tuple[str, ...] = ()
    class_rule_leak_evidence: tuple[str, ...] = ()
    feasible: bool = False
    rejected_code: Optional[str] = None
    rejected_reason: Optional[str] = None
    rejection_reasons: tuple[str, ...] = ()

    @property
    def primary_rejected_code(self) -> Optional[str]:
        """Alias for ``rejected_code``, named for what it actually is.

        The old name is kept as the stored field so every existing reader and
        every recorded artifact column keeps working; this property is the
        vocabulary the provenance model uses.
        """
        return self.rejected_code

    @property
    def leak_changed_by_class_rule(self) -> bool:
        """True when the class-only extension moved the verdict away from R1."""
        return (self.leak_status is LeakStatus.EVALUATED
                and self.leak_level is not self.r1_leak_level)


@dataclass(frozen=True)
class AnswerFeatures:
    """Every observation for one Answer, frozen before ranking.

    Constructing this is the ONLY thing that costs network traffic. Ranking is a
    pure function of it (:func:`rank_feasible_classes`).
    """

    answer_uri: str
    answer_label: str
    status: str
    classes: tuple[ClassFeature, ...] = ()
    semantic: Optional[SemanticText] = None
    dbpedia_description: Optional[str] = None
    idf_universe: Optional[IdfUniverse] = None
    encoder_metadata: Mapping[str, Any] = field(default_factory=dict)
    categories_discovered: int = 0
    categories_truncated: bool = False
    sparql_queries: int = 0
    error: Optional[str] = None

    @property
    def feasible_classes(self) -> tuple[ClassFeature, ...]:
        return tuple(c for c in self.classes if c.feasible)

    @property
    def rejected_classes(self) -> tuple[ClassFeature, ...]:
        return tuple(c for c in self.classes if not c.feasible)


STATUS_OK = "ok"
STATUS_NO_CATEGORIES = "no_subject_categories"
STATUS_ALL_REJECTED = "all_categories_rejected"
STATUS_QUERY_FAILED = "query_failed"
STATUS_IDF_UNAVAILABLE = "idf_universe_unavailable"


def _fetch_category_counts(
    runner: SparqlRunner, category_uris: Sequence[str], *, batch_size: int,
) -> tuple[dict[str, int], bool]:
    """``n_c`` for every category, in batches. Returns ``(counts, failed)``.

    A failed or PARTIAL batch sets ``failed`` rather than being read as "these
    classes have no members": the second reading would reject every class in the
    batch on the strength of a transport problem.
    """
    counts: dict[str, int] = {}
    for start in range(0, len(category_uris), max(1, batch_size)):
        window = list(category_uris[start:start + max(1, batch_size)])
        result = runner.run(build_category_counts_query(window))
        if not result.usable:
            return counts, True
        for row in result.rows:
            uri = binding_value(row, "cat")
            raw = binding_value(row, "c")
            if uri is None or raw is None:
                continue
            try:
                counts[uri] = int(raw)
            except (TypeError, ValueError):
                continue
    return counts, False


def _with_leakage(
    candidate: ClassFeature, verdict: ClassLeakVerdict, *,
    rejected_code: Optional[str] = None, rejected_reason: Optional[str] = None,
) -> ClassFeature:
    """Stamp a leakage verdict onto a class row, optionally rejecting it too.

    Both verdicts are copied: the composed ``leak_level`` the gate acts on and
    the ``r1_leak_level`` the frozen rule alone produced. Storing both is what
    lets the delta audit be a projection of these rows rather than a second
    computation that could disagree with the run it claims to describe.
    """
    stamped = replace(
        candidate,
        leak_level=LeakLevel(verdict.level),
        leak_status=LeakStatus(verdict.status),
        leak_reason=verdict.reason,
        leak_source=verdict.source,
        leak_evidence=verdict.evidence,
        r1_leak_level=LeakLevel(verdict.r1_level),
        r1_leak_evidence=verdict.r1_evidence,
        class_rule_leak_evidence=verdict.derivational_evidence,
    )
    if rejected_code is None:
        return stamped
    return _reject(stamped, rejected_code, rejected_reason or "")


def _reject(candidate: ClassFeature, code: str, reason: str) -> ClassFeature:
    """Refuse a class, recording the PRIMARY code and EVERY independent reason.

    ``code`` is the first gate that fired in the declared gate order and stays in
    ``rejected_code``, so every artifact column and every reader that already
    consumes that field keeps its previous meaning. ``rejection_reasons`` adds
    the reasons that are true SIMULTANEOUSLY — today that is exactly the case of
    a class rejected on size which is ALSO an answer-revealing name. Collapsing
    those two into one field is what made a hard-leaking class publish
    ``leak_level = no_leak``.
    """
    reasons = [code]
    if (code != RejectCode.HARD_LEAK.value
            and candidate.leak_level is LeakLevel.HARD):
        reasons.append(RejectCode.HARD_LEAK.value)
    return replace(candidate, feasible=False, rejected_code=code,
                   rejected_reason=reason, rejection_reasons=tuple(reasons))


def extract_answer_features(
    answer_uri: str,
    *,
    runner: SparqlRunner,
    idf_universe: IdfUniverse,
    semantic_source: SemanticSource = SemanticSource.WIKIPEDIA_LEAD,
    wikipedia_lead: Optional[WikipediaLead] = None,
    encoder: Optional[TextEncoder] = None,
    quality_policy: Optional[QualityPolicy] = None,
    min_remote_candidates: int = DEFAULT_MIN_REMOTE_CANDIDATES,
    max_remote_candidates: int = DEFAULT_MAX_REMOTE_CANDIDATES,
    category_limit: int = DEFAULT_CATEGORY_LIMIT,
    count_batch_size: int = DEFAULT_COUNT_BATCH_SIZE,
) -> AnswerFeatures:
    """Discover, gate and score one Answer's candidate-source classes.

    STAGE 1 — HARD FEASIBILITY, in this fixed order:
      1. the value must denote a valid DBpedia Category URI;
      2. it must not be an administrative/maintenance category;
      3. its complete member count must be known (an unknown count is NOT a
         rejection of the class, it is a rejection of the measurement);
      4. it must offer at least ``min_remote_candidates`` members EXCLUDING the
         Answer, which cannot be its own distractor;
      5. it must not exceed the declared broad-category maximum;
      6. it must not HARD-leak the Answer under the frozen R1 rule composed with
         the class-only derivational/eponymic rule.

    The leakage VERDICT is computed for every class with an adaptable URI before
    gate 3, and gate 6 only acts on it. Annotation and rejection are therefore
    independent: a class rejected at gate 4 for being too small still carries its
    true leakage level, and its ``rejection_reasons`` lists both facts. The gate
    ORDER is unchanged, so no class changes its PRIMARY rejection code because of
    this reordering.

    STAGE 2 — RAW FEATURES for every class that survived: conventional IDF from
    the run-level N, and (when a semantic text and an encoder both exist) the
    cosine similarity between the Answer's semantic text and the class label.
    No alpha is involved and no ranking happens here.

    Every network call this Answer will ever cause happens inside this function.
    """
    policy = quality_policy or load_r1_leakage_policy()
    label_result = runner.run(build_answer_info_query(answer_uri))
    rdfs_label: Optional[str] = None
    description: Optional[str] = None
    if label_result.usable:
        for row in label_result.rows:
            rdfs_label = rdfs_label or binding_value(row, "label")
            description = description or binding_value(row, "description")
    label = answer_display_label(answer_uri, rdfs_label)

    # The semantic text is chosen ONCE per run and never mixed across sources.
    if semantic_source is SemanticSource.DBPEDIA_DESCRIPTION:
        semantic = semantic_text_from_description(description)
    elif wikipedia_lead is not None:
        semantic = semantic_text_from_lead(wikipedia_lead)
    else:
        semantic = SemanticText(
            source=SemanticSource.WIKIPEDIA_LEAD,
            status=SemanticStatus.UNAVAILABLE,
            detail="no Wikipedia lead was supplied for this Answer")

    def emit(status: str, classes: Sequence[ClassFeature] = (),
             discovered: int = 0, truncated: bool = False,
             encoder_metadata: Optional[Mapping[str, Any]] = None,
             error: Optional[str] = None) -> AnswerFeatures:
        return AnswerFeatures(
            answer_uri=answer_uri, answer_label=label, status=status,
            classes=tuple(classes), semantic=semantic,
            dbpedia_description=description, idf_universe=idf_universe,
            encoder_metadata=dict(encoder_metadata or {}),
            categories_discovered=discovered, categories_truncated=truncated,
            sparql_queries=runner.n_queries, error=error)

    if not label_result.usable:
        return emit(STATUS_QUERY_FAILED, error=label_result.error)
    if not idf_universe.available:
        # Refusing here is the point of C3: an unscored Answer is recoverable,
        # an Answer scored against an invented N is a silent error in every
        # downstream table.
        return emit(STATUS_IDF_UNAVAILABLE,
                    error="no IDF universe N is available; supply --total-entities")

    categories_result = runner.run(
        build_answer_categories_query(answer_uri, limit=category_limit))
    if not categories_result.usable:
        return emit(STATUS_QUERY_FAILED, error=categories_result.error)
    discovered_raw = [binding_value(row, "cat") for row in categories_result.rows]
    discovered = [c for c in discovered_raw if c]
    truncated = len(discovered) >= category_limit
    if not discovered:
        return emit(STATUS_NO_CATEGORIES, discovered=0)

    # --- gates 1 and 2: URI validity and administrative categories ----------
    #
    # LEAKAGE IS ANNOTATED HERE, NOT AT THE END. Every class whose URI can be
    # adapted for the comparison receives its verdict now, BEFORE any size gate
    # can remove it from consideration. That is the whole repair: the annotation
    # describes the Answer/class NAME PAIR and has nothing to do with how many
    # members the class happens to have, so making it conditional on surviving a
    # size test published false `no_leak` values for exactly the classes a
    # reviewer is most likely to check by hand. Administrative categories are
    # annotated too — a superset of what is required, never less.
    evaluated: list[ClassFeature] = []
    survivors: list[ClassFeature] = []
    for raw_uri in discovered:
        canonical = normalize_category(raw_uri)
        if canonical is None:
            # The one case where no verdict can be produced. It is stamped
            # NOT_EVALUATED, never `no_leak`.
            unevaluated = not_evaluated_verdict(
                "value does not denote a usable DBpedia category URI, so no "
                "leakage comparison was possible")
            evaluated.append(_with_leakage(ClassFeature(
                category_uri=str(raw_uri), category_label=""), unevaluated,
                rejected_code=RejectCode.INVALID_URI.value,
                rejected_reason="value does not denote a usable DBpedia category URI"))
            continue
        verdict = classify_class_leakage_extended(
            answer_uri, canonical, policy=policy)
        candidate = _with_leakage(
            ClassFeature(category_uri=canonical,
                         category_label=category_display_label(canonical)),
            verdict)
        local_name = canonical[len(CATEGORY_PREFIX):]
        if _JUNK_RE.search(local_name):
            evaluated.append(_reject(
                candidate, RejectCode.JUNK.value,
                "maintenance or administrative category"))
            continue
        survivors.append(candidate)

    # --- gates 3, 4, 5: class size ------------------------------------------
    counts, counts_failed = _fetch_category_counts(
        runner, [c.category_uri for c in survivors], batch_size=count_batch_size)
    if counts_failed:
        return emit(STATUS_QUERY_FAILED, classes=evaluated + survivors,
                    discovered=len(discovered), truncated=truncated,
                    error="a category member-count query failed or returned "
                          "incomplete results")

    sized: list[ClassFeature] = []
    for candidate in survivors:
        count = counts.get(candidate.category_uri)
        if count is None or count < 1:
            evaluated.append(_reject(
                replace(candidate, remote_count=count),
                RejectCode.COUNT_UNAVAILABLE.value,
                "the endpoint returned no member count for this class"))
            continue
        # Every class here came from the Answer's own dct:subject list, so the
        # Answer is necessarily one of its members and cannot be its own
        # distractor. The size gate is applied to the eligible count; the IDF
        # denominator uses the full class size. The two are deliberately
        # different numbers.
        eligible = max(count - 1, 0)
        candidate = replace(candidate, remote_count=count,
                            eligible_remote_count=eligible,
                            raw_idf=standard_idf(count, idf_universe.total_entities))
        if eligible < min_remote_candidates:
            evaluated.append(_reject(
                candidate, RejectCode.TOO_SMALL.value,
                (f"only {eligible} remote distractor candidates excluding the "
                 f"Answer (< {min_remote_candidates}); class size {count}")))
        elif count > max_remote_candidates:
            evaluated.append(_reject(
                candidate, RejectCode.TOO_GENERIC.value,
                f"{count} remote members (> {max_remote_candidates})"))
        else:
            sized.append(candidate)

    # --- gate 6: the HARD lexical leakage gate ------------------------------
    #
    # The verdict was computed above; this loop only ACTS on it. Gate order is
    # unchanged from the previous version — size before leakage — so a class that
    # fails both keeps the same PRIMARY rejection code it had before, and only
    # `rejection_reasons` grows.
    feasible: list[ClassFeature] = []
    for candidate in sized:
        if candidate.leak_level is LeakLevel.HARD:
            evaluated.append(_reject(
                candidate, RejectCode.HARD_LEAK.value,
                f"hard leak ({candidate.leak_source}): {candidate.leak_reason}"))
        else:
            feasible.append(replace(candidate, feasible=True))

    # --- STAGE 2: raw semantic feature, one encode pass ---------------------
    similarities, encoder_metadata = encode_semantic_similarity(
        encoder, semantic, [c.category_label for c in feasible])
    if similarities is not None:
        feasible = [replace(c, raw_sbert=float(s))
                    for c, s in zip(feasible, similarities)]

    status = STATUS_OK if feasible else STATUS_ALL_REJECTED
    return emit(status, classes=evaluated + feasible, discovered=len(discovered),
                truncated=truncated, encoder_metadata=encoder_metadata)


# ---------------------------------------------------------------------------
# 8) RANKING — a pure function of frozen features and one alpha
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedClass:
    """One feasible class at one alpha. Rejected classes never appear here."""

    feature: ClassFeature
    feasible_rank: int
    normalized_idf: float
    normalized_sbert: Optional[float]
    combined_score: float

    @property
    def category_uri(self) -> str:
        return self.feature.category_uri


@dataclass(frozen=True)
class AnswerRanking:
    """One Answer's complete feasible ranking at one alpha, plus how it was made."""

    answer_uri: str
    answer_label: str
    alpha: float
    scoring_mode: ScoringMode
    ranked: tuple[RankedClass, ...]
    features: AnswerFeatures

    @property
    def top_ranked_class(self) -> Optional[str]:
        return self.ranked[0].category_uri if self.ranked else None

    def top_k(self, k: int) -> tuple[str, ...]:
        return tuple(r.category_uri for r in self.ranked[:k])


def rank_feasible_classes(features: AnswerFeatures, alpha: float) -> AnswerRanking:
    """Rank one Answer's feasible classes at one alpha. NO network, NO encoding.

    This is the whole reason a six-alpha sweep costs one Answer's traffic: the
    raw IDF and raw SBERT values were fixed by :func:`extract_answer_features`,
    and this function only re-weights them. Six calls therefore compare six
    rankings of the SAME observations, which a six-times-refetched sweep could
    not guarantee.

    Ordering is fully deterministic: one declared numerical key
    (``combined_score``, descending), then the category URI ascending. The URI
    tie-break is reached only when the declared numerical key is exactly tied, so
    the output does not depend on the order the endpoint returned categories in.
    """
    alpha = validate_alpha(alpha)
    feasible = list(features.feasible_classes)

    semantic_available = bool(feasible) and all(c.raw_sbert is not None
                                                for c in feasible)
    if not feasible:
        scoring_mode = ScoringMode.NO_FEASIBLE_CLASS
    elif not semantic_available:
        scoring_mode = ScoringMode.IDF_ONLY_SEMANTIC_UNAVAILABLE
    elif alpha == 0.0:
        scoring_mode = ScoringMode.IDF_ONLY_BY_ALPHA
    else:
        scoring_mode = ScoringMode.RANK_FUSION

    normalized_idf = rank_normalize([float(c.raw_idf or 0.0) for c in feasible])
    normalized_sbert: list[Optional[float]]
    if semantic_available:
        normalized_sbert = list(rank_normalize(
            [float(c.raw_sbert) for c in feasible]))  # type: ignore[arg-type]
    else:
        normalized_sbert = [None] * len(feasible)

    scored = [
        RankedClass(feature=c, feasible_rank=0, normalized_idf=ni,
                    normalized_sbert=ns, combined_score=combine_alpha(ns, ni, alpha))
        for c, ni, ns in zip(feasible, normalized_idf, normalized_sbert)
    ]
    scored.sort(key=lambda r: (-r.combined_score, r.category_uri))
    ranked = tuple(replace(r, feasible_rank=i + 1) for i, r in enumerate(scored))
    return AnswerRanking(answer_uri=features.answer_uri,
                         answer_label=features.answer_label, alpha=alpha,
                         scoring_mode=scoring_mode, ranked=ranked,
                         features=features)
