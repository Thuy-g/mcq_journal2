"""Prompt-8G audit derivations, re-computed from the FROZEN Prompt-8F-R1 records.

WHY THIS SCRIPT EXISTS
----------------------
Prompt 8G forbids changing R1 selection behaviour, but requires three audits the
R1 run did not write out: the exact Eisaku Sato selection trace (task section 4),
the pilot direct-identifier audit (section 5), and the measured effect of the
``rank_sum`` objective field (section 6).

So this module re-implements the selection objective *independently*, reading
only frozen machine-readable evidence, and asserts that its own result
reproduces ``selected_mcqs_v3_r1.jsonl`` exactly. That assertion is the point:
an audit derived from a re-implementation is trustworthy only if the
re-implementation demonstrably agrees with the artefact it audits. Nothing here
imports ``src.rationale_v3``.

READ-ONLY CONTRACT
------------------
Every path opened for reading lives under ``outputs/`` and is a frozen
scientific input. The only paths written are the audit targets named on the
command line. No network, no pinned-KG load, no mutation of any frozen input.

INPUTS
------
``evidence_audit_v3_r1.jsonl``   ``record_type=answer_fact_evidence`` gives, per
    Answer fact, the per-candidate evidence level plus the per-fact quality
    record. For Eisaku Sato the 60 such records ARE the full 60x24 table.
``candidate_ranking_handoff.jsonl``  the frozen Prompt-8D LRoleSim ranking
    (rank, score, canonical URI). LRoleSim is consumed purely as a structural
    plausibility ranker; no similarity is recomputed here.
``selected_mcqs_v3_r1.jsonl``    the R1 result, used only as the oracle.

THE OBJECTIVE BEING RE-DERIVED (smallest wins, exactly as the R1 selector)
--------------------------------------------------------------------------
  1. ``-lrolesim_score_sum``     maximise total structural plausibility
  2. ``-lrolesim_score_min``     maximise the weakest distractor
  3. ``minimum_rationale_size``  minimise |R*| via exact bitmask set cover
  4. the 14-field rationale ranking key (evidence profile first, then quality)
  5. ``candidate_rank_sum``      the field audited in section 6
  6. ``candidate_uris``          lexicographic last resort

Keys 1-3 are cheap for every combination; key 4 is materialised only for the
combinations still tied after keys 1-3, which is exact, because a combination
that already lost on keys 1-3 can never be rescued by a later key.

OPEN-WORLD LIMITATION carried through every number below: a fact absent from the
pinned snapshot is NOT a false fact. L1 records an observed alternative value,
never a proof that the candidate cannot also hold the Answer's object.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

# NOT_COVERED means the candidate SUPPORTS the Answer's proposition, so the fact
# discriminates nothing and covers nobody. It is tested before L0/L1/L2.
LEVEL_ORDER = {"NOT_COVERED": 0, "L0": 1, "L1": 2, "L2": 3}
POLICY_THRESHOLD = {"strict-l2": "L2", "main-l1": "L1", "diagnostic-l0": "L0"}
POLICY_ORDER = ("strict-l2", "main-l1", "diagnostic-l0")
K = 3
RHO = 3


class AnswerTable:
    """The frozen evidence table for one Answer: eligible facts x candidates."""

    def __init__(self, answer_uri, label, facts, candidates):
        self.answer_uri, self.label = answer_uri, label
        self.facts, self.candidates = facts, candidates
        # Ineligible facts are removed BEFORE any ranking: a rejected URL field
        # or an Answer-label leak is a hard FILTER, never a soft penalty.
        self.eligible = [i for i, f in enumerate(facts) if f["quality"]["eligible"]]

    def fact_mask(self, index, positions, threshold):
        """The k-bit coverage mask of ONE fact over ONE candidate combination.

        Bit i is set iff the fact covers ``positions[i]`` at or above threshold.
        IN and OUT never merge: direction is part of the fact identity upstream,
        so the two directions are simply two different facts here.
        """
        mask = 0
        for i, position in enumerate(positions):
            level = self.facts[index]["levels"][position]
            if LEVEL_ORDER[level] >= LEVEL_ORDER[threshold]:
                mask |= 1 << i
        return mask

    def local_anonymity(self, indices):
        """|S_local(R)|, its ratio, and whether R identifies the Answer alone.

        S_local(R) is the set of entities in {Answer} + the COMPLETE ranked
        candidate pool supporting every proposition in R; an entity supports a
        proposition exactly when the fact does not cover it. This is LOCAL: it
        says nothing about class members absent from the pool, nor about remote
        DBpedia.
        """
        pool = 1 + len(self.candidates)
        supporters = set(range(len(self.candidates)))
        for index in indices:
            supporters &= {p for p, lv in enumerate(self.facts[index]["levels"])
                           if lv == "NOT_COVERED"}
        count = 1 + len(supporters)
        return count, count / pool, count == 1


def cover_size_table(masks, k=K):
    """Minimum number of facts reaching each of the 2^k coverage masks.

    Exact minimum-cardinality set cover by bitmask DP over the k distractors.
    Unreachable masks hold k+1, strictly larger than any achievable cover size
    because |R*| <= k whenever a cover exists. Distinct masks suffice: a minimum
    cover never contains two facts carrying the same mask.
    """
    size, unreachable = 1 << k, k + 1
    table = [unreachable] * size
    table[0] = 0
    for mask in sorted({m for m in masks if m}):
        for covered, count in enumerate(list(table)):
            if count < unreachable and count + 1 < table[covered | mask]:
                table[covered | mask] = count + 1
    return table


def fact_quality_key(quality):
    """Per-fact ordering, smallest wins. Only single-fact components belong."""
    return (1 if quality["soft_leak"] else 0, quality["pedagogical_tier"],
            0 if quality["verbalizable"] else 1, quality["label_length"],
            quality["token_count"], (quality["predicate_uri"],
                                     quality["direction"],
                                     quality["counterpart_uri"]))


def score_rationale(table, positions, indices, threshold):
    """Objective key 4: the 14-field rationale ranking key, smallest wins."""
    per_candidate, counts, scoped, risk = [], {"L0": 0, "L1": 0, "L2": 0}, 0, 0
    for position in positions:
        best = "NOT_COVERED"
        for index in indices:
            level = table.facts[index]["levels"][position]
            if LEVEL_ORDER[level] > LEVEL_ORDER[best]:
                best = level
            if LEVEL_ORDER[level] < LEVEL_ORDER[threshold]:
                continue
            counts[level] += 1
            scoped += table.facts[index]["basis"][position] == "SCOPED_EMPIRICAL"
            risk += table.facts[index]["risk"][position] != "NONE"
        per_candidate.append(best)
    quality = [table.facts[i]["quality"] for i in indices]
    keys = [(q["predicate_uri"], q["direction"]) for q in quality]
    redundant = sum(1 for a, b in combinations(range(len(keys)), 2)
                    if keys[a] == keys[b])
    count, ratio, direct = table.local_anonymity(indices)
    total = lambda field: sum(q[field] for q in quality)  # noqa: E731
    unverbalizable = sum(1 for q in quality if not q["verbalizable"])
    key = (-LEVEL_ORDER[min(per_candidate, key=lambda x: LEVEL_ORDER[x])],
           -counts["L2"], -counts["L1"], counts["L0"], -scoped, risk,
           sum(1 for q in quality if q["soft_leak"]), total("pedagogical_tier"),
           unverbalizable, total("label_length"), total("token_count"),
           redundant, 1 if direct else 0,
           tuple(sorted((q["predicate_uri"], q["direction"],
                         q["counterpart_uri"]) for q in quality)))
    return {"key": key, "indices": indices, "per_candidate": per_candidate,
            "counts": counts, "scoped": scoped, "risk": risk,
            "anonymity": (count, ratio, direct),
            "unverbalizable": unverbalizable}


def rank_rationales(table, positions, policy):
    """Exact minimum cardinality, then every rationale of that size, ranked.

    Two exact steps. The DP gives the minimum size s at the policy threshold.
    Then the strongest level t at which a cover of the SAME size s still exists
    is found by re-running the size-only DP per level; that t is the maximum
    rationale_min_level over all minimum-cardinality rationales, because a
    size-s cover reaching t+1 would have made the minimum size at t+1 equal s.
    """
    threshold = POLICY_THRESHOLD[policy]
    full = (1 << len(positions)) - 1
    size = cover_size_table([table.fact_mask(i, positions, threshold)
                             for i in table.eligible])[full]
    if size > RHO:
        return None
    achieved = threshold
    for level in ("L2", "L1", "L0"):
        if LEVEL_ORDER[level] < LEVEL_ORDER[threshold]:
            break
        if cover_size_table([table.fact_mask(i, positions, level)
                             for i in table.eligible])[full] == size:
            achieved = level
            break
    usable = sorted((i for i in table.eligible
                     if table.fact_mask(i, positions, achieved)),
                    key=lambda i: fact_quality_key(table.facts[i]["quality"]))
    scored = []
    for combo in combinations(usable, size):
        covered = 0
        for index in combo:
            covered |= table.fact_mask(index, positions, achieved)
        if covered == full:
            scored.append(score_rationale(table, positions, combo, threshold))
    scored.sort(key=lambda item: item["key"])
    return {"size": size, "best": scored[0], "count": len(scored),
            "achieved_level": achieved} if scored else None


def evaluate(table, policy):
    """Every C(n,3) combination under one policy, with its objective parts.

    No pruning by rank, no beam, no early exit on the first feasible
    combination: a lower-ranked candidate replaces an uncovered higher-ranked
    one whenever the objective says so, which is the only reason the search
    looks past the provisional LRoleSim top three at all.

    Returns ``(feasible, ranked)``: every full-coverage combination with
    |R*| <= rho, and the subset still tied after objective keys 1-3, each
    carrying its materialised rationale key.
    """
    threshold = POLICY_THRESHOLD[policy]
    feasible, cache = [], {}
    for positions in combinations(range(len(table.candidates)), K):
        masks = tuple(sorted({table.fact_mask(i, positions, threshold)
                              for i in table.eligible} - {0}))
        if masks not in cache:
            cache[masks] = cover_size_table(masks)[(1 << K) - 1]
        if cache[masks] > RHO:
            continue
        scores = [table.candidates[p]["score"] for p in positions]
        feasible.append({
            "positions": positions, "scores": scores,
            "uris": tuple(table.candidates[p]["uri"] for p in positions),
            "ranks": [table.candidates[p]["rank"] for p in positions],
            "rank_sum": sum(table.candidates[p]["rank"] for p in positions),
            "size": cache[masks],
            "prefix": (-sum(scores), -min(scores), cache[masks])})
    if not feasible:
        return [], []
    best_prefix = min(c["prefix"] for c in feasible)
    ranked = []
    for combo in (c for c in feasible if c["prefix"] == best_prefix):
        ranking = rank_rationales(table, combo["positions"], policy)
        if ranking is not None:
            ranked.append({**combo, "ranking": ranking})
    return feasible, ranked


def select(table, use_rank_sum=True):
    """First policy in strict-L2 -> main-L1 -> diagnostic-L0 that is feasible.

    ``use_rank_sum=False`` drops objective key 5 ONLY; keys 1-4 and the
    lexicographic key 6 are untouched. That is the section-6 counterfactual.
    """
    for policy in POLICY_ORDER:
        feasible, ranked = evaluate(table, policy)
        if not ranked:
            continue
        tail = ((lambda c: (c["rank_sum"], c["uris"])) if use_rank_sum
                else (lambda c: (c["uris"],)))
        ranked.sort(key=lambda c: (c["ranking"]["best"]["key"], *tail(c)))
        # Combinations still tied after key 4 are exactly those rank_sum decides.
        best_key = ranked[0]["ranking"]["best"]["key"]
        tied = [c for c in ranked if c["ranking"]["best"]["key"] == best_key]
        return policy, ranked[0], feasible, tied
    return None, None, [], []


def load(audit_path, handoff_path):
    """Rebuild every Answer's evidence table from the frozen R1 records."""
    ranking = {json.loads(line)["answer_uri"]: json.loads(line)
               for line in Path(handoff_path).read_text("utf-8").splitlines()}
    raw = {}
    for line in Path(audit_path).read_text("utf-8").splitlines():
        record = json.loads(line)
        if record["record_type"] == "answer_fact_evidence":
            raw.setdefault(record["answer_uri"], []).append(record)
    tables = {}
    for uri, records in raw.items():
        records.sort(key=lambda r: r["fact_index"])
        row = ranking[uri]
        candidates = sorted(({"rank": c["rank"], "score": c["score"],
                              "uri": c["canonical_candidate_uri"]}
                             for c in row["ranked_candidates"]),
                            key=lambda c: c["rank"])
        facts = []
        for record in records:
            by_uri = {c["candidate_uri"]: c for c in record["per_candidate"]}
            facts.append({"quality": record["quality"],
                          "levels": [by_uri[c["uri"]]["evidence_level"]
                                     for c in candidates],
                          "basis": [by_uri[c["uri"]]["exclusion_basis"]
                                    for c in candidates],
                          "risk": [by_uri[c["uri"]]["granularity_risk"]
                                   for c in candidates]})
        tables[uri] = AnswerTable(uri, row["display_label"], facts, candidates)
    return tables


def derive(tables, selected_path):
    """Re-derive every pilot selection and check it against the R1 oracle."""
    rows = []
    for line in Path(selected_path).read_text("utf-8").splitlines():
        record = json.loads(line)
        table = tables[record["answer_uri"]]
        policy, best, feasible, tied = select(table)
        _, without, _, _ = select(table, use_rank_sum=False)
        facts = sorted((table.facts[i]["quality"]["predicate_uri"],
                        table.facts[i]["quality"]["direction"],
                        table.facts[i]["quality"]["counterpart_uri"])
                       for i in best["ranking"]["best"]["indices"])
        oracle = sorted((f["predicate_uri"], f["direction"],
                         f["claim_object_uri"])
                        for f in record["selected_rationale"])
        rows.append({
            "table": table, "record": record, "policy": policy, "best": best,
            "without": without, "feasible": feasible, "tied": tied,
            "reproduced": (policy == record["evidence_policy"]
                           and list(best["uris"]) == [d["candidate_uri"] for d
                                                      in record["distractors"]]
                           and facts == oracle)})
    return rows


def proper_name_signal(label):
    """A deliberately weak, purely orthographic signal.

    Every DBpedia resource label is capitalised by convention, so capitalisation
    alone carries no information. Only a MULTI-token label whose tokens are
    mostly capitalised is treated as a strong proper-name signal; a single token
    stays explicitly AMBIGUOUS (``Diamond`` and ``Tokyo`` are indistinguishable
    orthographically). No POS tagger or embedding is used, by task constraint.
    """
    tokens = [t for t in label.replace("_", " ").split() if t]
    capitalised = sum(1 for t in tokens if t[:1].isupper())
    if len(tokens) >= 2 and capitalised >= 2:
        return "MULTI_TOKEN_PROPER_NAME"
    return "SINGLE_TOKEN_CAPITALIZED_AMBIGUOUS"


def rank_sum_rows(rows):
    """Section 6: does objective key 5 change anything the pilot can observe?"""
    out = []
    for row in rows:
        tied, best, without = row["tied"], row["best"], row["without"]
        rank_sums = {c["rank_sum"] for c in tied}
        out.append({
            "answer_uri": row["table"].answer_uri,
            "display_label": row["table"].label,
            "evidence_policy": row["policy"],
            "feasible_combination_count": len(row["feasible"]),
            "combinations_tied_after_objective_key_4": len(tied),
            "rank_sum_tiebreak_reached": len(tied) > 1,
            "distinct_rank_sums_among_tied": len(rank_sums),
            "rank_sum_decided_the_tie": len(tied) > 1 and len(rank_sums) > 1,
            "selected_ranks_with_rank_sum": "|".join(map(str, best["ranks"])),
            "selected_ranks_without_rank_sum": "|".join(map(str,
                                                            without["ranks"])),
            "selection_changed_when_rank_sum_removed":
                list(best["uris"]) != list(without["uris"]),
            "candidate_rank_sum": best["rank_sum"]})
    return out


def direct_identifier_rows(rows):
    """Section 5: local-uniqueness diagnostics. Strictly descriptive."""
    out = []
    for row in rows:
        table, best = row["table"], row["best"]
        indices = best["ranking"]["best"]["indices"]
        quality = [table.facts[i]["quality"] for i in indices]
        count, ratio, direct = table.local_anonymity(indices)
        joined = lambda fn: "|".join(fn(q) for q in quality)  # noqa: E731
        out.append({
            "answer_uri": table.answer_uri,
            "display_label": table.label,
            "selected_distractor_uris": "|".join(best["uris"]),
            "selected_distractor_ranks": "|".join(map(str, best["ranks"])),
            "rationale_size": len(indices),
            "rationale_predicates": joined(lambda q: q["predicate_uri"]),
            "rationale_directions": joined(lambda q: q["direction"]),
            "rationale_objects": joined(lambda q: q["counterpart_uri"]),
            "rationale_object_labels": joined(lambda q: q["display_label"]),
            "local_candidate_pool_size": 1 + len(table.candidates),
            "local_candidate_pool_anonymity_count": count,
            "local_candidate_pool_anonymity_ratio": round(ratio, 6),
            "direct_identifier_flag": direct,
            "per_fact_anonymity_count":
                "|".join(str(table.local_anonymity((i,))[0]) for i in indices),
            "object_proper_name_signal":
                joined(lambda q: proper_name_signal(q["display_label"])),
            "rationale_verbalizable": joined(lambda q: str(q["verbalizable"])),
            "rationale_template_ids": joined(lambda q: q["template_id"]),
            "rationale_pedagogical_tiers":
                joined(lambda q: str(q["pedagogical_tier"])),
            "risk_category": ("UNIQUE_IN_LOCAL_POOL" if direct
                              else "SHARED_IN_LOCAL_POOL")})
    return out


def write_csv(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"wrote {path} ({len(records)} rows)")


def main():
    parser = argparse.ArgumentParser(description="Prompt-8G audit derivations")
    parser.add_argument("--r1-dir",
                        default="outputs/journal2_week2_rationale_v3_r1_2026-08-03")
    parser.add_argument("--handoff-dir",
                        default="outputs/journal2_week2_extract_integration_2026-07-30")
    parser.add_argument("--rank-sum-csv", default="")
    parser.add_argument("--direct-identifier-csv", default="")
    args = parser.parse_args()

    r1 = Path(args.r1_dir)
    tables = load(r1 / "evidence_audit_v3_r1.jsonl",
                  Path(args.handoff_dir) / "candidate_ranking_handoff.jsonl")
    rows = derive(tables, r1 / "selected_mcqs_v3_r1.jsonl")
    for row in rows:
        print(f"{'OK ' if row['reproduced'] else 'MISMATCH'} {row['table'].label}")
    if not all(row["reproduced"] for row in rows):
        raise SystemExit("re-derivation does not reproduce R1; audits withheld")
    if args.rank_sum_csv:
        write_csv(args.rank_sum_csv, rank_sum_rows(rows))
    if args.direct_identifier_csv:
        write_csv(args.direct_identifier_csv, direct_identifier_rows(rows))


if __name__ == "__main__":
    main()
