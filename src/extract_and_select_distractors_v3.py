############################################################################
# src/extract_and_select_distractors_v3.py
#
# VERSIONED V3 ENTRYPOINT  (Prompt 8F, revision R1)
#
# WHY A NEW FILE RATHER THAN A NEW MODE ON THE OLD ONE
#   src/extract_221_and_select_distractors_ClaudeWeb_v2.py is the Prompt-8E
#   entrypoint and must stay an EXECUTABLE FROZEN BASELINE: the comparison is
#   only meaningful if 8E can still be re-run and byte-compared. Adding a mode
#   there would have changed its hash and destroyed that.
#
# WHAT THIS FILE OWNS
#   Argument parsing and mode dispatch. Nothing else. Set-cover dynamic
#   programming, semantic closure, evidence-level logic, quality scoring and
#   combination enumeration live in src/rationale_v3/; orchestration lives in
#   src/pipeline/rationale_v3_run.py. AUDIT §9.2 traces the legacy pipeline's
#   unreviewable size to an entrypoint that accumulated exactly these.
#
# THE MODE IS MANDATORY — there is no default, and an unknown mode is an error.
#
#   pilot-rationale-v3-r1   PROPOSED. Strictly offline. Consumes the frozen
#                           Prompt-8D handoff and the cached semantic index,
#                           assigns evidence levels and the exclusion basis,
#                           applies the hard quality filters, solves exact
#                           minimum-cardinality set cover, ranks rationales
#                           pedagogically, and selects distractors.
#   build-semantic-index    SETUP. The ONE place permitted to open the pinned
#                           1.2 GB pickle, writing a cache keyed on the KG hash,
#                           the policy hash, the source-object list and depth.
#
# Stops before verbalization, final Bipartite Graph selection, fallback-class
# execution and human evaluation. Every fact written is OBSERVED in the pinned
# snapshot; no absence is reported as falsity (CLAUDE.md items 7 and 8).
############################################################################

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

MODE_RATIONALE_V3_R1 = "pilot-rationale-v3-r1"
MODE_BUILD_SEMANTIC_INDEX = "build-semantic-index"
MODES = (MODE_RATIONALE_V3_R1, MODE_BUILD_SEMANTIC_INDEX)

#: Defaults are spelled as strings here so that parsing arguments never imports
#: the rationale layer, and a test asserts they agree with the pipeline module's
#: own constants rather than trusting the duplication.
DEFAULT_OUTPUT_DIR = str(
    REPO_ROOT / "outputs" / "journal2_week2_rationale_v3_r1_2026-08-03")
DEFAULT_PROMPT8D_DIR = str(
    REPO_ROOT / "outputs" / "journal2_week2_extract_integration_2026-07-30")
DEFAULT_PROMPT8E_DIR = str(
    REPO_ROOT / "outputs" / "journal2_week2_rationale_selection_2026-08-01")
DEFAULT_PROMPT8F_DIR = str(
    REPO_ROOT / "outputs" / "journal2_week2_rationale_v3_2026-08-03")
DEFAULT_SEMANTIC_INDEX_CACHE = str(
    REPO_ROOT / "data" / "semantic_index_v3" / "pilot_place_containment_v1.json")
DEFAULT_LOCAL_KG = str(
    REPO_ROOT / "data" / "infobox.pickle_EnglishVersion_EntityType")


class UnknownModeError(Exception):
    """A mode was requested that this entrypoint does not implement.

    Raised instead of defaulting: a run that silently did something other than
    what was asked would be a false experimental claim.
    """


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python src/extract_and_select_distractors_v3.py",
        description=("Journal-2 rationale V3 entrypoint (Prompt 8F-R1). The "
                     "mode is mandatory: there is no default, and an unknown "
                     "mode is an error rather than a fall-through."))
    parser.add_argument("--mode", choices=MODES, required=True,
                        help=(f"{MODE_RATIONALE_V3_R1}: proposed path, offline, "
                              f"evidence levels + exclusion basis + quality "
                              f"filters + exact set cover + scalable distractor "
                              f"search over the frozen Prompt-8D handoff. "
                              f"{MODE_BUILD_SEMANTIC_INDEX}: read the pinned "
                              f"local KG once and write the bounded "
                              f"semantic-index cache."))
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt8d-dir", default=DEFAULT_PROMPT8D_DIR)
    parser.add_argument("--prompt8e-dir", default=DEFAULT_PROMPT8E_DIR)
    parser.add_argument("--prompt8f-dir", default=DEFAULT_PROMPT8F_DIR)
    parser.add_argument("--semantic-index-cache",
                        default=DEFAULT_SEMANTIC_INDEX_CACHE)
    parser.add_argument("--local-kg", default=DEFAULT_LOCAL_KG,
                        help="build-semantic-index only")
    parser.add_argument("-k", type=int, default=3,
                        help="distractors per question (1 <= k <= 5)")
    parser.add_argument("--rho", type=int, default=3,
                        help=("the largest rationale that may be presented. A "
                              "PRESENTATION budget, not a correctness "
                              "parameter."))
    parser.add_argument("--max-exact-combinations", type=int, default=200000,
                        help=("above this many three-candidate combinations the "
                              "search switches from FULL_EXACT to POOL_EXACT"))
    parser.add_argument("--skip-reduced-arm", action="store_true",
                        help="omit the REDUCED arm of the four-way comparison")
    parser.add_argument("--quiet", action="store_true")
    return parser


def dispatch(mode: str, args: argparse.Namespace,
             raw_command: Sequence[str] = ()) -> int:
    """Route to exactly one named mode, or refuse.

    Both branches import the pipeline module INSIDE the branch, so parsing
    arguments never pulls in the rationale layer and `build-semantic-index` is
    the only path on which `kg.loader` is ever imported.
    """
    if mode == MODE_RATIONALE_V3_R1:
        from pipeline import rationale_v3_run          # local: mode-scoped
        from rationale_v3.selector import PoolPolicy   # local: mode-scoped

        run = rationale_v3_run.run_rationale_v3(
            prompt8d_dir=args.prompt8d_dir,
            semantic_cache_path=args.semantic_index_cache,
            k=args.k, rho=args.rho,
            pool_policy=PoolPolicy(
                max_exact_combinations=args.max_exact_combinations),
            run_reduced_arm=not args.skip_reduced_arm,
            verbose=not args.quiet)
        out_dir = rationale_v3_run.write_all_outputs(
            run, args.output_dir, raw_command, args.prompt8e_dir,
            args.prompt8f_dir)
        rationale_v3_run.print_run_summary(run, out_dir)
        return 0

    if mode == MODE_BUILD_SEMANTIC_INDEX:
        from pipeline import rationale_v3_run          # local: mode-scoped

        path = rationale_v3_run.build_semantic_index_from_pinned_kg(
            prompt8d_dir=args.prompt8d_dir, local_kg_path=args.local_kg,
            cache_path=args.semantic_index_cache, verbose=not args.quiet)
        print(f"\n[done] semantic index cache -> {path}")
        print("       the pinned local KG was read ONCE, read-only, and was "
              "neither rebuilt nor modified")
        return 0

    raise UnknownModeError(
        f"unknown mode {mode!r}; expected one of {MODES}. There is no default "
        f"mode.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    raw_command = ["python", "src/extract_and_select_distractors_v3.py", *argv]
    return dispatch(args.mode, args, raw_command)


if __name__ == "__main__":
    raise SystemExit(main())
