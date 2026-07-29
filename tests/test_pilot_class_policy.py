############################################################################
# tests/test_pilot_class_policy.py
#
# Contract tests for src/classes/policy.py — the approved-class policy of the
# nine-Answer engineering pilot.
#
# What these tests defend:
#   * the pilot is exactly nine Answers, no more and no fewer;
#   * a duplicated Answer is rejected, not silently deduplicated;
#   * a blank or unrecognised approval token is never treated as approval;
#   * the ordered fallback list is preserved verbatim from the reconciliation;
#   * a class nobody approved can never reach a run, and exhausting the approved
#     list produces NO_FEASIBLE_APPROVED_CLASS rather than a substitute class.
#
# Offline and deterministic: reads only committed files under data/ and
# temporary files written by the test itself. No network, no SPARQL, no SBERT.
#
# Run:
#     python -m pytest -vv tests/test_pilot_class_policy.py
############################################################################

from __future__ import annotations

import csv
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from classes import policy as pol  # noqa: E402

POLICY_CSV = REPO_ROOT / "data" / "pilot_class_policy_v1.csv"
POLICY_JSON = REPO_ROOT / "data" / "pilot_class_policy_v1.json"
PLAN_CSV = (REPO_ROOT / "outputs" / "journal2_pdf_grounded_reconciliation_2026-07-30"
            / "pilot_measurement_plan.csv")

DBR = "http://dbpedia.org/resource/"

# The nine approved (display_label, preferred_class) pairs, transcribed from the
# researcher's explicit approval. Independent of the loader, so a change to
# either the data file or the loader shows up here.
EXPECTED_PREFERRED = (
    ("Shinya Yamanaka", "Category:Japanese_Nobel_laureates"),
    ("Shin'ichirō Tomonaga", "Category:Japanese_Nobel_laureates"),
    ("Eisaku Satō", "Category:Japanese_Nobel_laureates"),
    ("Carbon", "Category:Reactive_nonmetals"),
    ("Silicon", "Category:Group_IV_semiconductors"),
    ("Sulfuric acid", "Category:Mineral_acids"),
    ("Aristotle", "Category:Ancient_Greek_ethicists"),
    ("Plato", "Category:Ancient_Greek_ethicists"),
    ("Adam Smith", "Category:Classical_economists"),
)


@pytest.fixture(scope="module")
def csv_policy() -> pol.PilotClassPolicy:
    return pol.load_policy_csv(POLICY_CSV)


@pytest.fixture(scope="module")
def json_policy() -> pol.PilotClassPolicy:
    return pol.load_policy_json(POLICY_JSON)


def _row_dicts() -> list[dict]:
    """The committed CSV as plain dicts, for building mutated temporary copies."""
    with open(POLICY_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pol.POLICY_CSV_FIELDS),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path


# --- Exactly nine approved pilot Answers ----------------------------------

def test_policy_has_exactly_nine_answers(csv_policy):
    assert len(csv_policy) == 9
    assert len(csv_policy.answers) == pol.EXPECTED_PILOT_ANSWER_COUNT


def test_pilot_slots_are_one_to_nine_in_order(csv_policy):
    assert csv_policy.pilot_slots == (1, 2, 3, 4, 5, 6, 7, 8, 9)


def test_answer_uris_are_unique(csv_policy):
    uris = csv_policy.answer_uris
    assert len(set(uris)) == 9


def test_nine_approved_preferred_classes_are_the_approved_ones(csv_policy):
    got = tuple((a.display_label, a.preferred_class) for a in csv_policy)
    expected = tuple((label, DBR + cls) for label, cls in EXPECTED_PREFERRED)
    assert got == expected


def test_every_row_carries_the_approved_status_and_provenance(csv_policy):
    for a in csv_policy:
        assert a.approval_status == pol.APPROVED_STATUS
        assert a.approval_date == "2026-07-30"
        assert a.source_reconciliation_sha256 == (
            "14e3f68f1866b74d16f9b2948025ea7e8f68dd0a816df633e9c9126f49bbe951")


def test_loader_records_the_policy_file_sha256(csv_policy):
    assert csv_policy.source_sha256 is not None
    assert len(csv_policy.source_sha256) == 64
    assert csv_policy.source_format == "csv"


def test_csv_and_json_forms_describe_the_same_nine_answers(csv_policy, json_policy):
    pol.assert_policies_agree(csv_policy, json_policy)
    assert csv_policy.answers == json_policy.answers


def test_load_policy_dispatches_on_extension():
    assert len(pol.load_policy(POLICY_CSV)) == 9
    assert len(pol.load_policy(POLICY_JSON)) == 9
    with pytest.raises(pol.PolicyFileError):
        pol.load_policy(POLICY_CSV.with_suffix(".yaml"))


# --- Fallback order preservation -------------------------------------------

def test_fallbacks_are_copied_verbatim_from_the_reconciliation_plan(csv_policy):
    """The approved plan is the source of truth for the ordered fallbacks."""
    with open(PLAN_CSV, encoding="utf-8", newline="") as f:
        plan = {int(r["pilot_slot"]): r for r in csv.DictReader(f)}

    assert len(plan) == 9
    for a in csv_policy:
        row = plan[a.pilot_slot]
        expected_fallbacks = tuple(
            x.strip() for x in row["ordered_approved_fallbacks"].split("|"))
        assert len(expected_fallbacks) == 2
        assert a.answer_uri == row["answer_uri"].strip()
        assert a.input_index == int(row["input_index"])
        assert a.preferred_class == row["preferred_class"].strip()
        assert (a.fallback_class_1, a.fallback_class_2) == expected_fallbacks


def test_ordered_classes_are_preferred_then_fallback_1_then_fallback_2(csv_policy):
    a = csv_policy.by_slot(7)                              # Aristotle
    assert a.display_label == "Aristotle"
    assert a.ordered_classes == (
        DBR + "Category:Ancient_Greek_ethicists",
        DBR + "Category:Peripatetic_philosophers",
        DBR + "Category:Ancient_Greek_philosophers_of_mind",
    )
    assert a.ordered_positions == (
        ("preferred", DBR + "Category:Ancient_Greek_ethicists"),
        ("fallback_1", DBR + "Category:Peripatetic_philosophers"),
        ("fallback_2", DBR + "Category:Ancient_Greek_philosophers_of_mind"),
    )


def test_selection_tries_approved_classes_in_order(csv_policy):
    a = csv_policy.by_slot(4)                              # Carbon
    tried: list[str] = []

    def is_feasible(class_uri: str) -> bool:
        tried.append(class_uri)
        return class_uri == a.fallback_class_2              # only the last passes

    result = pol.select_first_feasible_class(a, is_feasible)
    assert tried == list(a.ordered_classes)                # exact order, no extras
    assert result.status == pol.SELECTED_FALLBACK_2
    assert result.first_feasible_class == a.fallback_class_2
    assert result.selected_position == "fallback_2"
    assert [t.feasible for t in result.attempts] == [False, False, True]


def test_selection_stops_at_the_first_feasible_class(csv_policy):
    a = csv_policy.by_slot(1)
    tried: list[str] = []

    def is_feasible(class_uri: str) -> bool:
        tried.append(class_uri)
        return True

    result = pol.select_first_feasible_class(a, is_feasible)
    assert tried == [a.preferred_class]                    # fallbacks never touched
    assert result.status == pol.SELECTED_PREFERRED
    assert result.selected_position == "preferred"


# --- No unapproved runtime class -------------------------------------------

def test_exhausting_the_approved_list_yields_no_feasible_approved_class(csv_policy):
    a = csv_policy.by_slot(5)                              # Silicon
    tried: list[str] = []

    def never_feasible(class_uri: str) -> bool:
        tried.append(class_uri)
        return False

    result = pol.select_first_feasible_class(a, never_feasible)
    assert tried == list(a.ordered_classes)                # exactly three, no fourth
    assert result.status == pol.NO_FEASIBLE_APPROVED_CLASS
    assert result.first_feasible_class is None
    assert result.selected_position is None
    assert result.has_feasible_class is False
    assert len(result.attempts) == 3


def test_selection_never_returns_a_class_outside_the_approved_list(csv_policy):
    """Whatever the gate says, the outcome is an approved class or nothing."""
    for a in csv_policy:
        for gate in (lambda _u: True, lambda _u: False):
            result = pol.select_first_feasible_class(a, gate)
            if result.first_feasible_class is not None:
                assert a.is_approved_class(result.first_feasible_class)
            for attempt in result.attempts:
                assert a.is_approved_class(attempt.class_uri)


def test_require_approved_class_rejects_an_unapproved_class(csv_policy):
    a = csv_policy.by_slot(8)                              # Plato
    assert a.require_approved_class(a.preferred_class) == "preferred"
    assert a.require_approved_class(a.fallback_class_1) == "fallback_1"
    with pytest.raises(pol.UnapprovedClassError):
        a.require_approved_class(DBR + "Category:Ancient_Greek_philosophers")


def test_an_unapproved_class_of_another_answer_is_still_unapproved(csv_policy):
    """Aristotle's fallback must not leak into Plato, and the reverse.

    4th-century_BC_Greek_philosophers is batch-derived for Plato but absent from
    all of Aristotle's categories, which is exactly why classes are approved per
    Answer and never transferred across Answers.
    """
    aristotle = csv_policy.by_slot(7)
    plato = csv_policy.by_slot(8)
    plato_only = DBR + "Category:4th-century_BC_Greek_philosophers"

    assert plato.is_approved_class(plato_only)
    assert not aristotle.is_approved_class(plato_only)
    with pytest.raises(pol.UnapprovedClassError):
        aristotle.require_approved_class(plato_only)


def test_answer_lookup_rejects_an_answer_outside_the_pilot(csv_policy):
    with pytest.raises(KeyError):
        csv_policy.by_answer_uri(DBR + "Immanuel_Kant")
    with pytest.raises(KeyError):
        csv_policy.by_slot(10)


# --- Duplicate rejection ---------------------------------------------------

def test_duplicate_answer_uri_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[1]["answer_uri"] = rows[0]["answer_uri"]
    path = _write_csv(tmp_path / "dup_answer.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="duplicate answer_uri"):
        pol.load_policy_csv(path)


def test_duplicate_pilot_slot_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[1]["pilot_slot"] = rows[0]["pilot_slot"]
    path = _write_csv(tmp_path / "dup_slot.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="duplicate pilot_slot"):
        pol.load_policy_csv(path)


def test_duplicate_input_index_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[2]["input_index"] = rows[0]["input_index"]
    path = _write_csv(tmp_path / "dup_index.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="duplicate input_index"):
        pol.load_policy_csv(path)


def test_duplicate_answer_in_json_form_is_rejected(tmp_path):
    payload = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
    payload["answers"][3]["answer_uri"] = payload["answers"][0]["answer_uri"]
    path = tmp_path / "dup_answer.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(pol.PolicyValidationError, match="duplicate answer_uri"):
        pol.load_policy_json(path)


def test_a_class_repeated_inside_one_row_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[0]["fallback_class_2"] = rows[0]["preferred_class"]
    path = _write_csv(tmp_path / "repeat_class.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="three\\s+distinct classes"):
        pol.load_policy_csv(path)


# --- Blank / wrong approval rejection --------------------------------------

def test_blank_approval_status_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[4]["approval_status"] = ""
    path = _write_csv(tmp_path / "blank_status.csv", rows)
    with pytest.raises(pol.PolicyParseError, match="approval_status.*blank"):
        pol.load_policy_csv(path)


def test_whitespace_only_approval_status_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[4]["approval_status"] = "   "
    path = _write_csv(tmp_path / "ws_status.csv", rows)
    with pytest.raises(pol.PolicyParseError, match="approval_status.*blank"):
        pol.load_policy_csv(path)


def test_unrecognised_approval_status_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[0]["approval_status"] = "PENDING"
    path = _write_csv(tmp_path / "pending.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="NOT approved"):
        pol.load_policy_csv(path)


def test_blank_approval_date_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[0]["approval_date"] = ""
    path = _write_csv(tmp_path / "blank_date.csv", rows)
    with pytest.raises(pol.PolicyParseError, match="approval_date.*blank"):
        pol.load_policy_csv(path)


def test_malformed_approval_date_is_rejected(tmp_path):
    rows = _row_dicts()
    for r in rows:
        r["approval_date"] = "30/07/2026"
    path = _write_csv(tmp_path / "bad_date.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="ISO YYYY-MM-DD"):
        pol.load_policy_csv(path)


def test_wrong_reconciliation_sha256_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[0]["source_reconciliation_sha256"] = "0" * 64
    path = _write_csv(tmp_path / "bad_sha.csv", rows)
    with pytest.raises(pol.PolicyValidationError,
                       match="does not match the .*reconciliation package"):
        pol.load_policy_csv(path)


def test_blank_fallback_class_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[3]["fallback_class_2"] = ""
    path = _write_csv(tmp_path / "blank_fb.csv", rows)
    with pytest.raises(pol.PolicyParseError, match="fallback_class_2.*blank"):
        pol.load_policy_csv(path)


# --- Count and shape -------------------------------------------------------

def test_eight_answers_is_rejected(tmp_path):
    rows = _row_dicts()[:8]
    path = _write_csv(tmp_path / "eight.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="exactly 9 Answers"):
        pol.load_policy_csv(path)


def test_a_tenth_answer_is_rejected(tmp_path):
    """The remaining 25 Answers are NOT approved; appending one must fail."""
    rows = _row_dicts()
    extra = dict(rows[0])
    extra.update({
        "pilot_slot": "10",
        "input_index": "31",
        "answer_uri": DBR + "Immanuel_Kant",
        "display_label": "Immanuel Kant",
    })
    rows.append(extra)
    path = _write_csv(tmp_path / "ten.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="exactly 9 Answers"):
        pol.load_policy_csv(path)


def test_non_contiguous_pilot_slots_are_rejected(tmp_path):
    rows = _row_dicts()
    rows[8]["pilot_slot"] = "11"
    path = _write_csv(tmp_path / "gap.csv", rows)
    with pytest.raises(pol.PolicyValidationError, match="must be 1..9 in pilot order"):
        pol.load_policy_csv(path)


def test_unexpected_csv_header_is_rejected(tmp_path):
    path = tmp_path / "bad_header.csv"
    path.write_text("pilot_slot,answer_uri\n1,x\n", encoding="utf-8")
    with pytest.raises(pol.PolicyParseError, match="unexpected CSV header"):
        pol.load_policy_csv(path)


def test_non_integer_pilot_slot_is_rejected(tmp_path):
    rows = _row_dicts()
    rows[0]["pilot_slot"] = "first"
    path = _write_csv(tmp_path / "bad_slot.csv", rows)
    with pytest.raises(pol.PolicyParseError, match="must be an integer"):
        pol.load_policy_csv(path)


def test_missing_policy_file_raises_a_typed_error(tmp_path):
    with pytest.raises(pol.PolicyFileError):
        pol.load_policy_csv(tmp_path / "absent.csv")
    with pytest.raises(pol.PolicyFileError):
        pol.load_policy_json(tmp_path / "absent.json")


def test_json_with_unexpected_key_is_rejected(tmp_path):
    payload = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
    payload["answers"][0]["approved_by"] = "someone"
    path = tmp_path / "extra_key.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(pol.PolicyParseError, match="unexpected keys"):
        pol.load_policy_json(path)


def test_json_missing_answers_key_is_rejected(tmp_path):
    path = tmp_path / "no_answers.json"
    path.write_text(json.dumps({"policy_version": "x"}), encoding="utf-8")
    with pytest.raises(pol.PolicyParseError, match="'answers' must be a list"):
        pol.load_policy_json(path)


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(pol.PolicyParseError, match="invalid JSON"):
        pol.load_policy_json(path)


def test_divergent_csv_and_json_forms_are_rejected(tmp_path):
    payload = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
    payload["answers"][2]["fallback_class_1"] = DBR + "Category:Something_else"
    path = tmp_path / "diverged.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(pol.PolicyValidationError, match="disagree"):
        pol.assert_policies_agree(pol.load_policy_csv(POLICY_CSV),
                                  pol.load_policy_json(path))
