############################################################################
# src/classes/policy.py
#
# Strict loader and ordered walker for the human-approved pilot class policy.
#
# WHAT THIS MODULE IS FOR
#   The nine-Answer engineering pilot may draw distractor candidates ONLY from
#   classes a human approved for that specific Answer. The approval lives in
#   data/pilot_class_policy_v1.csv and data/pilot_class_policy_v1.json, which
#   were derived from the reconciliation plan
#   outputs/journal2_pdf_grounded_reconciliation_2026-07-30/pilot_measurement_plan.csv
#   (reconciliation ZIP sha256 14e3f68f...bbe951).
#
# WHAT THIS MODULE MUST NEVER DO
#   * infer, widen, union or substitute a class that is not on the approved list
#     for that Answer — select_first_feasible_class() walks exactly three
#     candidates and then reports NO_FEASIBLE_APPROVED_CLASS;
#   * accept a row whose approval status is blank or unrecognised;
#   * silently tolerate a duplicate Answer or a missing fallback.
#
# NAMING (CLAUDE.md non-negotiable boundary 9): the class a run ends up using is
# a `first_feasible_class`, never a "globally optimal" class.
#
# Offline: parsing only. No network, no SPARQL, no cache creation at import time.
############################################################################

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

# --- Frozen expectations of the pilot -------------------------------------
# Deliberately hard constants, not configuration. The pilot's size and approval
# token are part of what was approved; a run that quietly used a different count
# or a different token would not be the approved pilot.

EXPECTED_PILOT_ANSWER_COUNT = 9
APPROVED_STATUS = "HUMAN_APPROVED_FOR_ENGINEERING_PILOT"
EXPECTED_APPROVAL_DATE = "2026-07-30"
EXPECTED_RECONCILIATION_SHA256 = (
    "14e3f68f1866b74d16f9b2948025ea7e8f68dd0a816df633e9c9126f49bbe951"
)

POLICY_CSV_FIELDS = (
    "pilot_slot",
    "input_index",
    "answer_uri",
    "display_label",
    "preferred_class",
    "fallback_class_1",
    "fallback_class_2",
    "approval_status",
    "approval_date",
    "source_reconciliation_sha256",
)

# Class position labels, recorded per Answer so the pilot report can state which
# position in the approved list a run actually used.
POSITION_PREFERRED = "preferred"
POSITION_FALLBACK_1 = "fallback_1"
POSITION_FALLBACK_2 = "fallback_2"
CLASS_POSITIONS = (POSITION_PREFERRED, POSITION_FALLBACK_1, POSITION_FALLBACK_2)

# --- Result statuses -------------------------------------------------------
SELECTED_PREFERRED = "SELECTED_PREFERRED"
SELECTED_FALLBACK_1 = "SELECTED_FALLBACK_1"
SELECTED_FALLBACK_2 = "SELECTED_FALLBACK_2"
NO_FEASIBLE_APPROVED_CLASS = "NO_FEASIBLE_APPROVED_CLASS"

_STATUS_FOR_POSITION = {
    POSITION_PREFERRED: SELECTED_PREFERRED,
    POSITION_FALLBACK_1: SELECTED_FALLBACK_1,
    POSITION_FALLBACK_2: SELECTED_FALLBACK_2,
}

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


# --- Typed errors ----------------------------------------------------------
# Distinct types so a caller can tell a malformed file from an unapproved one
# from an attempt to use a class nobody approved.

class PolicyError(Exception):
    """Base class for every approved-class-policy failure."""


class PolicyFileError(PolicyError):
    """The policy file is missing, unreadable or has an unknown extension."""


class PolicyParseError(PolicyError):
    """The policy file exists but its structure or fields are malformed."""


class PolicyValidationError(PolicyError):
    """The policy parsed but violates a pilot invariant (count, duplicates...)."""


class UnapprovedClassError(PolicyError):
    """A class was requested for an Answer that never approved it."""


# --- Row model -------------------------------------------------------------

@dataclass(frozen=True)
class AnswerClassPolicy:
    """One Answer's approved class list: preferred plus two ordered fallbacks."""

    pilot_slot: int
    input_index: int
    answer_uri: str
    display_label: str
    preferred_class: str
    fallback_class_1: str
    fallback_class_2: str
    approval_status: str
    approval_date: str
    source_reconciliation_sha256: str

    @property
    def ordered_classes(self) -> tuple[str, str, str]:
        """The approved classes in the order a run must try them."""
        return (self.preferred_class, self.fallback_class_1, self.fallback_class_2)

    @property
    def ordered_positions(self) -> tuple[tuple[str, str], ...]:
        """((position, class_uri), ...) in approved order."""
        return tuple(zip(CLASS_POSITIONS, self.ordered_classes))

    def is_approved_class(self, class_uri: str) -> bool:
        return class_uri in self.ordered_classes

    def position_of(self, class_uri: str) -> Optional[str]:
        """Which approved position `class_uri` occupies, or None if unapproved."""
        for position, uri in self.ordered_positions:
            if uri == class_uri:
                return position
        return None

    def require_approved_class(self, class_uri: str) -> str:
        """Guard: raise unless `class_uri` is on this Answer's approved list.

        The single chokepoint that makes "no silent fallback to an unapproved
        class" enforceable rather than merely intended.
        """
        position = self.position_of(class_uri)
        if position is None:
            raise UnapprovedClassError(
                f"class {class_uri!r} is not approved for Answer "
                f"{self.answer_uri!r} (pilot slot {self.pilot_slot}); "
                f"approved: {list(self.ordered_classes)}"
            )
        return position


# --- Policy collection -----------------------------------------------------

@dataclass(frozen=True)
class PilotClassPolicy:
    """The nine approved Answers, in pilot order, plus file provenance."""

    answers: tuple[AnswerClassPolicy, ...]
    source_path: Optional[Path] = None
    source_sha256: Optional[str] = None
    source_format: Optional[str] = None

    def __len__(self) -> int:
        return len(self.answers)

    def __iter__(self) -> Iterator[AnswerClassPolicy]:
        return iter(self.answers)

    @property
    def answer_uris(self) -> tuple[str, ...]:
        return tuple(a.answer_uri for a in self.answers)

    @property
    def pilot_slots(self) -> tuple[int, ...]:
        return tuple(a.pilot_slot for a in self.answers)

    def by_slot(self, pilot_slot: int) -> AnswerClassPolicy:
        for a in self.answers:
            if a.pilot_slot == pilot_slot:
                return a
        raise KeyError(f"no approved Answer in pilot slot {pilot_slot}")

    def by_answer_uri(self, answer_uri: str) -> AnswerClassPolicy:
        for a in self.answers:
            if a.answer_uri == answer_uri:
                return a
        raise KeyError(f"Answer {answer_uri!r} is not in the approved pilot policy")


# --- Field-level parsing helpers ------------------------------------------

def _require_nonblank(row_label: str, name: str, value: object) -> str:
    if value is None:
        raise PolicyParseError(f"{row_label}: field {name!r} is missing")
    if not isinstance(value, str):
        raise PolicyParseError(
            f"{row_label}: field {name!r} must be a string, got {type(value).__name__}"
        )
    text = value.strip()
    if not text:
        raise PolicyParseError(f"{row_label}: field {name!r} is blank")
    return text


def _require_int(row_label: str, name: str, value: object) -> int:
    if isinstance(value, bool):          # bool is an int subclass; reject it
        raise PolicyParseError(f"{row_label}: field {name!r} must be an integer")
    if isinstance(value, int):
        return value
    text = _require_nonblank(row_label, name, value)
    try:
        return int(text)
    except ValueError as exc:
        raise PolicyParseError(
            f"{row_label}: field {name!r} must be an integer, got {text!r}"
        ) from exc


def _validate_approval(row_label: str, row: AnswerClassPolicy) -> None:
    """Approval-status validation. A blank or unknown token is never approved."""
    if row.approval_status != APPROVED_STATUS:
        raise PolicyValidationError(
            f"{row_label}: approval_status must be {APPROVED_STATUS!r}, "
            f"got {row.approval_status!r} — this Answer is NOT approved for the pilot"
        )
    if not _DATE_RE.match(row.approval_date):
        raise PolicyValidationError(
            f"{row_label}: approval_date must be ISO YYYY-MM-DD, "
            f"got {row.approval_date!r}"
        )
    if row.approval_date != EXPECTED_APPROVAL_DATE:
        raise PolicyValidationError(
            f"{row_label}: approval_date must be {EXPECTED_APPROVAL_DATE!r}, "
            f"got {row.approval_date!r}"
        )
    if not _SHA256_RE.match(row.source_reconciliation_sha256):
        raise PolicyValidationError(
            f"{row_label}: source_reconciliation_sha256 must be 64 lowercase hex "
            f"characters, got {row.source_reconciliation_sha256!r}"
        )
    if row.source_reconciliation_sha256 != EXPECTED_RECONCILIATION_SHA256:
        raise PolicyValidationError(
            f"{row_label}: source_reconciliation_sha256 does not match the "
            f"approved reconciliation package {EXPECTED_RECONCILIATION_SHA256}"
        )


def _build_row(row_label: str, raw: dict) -> AnswerClassPolicy:
    """Turn one already-key-checked mapping into a validated AnswerClassPolicy."""
    row = AnswerClassPolicy(
        pilot_slot=_require_int(row_label, "pilot_slot", raw.get("pilot_slot")),
        input_index=_require_int(row_label, "input_index", raw.get("input_index")),
        answer_uri=_require_nonblank(row_label, "answer_uri", raw.get("answer_uri")),
        display_label=_require_nonblank(
            row_label, "display_label", raw.get("display_label")),
        preferred_class=_require_nonblank(
            row_label, "preferred_class", raw.get("preferred_class")),
        fallback_class_1=_require_nonblank(
            row_label, "fallback_class_1", raw.get("fallback_class_1")),
        fallback_class_2=_require_nonblank(
            row_label, "fallback_class_2", raw.get("fallback_class_2")),
        approval_status=_require_nonblank(
            row_label, "approval_status", raw.get("approval_status")),
        approval_date=_require_nonblank(
            row_label, "approval_date", raw.get("approval_date")),
        source_reconciliation_sha256=_require_nonblank(
            row_label, "source_reconciliation_sha256",
            raw.get("source_reconciliation_sha256")),
    )
    _validate_approval(row_label, row)

    # An Answer cannot be its own distractor pool, and a repeated class would
    # make the "ordered fallback" record meaningless: position 2 would silently
    # re-test position 1 and the fallback count in the report would be wrong.
    if len(set(row.ordered_classes)) != 3:
        raise PolicyValidationError(
            f"{row_label}: preferred_class and the two fallbacks must be three "
            f"distinct classes, got {list(row.ordered_classes)}"
        )
    return row


def _validate_policy(answers: Sequence[AnswerClassPolicy]) -> None:
    """Collection-level invariants: exactly nine unique slots and Answer URIs."""
    if len(answers) != EXPECTED_PILOT_ANSWER_COUNT:
        raise PolicyValidationError(
            f"the approved pilot policy must contain exactly "
            f"{EXPECTED_PILOT_ANSWER_COUNT} Answers, got {len(answers)}"
        )

    slots = [a.pilot_slot for a in answers]
    if len(set(slots)) != len(slots):
        duplicates = sorted({s for s in slots if slots.count(s) > 1})
        raise PolicyValidationError(f"duplicate pilot_slot values: {duplicates}")
    if slots != list(range(1, EXPECTED_PILOT_ANSWER_COUNT + 1)):
        raise PolicyValidationError(
            f"pilot_slot values must be 1..{EXPECTED_PILOT_ANSWER_COUNT} in pilot "
            f"order, got {slots}"
        )

    uris = [a.answer_uri for a in answers]
    if len(set(uris)) != len(uris):
        duplicates = sorted({u for u in uris if uris.count(u) > 1})
        raise PolicyValidationError(f"duplicate answer_uri values: {duplicates}")

    indices = [a.input_index for a in answers]
    if len(set(indices)) != len(indices):
        duplicates = sorted({i for i in indices if indices.count(i) > 1})
        raise PolicyValidationError(f"duplicate input_index values: {duplicates}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Public loaders --------------------------------------------------------

def load_policy_csv(path: str | Path) -> PilotClassPolicy:
    """Load the approved policy from the CSV form. Strict about the header."""
    path = Path(path)
    if not path.is_file():
        raise PolicyFileError(f"approved class policy CSV not found: {path}")

    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = tuple(reader.fieldnames or ())
        if header != POLICY_CSV_FIELDS:
            raise PolicyParseError(
                f"{path.name}: unexpected CSV header.\n"
                f"  expected: {list(POLICY_CSV_FIELDS)}\n"
                f"  found:    {list(header)}"
            )
        rows = []
        for lineno, raw in enumerate(reader, start=2):
            row_label = f"{path.name} line {lineno}"
            # DictReader puts surplus columns under None and short rows get None
            # values; both mean the file is not the approved shape.
            if None in raw:
                raise PolicyParseError(f"{row_label}: more columns than the header")
            rows.append(_build_row(row_label, raw))

    _validate_policy(rows)
    return PilotClassPolicy(
        answers=tuple(rows),
        source_path=path,
        source_sha256=_sha256_file(path),
        source_format="csv",
    )


def load_policy_json(path: str | Path) -> PilotClassPolicy:
    """Load the approved policy from the JSON form. Strict about the shape."""
    path = Path(path)
    if not path.is_file():
        raise PolicyFileError(f"approved class policy JSON not found: {path}")

    with open(path, encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise PolicyParseError(f"{path.name}: invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise PolicyParseError(
            f"{path.name}: top level must be an object, got {type(payload).__name__}"
        )
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, list):
        raise PolicyParseError(f"{path.name}: key 'answers' must be a list")

    rows = []
    for position, raw in enumerate(raw_answers, start=1):
        row_label = f"{path.name} answers[{position - 1}]"
        if not isinstance(raw, dict):
            raise PolicyParseError(f"{row_label}: must be an object")
        missing = [k for k in POLICY_CSV_FIELDS if k not in raw]
        if missing:
            raise PolicyParseError(f"{row_label}: missing keys {missing}")
        unexpected = sorted(set(raw) - set(POLICY_CSV_FIELDS))
        if unexpected:
            raise PolicyParseError(f"{row_label}: unexpected keys {unexpected}")
        rows.append(_build_row(row_label, raw))

    _validate_policy(rows)
    return PilotClassPolicy(
        answers=tuple(rows),
        source_path=path,
        source_sha256=_sha256_file(path),
        source_format="json",
    )


def load_policy(path: str | Path) -> PilotClassPolicy:
    """Dispatch on the file extension. Unknown extensions are an error."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_policy_csv(path)
    if suffix == ".json":
        return load_policy_json(path)
    raise PolicyFileError(
        f"unsupported approved-policy file type {suffix!r} for {path}; "
        f"expected '.csv' or '.json'"
    )


def assert_policies_agree(csv_policy: PilotClassPolicy,
                          json_policy: PilotClassPolicy) -> None:
    """Both approved forms must describe the same nine Answers.

    Two hand-editable copies of the same approval will eventually diverge; this
    turns divergence into a loud failure instead of a run that depends on which
    file was loaded.
    """
    if csv_policy.answers != json_policy.answers:
        differing = [
            (c.pilot_slot, c.answer_uri, j.answer_uri)
            for c, j in zip(csv_policy.answers, json_policy.answers)
            if c != j
        ]
        raise PolicyValidationError(
            "the CSV and JSON approved policies disagree; "
            f"first differing slots: {differing[:3]}"
        )


# --- Ordered class selection ----------------------------------------------

@dataclass(frozen=True)
class ClassAttempt:
    """One approved class that was tried, and whether it passed the gate."""

    position: str
    class_uri: str
    feasible: bool
    detail: Optional[str] = None


@dataclass(frozen=True)
class ClassSelectionResult:
    """Outcome of walking one Answer's approved class list in order."""

    answer_uri: str
    status: str
    first_feasible_class: Optional[str]
    selected_position: Optional[str]
    attempts: tuple[ClassAttempt, ...]

    @property
    def has_feasible_class(self) -> bool:
        return self.status != NO_FEASIBLE_APPROVED_CLASS


def select_first_feasible_class(
    row: AnswerClassPolicy,
    is_feasible: Callable[[str], object],
) -> ClassSelectionResult:
    """Walk `row`'s three approved classes in order and stop at the first that fits.

    `is_feasible(class_uri)` decides the candidate gate for one class. It may
    return a bool, or any object with a truthy/falsy value plus an optional
    `detail` attribute that is copied into the provenance record.

    The walk considers exactly the three approved classes. If none is feasible
    the result is NO_FEASIBLE_APPROVED_CLASS and the Answer stays in the
    denominator — it is never rescued with an unapproved class.
    """
    attempts: list[ClassAttempt] = []
    for position, class_uri in row.ordered_positions:
        verdict = is_feasible(class_uri)
        detail = getattr(verdict, "detail", None)
        feasible = bool(verdict)
        attempts.append(ClassAttempt(
            position=position, class_uri=class_uri,
            feasible=feasible, detail=detail,
        ))
        if feasible:
            return ClassSelectionResult(
                answer_uri=row.answer_uri,
                status=_STATUS_FOR_POSITION[position],
                first_feasible_class=class_uri,
                selected_position=position,
                attempts=tuple(attempts),
            )

    return ClassSelectionResult(
        answer_uri=row.answer_uri,
        status=NO_FEASIBLE_APPROVED_CLASS,
        first_feasible_class=None,
        selected_position=None,
        attempts=tuple(attempts),
    )
