############################################################################
# src/lrolesim/adapter.py
#
# Thin adapter over src/MCQ_lrolesim_ClaudeWeb_v2.py for the nine-Answer pilot.
#
# PRIMARY PILOT CONFIGURATION (architecture_decision_v2.md section 1;
# LRoleSim paper, printed p. 436: "We set the parameters as beta = 0.2 and k = 3")
#     measure       = lrolesim_ed
#     lrolesim_beta = 0.2
#     iterations    = 3        (fixed; NO convergence test)
#
# ABLATION
#     measure       = lrolesim_edt      (needs an entity-type map)
#     iterations    = convergence       (explicitly a different API)
#
# THE TWO BETAS ARE NOT THE SAME NUMBER
#   `lrolesim_beta` here is the LRoleSim decay factor from the published kernel.
#   The extractors' `BETA` is the OverlapLoose weight of OverlapScore
#   (= alpha * OverlapStrict + beta * OverlapLoose). They are unrelated
#   quantities that happened to share a name. This module therefore exposes ONLY
#   `lrolesim_beta` and actively rejects a keyword called `beta`, so an
#   Experimental Setup table can never conflate the two.
#
# SCOPE
#   Ranking only. No candidate retrieval, no rationale, no verbalization.
#   This module does not build the graph either — it consumes a node set and the
#   induced neighbour maps produced by src/kg/graph_view.py.
############################################################################

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

# --- Frozen pilot configuration -------------------------------------------
PILOT_MEASURE = "lrolesim_ed"
ABLATION_MEASURE = "lrolesim_edt"
PILOT_LROLESIM_BETA = 0.2
PILOT_ITERATIONS = 3

# Convergence-ablation defaults, matching the kernel's own preserved path.
CONVERGENCE_MAX_ITER = 20
CONVERGENCE_TOL = 1e-4

_KERNEL_MODULE_NAME = "MCQ_lrolesim_ClaudeWeb_v2"
_SRC_DIR = Path(__file__).resolve().parent.parent


class LRoleSimAdapterError(Exception):
    """Base class for adapter-level failures."""


class KernelNotAvailableError(LRoleSimAdapterError):
    """The LRoleSim kernel module could not be imported."""


class LRoleSimConfigError(LRoleSimAdapterError):
    """The requested LRoleSim configuration is not usable for the pilot."""


def load_kernel():
    """Import the LRoleSim kernel module without mutating sys.path.

    Tries a normal import first (the repo convention is to put src/ on sys.path),
    then falls back to loading the file by explicit path. The fallback keeps the
    adapter importable from a plain repo-root checkout while still binding to the
    one kernel file this task is allowed to touch.
    """
    if _KERNEL_MODULE_NAME in sys.modules:
        return sys.modules[_KERNEL_MODULE_NAME]
    try:
        return importlib.import_module(_KERNEL_MODULE_NAME)
    except ImportError:
        pass

    kernel_path = _SRC_DIR / f"{_KERNEL_MODULE_NAME}.py"
    if not kernel_path.is_file():
        raise KernelNotAvailableError(f"LRoleSim kernel not found at {kernel_path}")
    spec = importlib.util.spec_from_file_location(_KERNEL_MODULE_NAME, kernel_path)
    if spec is None or spec.loader is None:
        raise KernelNotAvailableError(f"cannot load LRoleSim kernel from {kernel_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_KERNEL_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


# --- Configuration ---------------------------------------------------------

@dataclass(frozen=True)
class LRoleSimConfig:
    """One fully specified LRoleSim run configuration.

    `iterations` is a fixed count. There is deliberately no `tol` field: a
    configuration that could stop early is a different execution path, reached
    through `run_lrolesim_until_convergence()`.
    """

    measure: str = PILOT_MEASURE
    lrolesim_beta: float = PILOT_LROLESIM_BETA
    iterations: int = PILOT_ITERATIONS

    def __post_init__(self) -> None:
        kernel = load_kernel()
        if self.measure not in kernel.MEASURES:
            raise LRoleSimConfigError(
                f"unknown measure {self.measure!r}; "
                f"available: {sorted(kernel.MEASURES)}"
            )
        if not isinstance(self.lrolesim_beta, (int, float)) or isinstance(
                self.lrolesim_beta, bool):
            raise LRoleSimConfigError("lrolesim_beta must be a real number")
        if not 0.0 <= float(self.lrolesim_beta) <= 1.0:
            raise LRoleSimConfigError(
                f"lrolesim_beta must lie in [0, 1], got {self.lrolesim_beta}")
        if not isinstance(self.iterations, int) or isinstance(self.iterations, bool):
            raise LRoleSimConfigError("iterations must be an int")
        if self.iterations < 1:
            raise LRoleSimConfigError(
                f"iterations must be >= 1, got {self.iterations}")

    @property
    def is_pilot_primary(self) -> bool:
        return (self.measure == PILOT_MEASURE
                and float(self.lrolesim_beta) == PILOT_LROLESIM_BETA
                and self.iterations == PILOT_ITERATIONS)

    @property
    def requires_entity_types(self) -> bool:
        return self.measure == ABLATION_MEASURE

    def as_record(self) -> dict:
        return {
            "measure": self.measure,
            "lrolesim_beta": float(self.lrolesim_beta),
            "iterations": self.iterations,
            "iteration_mode": "fixed",
            "is_pilot_primary": self.is_pilot_primary,
        }


def pilot_config() -> LRoleSimConfig:
    """The primary pilot configuration: L_ed, lrolesim_beta 0.2, exactly 3 iterations."""
    return LRoleSimConfig(measure=PILOT_MEASURE,
                          lrolesim_beta=PILOT_LROLESIM_BETA,
                          iterations=PILOT_ITERATIONS)


def ablation_config() -> LRoleSimConfig:
    """The L_edt ablation, same beta and iteration count as the primary run."""
    return LRoleSimConfig(measure=ABLATION_MEASURE,
                          lrolesim_beta=PILOT_LROLESIM_BETA,
                          iterations=PILOT_ITERATIONS)


# --- Running the kernel ----------------------------------------------------

@dataclass(frozen=True)
class LRoleSimRun:
    """A finished LRoleSim computation plus the provenance the pilot must record."""

    sim: object                      # kernel Sim instance
    config: LRoleSimConfig
    node_count: int
    iterations_run: int
    iteration_mode: str

    def score(self, u: int, v: int) -> float:
        return self.sim[u, v]

    def as_record(self) -> dict:
        record = self.config.as_record()
        record.update({
            "node_count": self.node_count,
            "iterations_run": self.iterations_run,
            "iteration_mode": self.iteration_mode,
        })
        return record


def _reject_beta_kwarg(kwargs: Mapping[str, object]) -> None:
    """Refuse a keyword named `beta`.

    OverlapScore's OverlapLoose weight is also called beta in the extractors.
    Silently accepting `beta=` here would let that weight be passed in as the
    LRoleSim decay factor with no error at all.
    """
    if "beta" in kwargs:
        raise LRoleSimConfigError(
            "'beta' is ambiguous in this project: OverlapScore's OverlapLoose "
            "weight is also called beta. Pass the LRoleSim decay factor as "
            "'lrolesim_beta' on LRoleSimConfig instead."
        )
    if kwargs:
        raise TypeError(f"unexpected keyword arguments: {sorted(kwargs)}")


def run_lrolesim_fixed(
    nodes: Sequence[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    config: Optional[LRoleSimConfig] = None,
    index_type: Optional[Mapping[int, int]] = None,
    verbose: bool = False,
    **kwargs: object,
) -> LRoleSimRun:
    """Run the kernel's FIXED-iteration path and verify the count actually run.

    `iterations_run` is counted by the kernel's per-iteration callback rather than
    copied from the configuration, so the recorded number is observed, not
    asserted.
    """
    _reject_beta_kwarg(kwargs)
    kernel = load_kernel()
    config = config or pilot_config()

    if config.requires_entity_types and not index_type:
        raise LRoleSimConfigError(
            f"measure {config.measure!r} needs an entity-type map; without one it "
            f"degenerates to {PILOT_MEASURE!r} and the ablation would be a "
            f"duplicate of the primary run"
        )

    node_list = list(nodes)
    observed: list[int] = []

    sim = kernel.lrolesim_fixed_iterations(
        float(config.lrolesim_beta), node_list, in_neighbor, out_neighbor,
        measure=config.measure, index_type=index_type,
        iterations=config.iterations,
        on_iteration=lambda k, _: observed.append(k),
        verbose=verbose,
    )

    if observed != list(range(1, config.iterations + 1)):
        raise LRoleSimConfigError(
            f"expected exactly {config.iterations} iterations, observed {observed}"
        )

    return LRoleSimRun(sim=sim, config=config, node_count=len(node_list),
                       iterations_run=len(observed), iteration_mode="fixed")


def run_lrolesim_until_convergence(
    nodes: Sequence[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    measure: str = PILOT_MEASURE,
    lrolesim_beta: float = PILOT_LROLESIM_BETA,
    index_type: Optional[Mapping[int, int]] = None,
    max_iter: int = CONVERGENCE_MAX_ITER,
    tol: float = CONVERGENCE_TOL,
    verbose: bool = False,
    **kwargs: object,
) -> LRoleSimRun:
    """Convergence ABLATION. Reachable only through this explicitly named function.

    The primary pilot must not use this path: its stopping point depends on `tol`
    and on graph structure, so it is not the published k = 3 configuration.
    """
    _reject_beta_kwarg(kwargs)
    kernel = load_kernel()
    node_list = list(nodes)

    sim = kernel.lrolesim_until_convergence(
        float(lrolesim_beta), node_list, in_neighbor, out_neighbor,
        measure=measure, index_type=index_type,
        max_iter=max_iter, tol=tol, verbose=verbose,
    )
    # The kernel's convergence path does not report its own iteration count; the
    # ablation records the bound rather than inventing an observed number.
    return LRoleSimRun(
        sim=sim,
        config=LRoleSimConfig(measure=measure, lrolesim_beta=lrolesim_beta,
                              iterations=max_iter),
        node_count=len(node_list),
        iterations_run=-1,
        iteration_mode="convergence",
    )


# --- Candidate ranking -----------------------------------------------------

@dataclass(frozen=True)
class CandidateScore:
    """One candidate's LRoleSim score against the Answer, with its rank."""

    rank: int
    candidate: int
    score: float
    at_beta_floor: bool

    def as_record(self) -> dict:
        return {
            "rank": self.rank,
            "candidate": self.candidate,
            "score": self.score,
            "at_beta_floor": self.at_beta_floor,
        }


@dataclass(frozen=True)
class RankingResult:
    """Ordered candidates plus the run provenance behind the ordering."""

    answer: int
    scores: tuple[CandidateScore, ...]
    run: LRoleSimRun

    @property
    def ordered_candidates(self) -> tuple[int, ...]:
        return tuple(s.candidate for s in self.scores)

    @property
    def beta_floor_count(self) -> int:
        """Candidates scoring exactly the beta floor.

        A direct measure of the floor-collapse risk: in the published HanamiSpots
        table every non-seed node sat at beta, so a run where most candidates are
        at the floor has not separated them at all.
        """
        return sum(1 for s in self.scores if s.at_beta_floor)

    def as_record(self) -> dict:
        return {
            "answer": self.answer,
            "run": self.run.as_record(),
            "beta_floor_count": self.beta_floor_count,
            "scores": [s.as_record() for s in self.scores],
        }


def rank_candidates(
    answer: int,
    candidates: Sequence[int],
    nodes: Sequence[int],
    in_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    out_neighbor: Mapping[int, Sequence[tuple[int, int]]],
    config: Optional[LRoleSimConfig] = None,
    index_type: Optional[Mapping[int, int]] = None,
    index_url: Optional[Mapping[int, str]] = None,
    verbose: bool = False,
    **kwargs: object,
) -> RankingResult:
    """Score `candidates` against `answer` on a PREBUILT graph, then order them.

    Tie-breaking is (-score, index_url[candidate]) when `index_url` is supplied,
    and (-score, candidate) otherwise. Ordering by node index would be a
    systematic bias, because indices follow the order of appearance in the source
    TTL file; the URI is neutral with respect to that order. Ties are frequent
    here, since every candidate that shares no equivalence class with the Answer
    lands exactly on the beta floor.
    """
    _reject_beta_kwarg(kwargs)
    config = config or pilot_config()

    run = run_lrolesim_fixed(
        nodes=nodes, in_neighbor=in_neighbor, out_neighbor=out_neighbor,
        config=config, index_type=index_type, verbose=verbose,
    )

    beta = float(config.lrolesim_beta)
    scored = [(run.score(answer, c), c) for c in candidates if c != answer]
    if index_url is not None:
        scored.sort(key=lambda t: (-t[0], index_url[t[1]]))
    else:
        scored.sort(key=lambda t: (-t[0], t[1]))

    scores = tuple(
        CandidateScore(rank=rank, candidate=candidate, score=score,
                       at_beta_floor=(score == beta))
        for rank, (score, candidate) in enumerate(scored, start=1)
    )
    return RankingResult(answer=answer, scores=scores, run=run)


def rank_m1_graph(
    m1_graph,
    config: Optional[LRoleSimConfig] = None,
    index_type: Optional[Mapping[int, int]] = None,
    index_url: Optional[Mapping[int, str]] = None,
    verbose: bool = False,
    **kwargs: object,
) -> RankingResult:
    """Rank the accepted candidates of a kg.graph_view.M1Graph.

    Refuses a graph the budget declared unusable, so an insufficient-candidate
    Answer cannot be ranked by accident.
    """
    _reject_beta_kwarg(kwargs)
    if not m1_graph.is_ready:
        raise LRoleSimConfigError(
            f"M1 graph is not rankable: status {m1_graph.status}"
        )
    graph = m1_graph.graph
    return rank_candidates(
        answer=m1_graph.answer,
        candidates=m1_graph.accepted_candidates,
        nodes=graph.nodes,
        in_neighbor=graph.in_neighbor,
        out_neighbor=graph.out_neighbor,
        config=config, index_type=index_type, index_url=index_url, verbose=verbose,
    )
