"""
eval/trajectory_cases.py
------------------------
Week 8 — trajectory contracts, built **from the golden sets**, plus the
failure-mode taxonomy used by the metrics engine.

Why the cases are derived rather than written out
-------------------------------------------------
An earlier version of this file carried its own copy of each question. The text
matched the golden sets on the day it was written and nothing kept it that way:
editing ``goldensets/*.json`` would leave the trajectory eval quietly scoring
the old wording, while the outcome eval scored the new one — and the whole point
of the gap metric is that both verdicts describe *the same run*.

So the golden sets are the single source of truth. A case is now a golden entry
plus a **path contract**, and the contract is chosen from the entry's own
metadata (``is_negative_case``, ``api_versions``, ``tool_context``) rather than
hand-assigned. Adding a golden entry therefore gets a trajectory contract for
free, and no question text exists in two places.

Trajectory assertions remain **path sets**, not single rigid sequences. A query
like "what is the default value for `mode`?" is legitimately answerable by either

    reference_search -> finish
    reference_search -> chunk_retrieval -> finish

so both are in the contract. On top of the enumerated paths each contract
carries *structural* rules (``required_tools``, ``forbidden_tools``,
``ordering``) so a sound path nobody enumerated is still accepted — that is what
stops the suite being brittle.

Every field here is an assertion made in code; nothing is judged by an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from eval.golden_loader import GoldenEntry, get_all_entries, load_all_golden_sets

# Tool vocabulary the agent is allowed to emit. Anything outside this set is a
# hallucinated tool (failure mode M6).
KNOWN_TOOLS: frozenset[str] = frozenset({
    "reference_search",
    "chunk_retrieval",
    "migration_analyzer",
    "finish",
})

#: Fallback vocabulary for the ``version`` argument, used only when the live
#: collection cannot be read. The real check derives the accepted values from
#: the corpus — see ``tools/corpus_facts.py``.
VALID_VERSION_ARGS: frozenset[str] = frozenset({
    "v2", "v3", "2.x", "3.x", "2022-11-28", "2025-06-01",
})


# ─────────────────────────────────────────────────────────────────────────────
# Failure-mode taxonomy
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FailureMode:
    code: str
    name: str
    description: str


FAILURE_MODES: tuple[FailureMode, ...] = (
    FailureMode(
        "M1", "skipped_retrieval",
        "Produced a final answer without ever calling reference_search — the "
        "answer came from pretrained memory, not the corpus.",
    ),
    FailureMode(
        "M2", "wrong_tool_order",
        "Called chunk_retrieval or migration_analyzer before any evidence "
        "existed, i.e. analysed before it retrieved.",
    ),
    FailureMode(
        "M3", "invalid_arguments",
        "A tool call carried arguments that fail validation: empty/degenerate "
        "query, a chunk_id absent from the corpus, or an invented version string.",
    ),
    FailureMode(
        "M4", "redundant_steps",
        "Took strictly more steps than the optimal path needs — repeated or "
        "looping tool calls.",
    ),
    FailureMode(
        "M5", "missing_analysis",
        "A comparison/migration query finished without running "
        "migration_analyzer over the collected evidence.",
    ),
    FailureMode(
        "M6", "unsupported_tool",
        "Emitted an action naming a tool that does not exist.",
    ),
    FailureMode(
        "M7", "budget_exhausted",
        "The circuit breaker tripped (iterations, tokens, cost or time) before "
        "the agent finished on its own.",
    ),
)

FAILURE_MODE_BY_CODE: dict[str, FailureMode] = {m.code: m for m in FAILURE_MODES}
ALL_MODE_CODES: tuple[str, ...] = tuple(m.code for m in FAILURE_MODES)


# ─────────────────────────────────────────────────────────────────────────────
# Path contracts, one per question kind
# ─────────────────────────────────────────────────────────────────────────────

_S = "reference_search"
_C = "chunk_retrieval"
_M = "migration_analyzer"
_F = "finish"


@dataclass(frozen=True)
class PathContract:
    """What a legitimate trajectory looks like for one *kind* of question."""

    allowed_paths: tuple[tuple[str, ...], ...]
    required_tools: frozenset[str]
    ordering: tuple[tuple[str, str], ...]
    optimal_steps: int
    max_reasonable_steps: int
    forbidden_tools: frozenset[str] = frozenset()


#: Single-fact lookup. Retrieve, optionally pull the chunk for detail, answer.
LOOKUP_CONTRACT = PathContract(
    allowed_paths=((_S, _F), (_S, _C, _F), (_S, _C, _M, _F), (_S, _S, _F)),
    required_tools=frozenset({_S}),
    ordering=((_S, _F),),
    optimal_steps=2,
    max_reasonable_steps=4,
)

#: Version migration / comparison. A migration answer must be *analysed*, not
#: merely retrieved, so the analyzer is required rather than optional.
COMPARISON_CONTRACT = PathContract(
    allowed_paths=(
        (_S, _M, _F),
        (_S, _C, _M, _F),
        (_S, _S, _M, _F),
        (_S, _C, _C, _M, _F),
        (_S, _S, _C, _M, _F),
    ),
    required_tools=frozenset({_S, _M}),
    ordering=((_S, _M), (_M, _F)),
    optimal_steps=3,
    max_reasonable_steps=5,
)

#: Unanswerable. A refusal is only trustworthy if the agent actually looked
#: first, so retrieval is still required; one or two further attempts are fair.
UNANSWERABLE_CONTRACT = PathContract(
    allowed_paths=((_S, _F), (_S, _S, _F), (_S, _S, _S, _F)),
    required_tools=frozenset({_S}),
    ordering=((_S, _F),),
    optimal_steps=2,
    max_reasonable_steps=4,
)

#: Unanswerable, but phrased as a migration question. Reaching for the analyzer
#: before refusing is reasonable here, so the analyzer paths are allowed without
#: being required.
UNANSWERABLE_COMPARISON_CONTRACT = PathContract(
    allowed_paths=(
        (_S, _F), (_S, _S, _F), (_S, _M, _F), (_S, _C, _M, _F), (_S, _S, _S, _F),
    ),
    required_tools=frozenset({_S}),
    ordering=((_S, _F),),
    optimal_steps=2,
    max_reasonable_steps=5,
)


# ─────────────────────────────────────────────────────────────────────────────
# Trajectory case
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrajectoryCase:
    """One golden-set query plus the trajectory contract it must satisfy."""

    case_id: str                  # stable, derived from the scenario: "E01"
    scenario_key: str             # golden-set key, e.g. "easy:01"
    question: str                 # verbatim from the golden entry
    kind: str                     # "lookup" | "comparison" | "unanswerable"

    allowed_paths: tuple[tuple[str, ...], ...]
    required_tools: frozenset[str] = field(default_factory=frozenset)
    forbidden_tools: frozenset[str] = field(default_factory=frozenset)
    ordering: tuple[tuple[str, str], ...] = ()
    optimal_steps: int = 2
    max_reasonable_steps: int = 4
    expected_versions: frozenset[str] = field(default_factory=frozenset)

    def shortest_allowed(self) -> int:
        return min((len(p) for p in self.allowed_paths), default=self.optimal_steps)


# ─────────────────────────────────────────────────────────────────────────────
# Classification — derived from golden-set metadata, never hand-assigned
# ─────────────────────────────────────────────────────────────────────────────

def _looks_like_comparison(entry: GoldenEntry) -> bool:
    """Does this entry ask how something changed between two versions?

    Checked against the entry's own metadata first (``api_versions`` carries
    more than one release; ``tool_context`` names a migration or comparison),
    falling back to the question wording.
    """
    meta = entry.metadata or {}

    versions = meta.get("api_versions")
    if isinstance(versions, (list, tuple)) and len(versions) > 1:
        return True

    context = str(meta.get("tool_context", "")).lower()
    if any(word in context for word in ("migration", "comparison")):
        return True

    question = entry.question.lower()
    return any(
        phrase in question
        for phrase in ("compare", "change between", "changed between", "differ")
    )


def classify_entry(entry: GoldenEntry) -> str:
    """Map a golden entry onto one of the three question kinds."""
    if entry.is_negative_case:
        return "unanswerable"
    return "comparison" if _looks_like_comparison(entry) else "lookup"


def contract_for(entry: GoldenEntry, kind: str) -> PathContract:
    """Pick the path contract for an entry.

    Unanswerable entries split two ways: a plain one should just search and
    refuse, while one phrased as a migration may reasonably reach for the
    analyzer before refusing.
    """
    if kind == "comparison":
        return COMPARISON_CONTRACT
    if kind == "unanswerable":
        return (
            UNANSWERABLE_COMPARISON_CONTRACT
            if _looks_like_comparison(entry)
            else UNANSWERABLE_CONTRACT
        )
    return LOOKUP_CONTRACT


def _expected_versions(entry: GoldenEntry) -> frozenset[str]:
    """Version strings the question is *about*, for reporting context.

    Argument validity is judged against the corpus's real vocabulary, not this —
    see ``tools/corpus_facts.accepted_version_values``.
    """
    meta = entry.metadata or {}
    found: set[str] = set()
    versions = meta.get("api_versions")
    if isinstance(versions, (list, tuple)):
        found.update(str(v) for v in versions)
    for key in ("api_version", "tool_version", "sdk_version"):
        if meta.get(key):
            found.add(str(meta[key]))
    return frozenset(found)


def scenario_key(entry: GoldenEntry) -> str:
    """``"easy:01"`` — the key the Week 7 benchmark already selects scenarios by."""
    return f"{entry.level.lower()}:{entry.id}"


def case_id_for(entry: GoldenEntry) -> str:
    """``"E01"`` — stable across selections, unlike a positional T-number."""
    return f"{entry.level[:1].upper()}{entry.id}"


def build_case(entry: GoldenEntry) -> TrajectoryCase:
    """Turn one golden entry into a trajectory case."""
    kind = classify_entry(entry)
    contract = contract_for(entry, kind)
    return TrajectoryCase(
        case_id=case_id_for(entry),
        scenario_key=scenario_key(entry),
        question=entry.question,          # the golden set is the only source
        kind=kind,
        allowed_paths=contract.allowed_paths,
        required_tools=contract.required_tools,
        forbidden_tools=contract.forbidden_tools,
        ordering=contract.ordering,
        optimal_steps=contract.optimal_steps,
        max_reasonable_steps=contract.max_reasonable_steps,
        expected_versions=_expected_versions(entry),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Loading
# ─────────────────────────────────────────────────────────────────────────────

#: The default 10 queries — the same selection the Week 7 benchmark races, so
#: the outcome and trajectory numbers describe the same scenarios.
DEFAULT_SCENARIO_KEYS: tuple[str, ...] = (
    "easy:01", "easy:04", "easy:13",
    "medium:02", "medium:05", "medium:14",
    "hard:01", "hard:04", "hard:09", "hard:13",
)

_CASE_CACHE: dict[tuple[str, tuple[str, ...]], tuple[TrajectoryCase, ...]] = {}


def golden_index(golden_dir: Path) -> dict[str, GoldenEntry]:
    """Every golden entry, keyed by ``"level:id"``."""
    sets = load_all_golden_sets(golden_dir)
    return {scenario_key(e): e for e in get_all_entries(sets)}


def load_trajectory_cases(
    golden_dir: Path,
    scenario_keys: tuple[str, ...] | list[str] | None = None,
) -> tuple[TrajectoryCase, ...]:
    """Build trajectory cases from the golden sets.

    ``scenario_keys`` selects which entries to run; ``None`` uses the standard
    ten. Pass a wider selection to score more of the golden set — every entry
    gets a contract automatically. Results are cached per (dir, selection)
    because the golden sets are static for the life of a run.
    """
    keys = tuple(scenario_keys) if scenario_keys else DEFAULT_SCENARIO_KEYS
    cache_key = (str(golden_dir), keys)
    if cache_key in _CASE_CACHE:
        return _CASE_CACHE[cache_key]

    index = golden_index(golden_dir)
    cases: list[TrajectoryCase] = []
    for key in keys:
        entry = index.get(key.strip().lower())
        if entry is None:
            raise ValueError(
                f"Scenario key {key!r} matches no golden entry. "
                f"Known keys: {', '.join(sorted(index))}"
            )
        cases.append(build_case(entry))

    result = tuple(cases)
    _CASE_CACHE[cache_key] = result
    return result


def default_golden_dir() -> Path:
    from benchmark.config import PROJECT_ROOT

    return PROJECT_ROOT / "goldensets"


def case_by_id(case_id: str, cases: tuple[TrajectoryCase, ...] | None = None) -> TrajectoryCase:
    for case in cases or load_trajectory_cases(default_golden_dir()):
        if case.case_id == case_id:
            return case
    raise KeyError(f"Unknown trajectory case: {case_id}")


def case_by_scenario(key: str, cases: tuple[TrajectoryCase, ...] | None = None) -> TrajectoryCase:
    for case in cases or load_trajectory_cases(default_golden_dir()):
        if case.scenario_key == key:
            return case
    raise KeyError(f"Unknown scenario key: {key}")
