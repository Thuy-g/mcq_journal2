############################################################################
# src/rationale_v3/quality.py
#
# Hard eligibility filters and pedagogical quality, applied BEFORE set cover.
# R1 changed nothing in this module's behaviour.
#
# WHY IT EXISTS
#   Two of the eight rationales Prompt 8E selected are unusable as teaching
#   material, and both were minimum-cardinality covers — failures of the
#   eligibility relation, not of set cover:
#
#     Eisaku Sato   dbp:url -> a Web Archive snapshot URL. It discriminates all
#                   three distractors perfectly and teaches nothing.
#     Carbon        dbp:formula (IN) -> dbr:Carbonado. "Carbonado" contains
#                   "Carbon", so the rationale hands the learner the Answer.
#
# HARD VERSUS SOFT
#   A HARD filter removes a fact from every policy and every rationale and emits
#   a stable reason code. A SOFT signal only orders equally small rationales. A
#   soft signal that could silently remove a fact would be indistinguishable
#   from a bug; a hard filter used for ranking would drop supported yield.
#
# DISPLAY IS NOT LEAKAGE TOKENIZATION
#   `display_label` preserves parentheses and Roman numerals: the legacy
#   `remove_parenthetical()` turns Iron(III)_chloride into "Iron chloride",
#   misnaming the entity and collapsing two choices to one label (AUDIT items
#   CE-10, INV-2). Leakage tokenization is a separate, lossy pipeline used only
#   for comparison, never for display or identity.
#
# NO MODELS. Unicode normalization, percent decoding, casefolding and string
# comparison only; nothing expands a token beyond a light plural stem (AUDIT
# item CE-11). OFFLINE AND PURE apart from reading the policy file it is given.
############################################################################

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence
from urllib.parse import unquote, urlsplit

from rationale_v3.contracts import RationaleV3ContractError

VERSION = "rationale_v3.quality/1.0.0"

TEMPLATE_UNKNOWN = "VERBALIZABLE_UNKNOWN"
LEAK_NONE = "NO_LEAK"


class QualityPolicyError(RationaleV3ContractError):
    """The predicate/object/leakage policy file is missing or malformed."""


# --- 1) LABELS ---------------------------------------------------------------

def local_name(uri: str) -> str:
    """The last path segment of a URI, percent-decoded. Nothing else."""
    text = uri.strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    parts = urlsplit(text)
    tail = parts.path.rsplit("/", 1)[-1] if parts.path else ""
    if not tail:
        tail = parts.netloc or text
    return unquote(tail)


def display_label(uri: str) -> str:
    """A readable label that keeps everything that distinguishes the entity.

    Underscores become spaces and percent escapes are decoded; parentheses,
    Roman numerals, digits, diacritics and case are preserved exactly. This is
    the audit's principled answer to "keep or strip?": keeping costs a slightly
    longer label, stripping costs a misnamed chemical and two identical choices
    (AUDIT appendix B.3, INV-1 and INV-2).
    """
    return unicodedata.normalize("NFC", local_name(uri).replace("_", " ")).strip()


def leakage_tokens(uri_or_text: str, *, minimum_length: int) -> tuple[str, ...]:
    """The lossy token pipeline used ONLY for leakage comparison.

    NFKC (so full-width and compatibility forms compare equal), percent
    decoding, casefold, then a split on every character that is not a letter or
    a digit. Tokens shorter than `minimum_length` are dropped, because a
    two- or three-character coincidence is not a leak (AUDIT item CE-11 records
    the opposite mistake: a synonym-expanding checker that rejected valid
    classes).
    """
    text = local_name(uri_or_text) if "/" in uri_or_text else uri_or_text
    text = unicodedata.normalize("NFKC", text).casefold()
    token = []
    tokens = []
    for char in text:
        if char.isalnum():
            token.append(char)
        elif token:
            tokens.append("".join(token))
            token = []
    if token:
        tokens.append("".join(token))
    return tuple(t for t in tokens if len(t) >= minimum_length)


# --- 2) THE POLICY -----------------------------------------------------------

@dataclass(frozen=True)
class TemplateEntry:
    predicate_uri: str
    direction: str
    template_id: str
    reading: str


@dataclass(frozen=True)
class ObjectPolicy:
    resource_namespace_prefixes: tuple[str, ...]
    web_archive_hosts: tuple[str, ...]
    media_file_suffixes: tuple[str, ...]
    maximum_object_label_length: int
    minimum_object_label_length: int
    machine_identifier_minimum_digit_ratio: float
    educational_allowlist: frozenset
    reject_reason_codes: Mapping[str, str]


@dataclass(frozen=True)
class LeakagePolicy:
    minimum_token_length: int
    minimum_prefix_length: int
    soft_prefix_length: int
    strip_suffixes: tuple[str, ...]
    hard_reason_code: str
    soft_reason_code: str


@dataclass(frozen=True)
class QualityPolicy:
    """The versioned §9 policy: predicates, objects, leakage and templates."""

    version: str
    policy_sha256: str
    hard_reject_predicates: Mapping[str, str]
    reject_reason_codes: Mapping[str, str]
    pedagogical_tier: Mapping[str, int]
    pedagogical_tier_default: int
    templates: Mapping[tuple[str, str], TemplateEntry]
    objects: ObjectPolicy
    leakage: LeakagePolicy
    notes: Mapping[str, str] = field(default_factory=dict)

    def tier_for(self, predicate_uri: str) -> int:
        return self.pedagogical_tier.get(predicate_uri,
                                         self.pedagogical_tier_default)

    def template_for(self, predicate_uri: str,
                     direction: str) -> Optional[TemplateEntry]:
        return self.templates.get((predicate_uri, direction))

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "policy_sha256": self.policy_sha256,
            "hard_reject_predicate_count": len(self.hard_reject_predicates),
            "hard_reject_predicates": dict(sorted(
                self.hard_reject_predicates.items())),
            "predicate_reject_reason_codes": dict(sorted(
                self.reject_reason_codes.items())),
            "object_reject_reason_codes": dict(sorted(
                self.objects.reject_reason_codes.items())),
            "template_count": len(self.templates),
            "pedagogical_tier_default": self.pedagogical_tier_default,
            "educational_allowlist": sorted(self.objects.educational_allowlist),
            "leakage": {
                "minimum_token_length": self.leakage.minimum_token_length,
                "minimum_prefix_length": self.leakage.minimum_prefix_length,
                "soft_prefix_length": self.leakage.soft_prefix_length,
            },
            "notes": dict(sorted(self.notes.items())),
        }


def load_quality_policy(path: str | Path) -> QualityPolicy:
    path = Path(path)
    if not path.is_file():
        raise QualityPolicyError(f"predicate policy not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise QualityPolicyError(f"{path.name}: {exc}") from exc

    obj = payload.get("object_policy", {})
    leak = payload.get("leakage_policy", {})
    templates: dict[tuple[str, str], TemplateEntry] = {}
    for entry in payload.get("templates", ()):
        key = (str(entry["predicate_uri"]), str(entry["direction"]))
        if key in templates:
            raise QualityPolicyError(
                f"{path.name}: two templates registered for {key}")
        templates[key] = TemplateEntry(
            predicate_uri=key[0], direction=key[1],
            template_id=str(entry["template_id"]),
            reading=str(entry.get("reading", "")))

    return QualityPolicy(
        version=str(payload.get("version", "unversioned")),
        policy_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        hard_reject_predicates={str(k): str(v) for k, v
                                in payload.get("hard_reject_predicates", {}).items()},
        reject_reason_codes={str(k): str(v) for k, v
                             in payload.get("reject_reason_codes", {}).items()},
        pedagogical_tier={str(k): int(v) for k, v
                          in payload.get("pedagogical_tier", {}).items()},
        pedagogical_tier_default=int(payload.get("pedagogical_tier_default", 3)),
        templates=templates,
        objects=ObjectPolicy(
            resource_namespace_prefixes=tuple(
                str(p) for p in obj.get("resource_namespace_prefixes", ())),
            web_archive_hosts=tuple(str(h) for h in obj.get("web_archive_hosts", ())),
            media_file_suffixes=tuple(
                str(s).lower() for s in obj.get("media_file_suffixes", ())),
            maximum_object_label_length=int(
                obj.get("maximum_object_label_length", 120)),
            minimum_object_label_length=int(
                obj.get("minimum_object_label_length", 1)),
            machine_identifier_minimum_digit_ratio=float(
                obj.get("machine_identifier_minimum_digit_ratio", 0.6)),
            educational_allowlist=frozenset(
                str(u) for u in obj.get("educational_allowlist", ())),
            reject_reason_codes={str(k): str(v) for k, v
                                 in obj.get("reject_reason_codes", {}).items()},
        ),
        leakage=LeakagePolicy(
            minimum_token_length=int(leak.get("minimum_token_length", 4)),
            minimum_prefix_length=int(leak.get("minimum_prefix_length", 5)),
            soft_prefix_length=int(leak.get("soft_prefix_length", 4)),
            strip_suffixes=tuple(str(s) for s in leak.get("strip_suffixes", ())),
            hard_reason_code=str(leak.get("hard_reason_code",
                                          "ANSWER_LEXICAL_LEAK")),
            soft_reason_code=str(leak.get("soft_reason_code",
                                          "ANSWER_LEXICAL_LEAK_SOFT")),
        ),
        notes={str(k): str(v) for k, v in payload.get("notes", {}).items()},
    )


# --- 3) LEXICAL ANSWER LEAKAGE -----------------------------------------------

@dataclass(frozen=True)
class LeakageResult:
    """Whether a counterpart hands the learner the Answer."""

    hard_leak: bool
    soft_leak: bool
    reason_code: str
    matches: tuple[tuple[str, str, str], ...]  # (answer token, other, kind)

    def as_record(self) -> dict:
        return {
            "hard_leak": self.hard_leak,
            "soft_leak": self.soft_leak,
            "leakage_reason_code": self.reason_code,
            "leakage_matches": [list(m) for m in self.matches],
        }


def _plural_stem(token: str, suffixes: Sequence[str]) -> str:
    """Strip ONE light plural suffix, never below four characters.

    Deliberately not a stemmer. Porter-style stemming would fold 'carbonate'
    and 'carbonated' onto 'carbon' and reject facts that share nothing but a
    chemical root, which is the over-sensitivity AUDIT item CE-11 warns about.
    """
    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix and token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def detect_answer_leakage(answer_uri: str, counterpart_uri: str,
                          policy: QualityPolicy) -> LeakageResult:
    """Deterministic lexical leakage detection, no models involved.

    HARD when an Answer token and a counterpart token are equal, are equal after
    a light plural stem, or one is a prefix of the other at least
    `minimum_prefix_length` characters long. SOFT when the longest shared prefix
    reaches `soft_prefix_length` but not the hard threshold.

    The two thresholds are what separate `Carbon` / `Carbonado` (shared prefix
    'carbon', six characters, HARD) from `Carbon` / `Boron_carbide` (shared
    prefix 'carb', four characters, SOFT at most).
    """
    leak = policy.leakage
    answer_tokens = leakage_tokens(answer_uri,
                                   minimum_length=leak.minimum_token_length)
    other_tokens = leakage_tokens(counterpart_uri,
                                  minimum_length=leak.minimum_token_length)

    hard: list[tuple[str, str, str]] = []
    soft: list[tuple[str, str, str]] = []
    for a in answer_tokens:
        a_stem = _plural_stem(a, leak.strip_suffixes)
        for b in other_tokens:
            if a == b:
                hard.append((a, b, "WHOLE_TOKEN"))
                continue
            if a_stem == _plural_stem(b, leak.strip_suffixes):
                hard.append((a, b, "PLURAL_STEM"))
                continue
            shared = _shared_prefix_length(a, b)
            if shared >= leak.minimum_prefix_length and (a.startswith(b)
                                                         or b.startswith(a)):
                hard.append((a, b, "LONG_PREFIX"))
            elif shared >= leak.soft_prefix_length:
                soft.append((a, b, "SHORT_PREFIX"))

    if hard:
        return LeakageResult(True, False, leak.hard_reason_code,
                             tuple(sorted(hard)))
    if soft:
        return LeakageResult(False, True, leak.soft_reason_code,
                             tuple(sorted(soft)))
    return LeakageResult(False, False, LEAK_NONE, ())


def _shared_prefix_length(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    index = 0
    while index < limit and a[index] == b[index]:
        index += 1
    return index


# --- 4) OBJECT AND PREDICATE ELIGIBILITY -------------------------------------

@dataclass(frozen=True)
class FactQuality:
    """Every quality signal for one Answer fact, hard and soft together."""

    predicate_uri: str
    direction: str
    counterpart_uri: str
    display_label: str
    predicate_ok: bool
    predicate_reason: str
    object_ok: bool
    object_reason: str
    leakage: LeakageResult
    template_id: str
    verbalizable: bool
    pedagogical_tier: int
    label_length: int
    token_count: int

    @property
    def eligible(self) -> bool:
        """Hard eligibility. Verbalizability is NOT part of it: an unverbalizable
        fact stays available for diagnostics and is only barred from the main
        corpus."""
        return (self.predicate_ok and self.object_ok
                and not self.leakage.hard_leak)

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        reasons = []
        if not self.predicate_ok:
            reasons.append(self.predicate_reason)
        if not self.object_ok:
            reasons.append(self.object_reason)
        if self.leakage.hard_leak:
            reasons.append(self.leakage.reason_code)
        return tuple(reasons)

    def as_record(self) -> dict:
        return {
            "predicate_uri": self.predicate_uri,
            "direction": self.direction,
            "counterpart_uri": self.counterpart_uri,
            "display_label": self.display_label,
            "predicate_policy_result": ("ACCEPTED" if self.predicate_ok
                                        else self.predicate_reason),
            "object_policy_result": ("ACCEPTED" if self.object_ok
                                     else self.object_reason),
            "template_id": self.template_id,
            "verbalizable": self.verbalizable,
            "pedagogical_tier": self.pedagogical_tier,
            "label_length": self.label_length,
            "token_count": self.token_count,
            "eligible": self.eligible,
            "rejection_reasons": list(self.rejection_reasons),
            **self.leakage.as_record(),
        }


def check_predicate(predicate_uri: str, policy: QualityPolicy) -> tuple[bool, str]:
    reason = policy.hard_reject_predicates.get(predicate_uri)
    if reason is None:
        return (True, "")
    return (False, reason)


def check_object(counterpart_uri: str, policy: QualityPolicy) -> tuple[bool, str]:
    """Hard object filters (§9.2). Allowlist first, so an exception is explicit."""
    objects = policy.objects
    if counterpart_uri in objects.educational_allowlist:
        return (True, "")

    parts = urlsplit(counterpart_uri)
    host = parts.netloc.lower()
    if any(host == h or host.endswith("." + h) for h in objects.web_archive_hosts):
        return (False, "OBJECT_WEB_ARCHIVE_URL")
    if objects.resource_namespace_prefixes and not any(
            counterpart_uri.startswith(prefix)
            for prefix in objects.resource_namespace_prefixes):
        return (False, "OBJECT_EXTERNAL_URL")

    name = local_name(counterpart_uri)
    lowered = name.lower()
    if any(lowered.endswith(suffix) for suffix in objects.media_file_suffixes):
        return (False, "OBJECT_MEDIA_FILE")

    label = display_label(counterpart_uri)
    if len(label) < objects.minimum_object_label_length:
        return (False, "OBJECT_EMPTY_LABEL")
    if len(label) > objects.maximum_object_label_length:
        return (False, "OBJECT_LABEL_TOO_LONG")

    alphanumeric = [c for c in label if c.isalnum()]
    if alphanumeric:
        digits = sum(1 for c in alphanumeric if c.isdigit())
        if (digits / len(alphanumeric)
                >= objects.machine_identifier_minimum_digit_ratio):
            return (False, "OBJECT_MACHINE_IDENTIFIER")
    return (True, "")


def assess_fact_quality(*, answer_uri: str, predicate_uri: str, direction: str,
                        counterpart_uri: str,
                        policy: QualityPolicy) -> FactQuality:
    """Every §9 signal for one Answer fact, computed once and reused."""
    predicate_ok, predicate_reason = check_predicate(predicate_uri, policy)
    object_ok, object_reason = check_object(counterpart_uri, policy)
    leakage = detect_answer_leakage(answer_uri, counterpart_uri, policy)
    template = policy.template_for(predicate_uri, direction)
    label = display_label(counterpart_uri)
    return FactQuality(
        predicate_uri=predicate_uri,
        direction=direction,
        counterpart_uri=counterpart_uri,
        display_label=label,
        predicate_ok=predicate_ok,
        predicate_reason=predicate_reason,
        object_ok=object_ok,
        object_reason=object_reason,
        leakage=leakage,
        template_id=template.template_id if template else TEMPLATE_UNKNOWN,
        verbalizable=template is not None,
        pedagogical_tier=policy.tier_for(predicate_uri),
        label_length=len(label),
        token_count=len(leakage_tokens(counterpart_uri, minimum_length=1)),
    )


# --- 5) PER-FACT SOFT ORDERING KEY -------------------------------------------

def fact_quality_key(quality: FactQuality) -> tuple:
    """The per-fact part of the rationale ordering. SMALLEST WINS.

    Only components that depend on ONE fact live here. The coupled components —
    rationale minimum level, redundancy across the set, local candidate-pool
    anonymity — are properties of the whole rationale and are applied in
    selector.py, the only place that can see the set.
    """
    return (
        1 if quality.leakage.soft_leak else 0,   # minimise soft leakage
        quality.pedagogical_tier,                # prefer tier 1 over tier 3
        0 if quality.verbalizable else 1,        # prefer a known template
        quality.label_length,                    # prefer a shorter label
        quality.token_count,                     # prefer fewer tokens
        (quality.predicate_uri, quality.direction, quality.counterpart_uri),
    )
