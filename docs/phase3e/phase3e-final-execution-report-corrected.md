# Phase 3E Final Execution Report

## Final status

- Final verdict: **COMPLETE**
- Repository status: **MERGED TO `main`**
- Baseline commit: `c4313f6ad3a28b5901255259c2b39b67ee836413`
- Phase 3E implementation commit: `bcfe625`
- Merge commit on `main`: `69313bd`
- Feature branch: `benchmark/phase3e-experiment`
- Pull request: `#2 — Finalize Phase 3E benchmark study`

## Gates

| Gate | Result |
|---|---|
| Clean working tree | PASS |
| Clean install | PASS |
| Ruff lint | PASS |
| Ruff format | PASS |
| Tests | PASS — 57 tests |
| Cross-batch conflict semantics | PASS — A/B/C |
| Stateful rerun/update/stale semantics | PASS |
| Oracle equivalence | PASS — 100k and 1m |
| Process interruption recovery | PASS |
| 100k cohort | PASS — 90 runs, 11,250 query samples |
| 1m cohort | PASS — 48 runs, 4,500 query samples |
| Q1–Q5 equality | PASS |
| Analysis regeneration | PASS |
| GitHub Actions push CI | PASS — Python 3.11 and 3.12 |
| GitHub Actions PR CI | PASS — Python 3.11 and 3.12 |
| Pull request merge | PASS — PR #2 |

The 1m resource-bounded design uses one complete stateful correctness sequence per strategy and five measured `initial_load` / `exact_rerun` repetitions per strategy. The correctness-only repetition is excluded from performance aggregation by `scripts/analyze_benchmark.py`.

## Corrected 1m analysis

The original generated report accidentally included the correctness-only `repetition == 0` run in the regenerated performance summary. The merged implementation fixes this by excluding repetition 0 from performance aggregation while preserving it for correctness evidence.

Corrected median initial-load wall times:

| Strategy | Median (ms) |
|---|---:|
| A — atomic full replacement | 39,050.38 |
| B — incremental upsert | 21,173.67 |
| C — append history + materialized current state | 22,539.42 |

For this recorded 1m cohort, Strategy B's median initial-load wall time was **45.8% lower** than Strategy A's. Equivalently, Strategy A took about **1.84×** as long as Strategy B.

The 100k result is unchanged: Strategy B's median initial-load wall time was **49.4% lower** than Strategy A's.

## Canonical source

The canonical project state is the merged Git repository at:

- Phase 3E implementation commit: `bcfe625`
- Main merge commit: `69313bd`

Earlier Manus-generated ZIP/diff/format-patch artifacts predate the local analysis correction and should not be treated as the canonical final source unless regenerated from the merged repository.

## CI evidence

Remote GitHub Actions was executed after the corrected Phase 3E implementation was pushed:

- Push workflow run: `35874939037` — PASS
- Pull-request workflow run: `35875147446` — PASS
- Python 3.11 correctness job — PASS
- Python 3.12 correctness job — PASS

## Main remaining limitation

Evidence is single-machine, synthetic, single-process, and SQLite-specific. No universal performance claim, distributed scalability claim, publication claim, or production-readiness claim is made.
