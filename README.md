# Finance Data Pipelines

Finance Data Pipelines is a small, correctness-first time-series ETL and SQLite loading
project. The current release provides a deterministic offline generator, strict validation,
an independent logical-state oracle, and three comparable SQLite strategies: **A: atomic
full replacement**, **B: incremental upsert**, and **C: append-only history with a current
projection**.

The repository includes a reproducible benchmark harness. Its results are cohort-specific and
are not a claim of production readiness, universal performance, scalability, or research novelty.

## Requirements

- Python 3.11 or newer
- SQLite supplied by Python
- No API key or network data source

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
fdp --help
```

For development:

```bash
python -m pip install -e '.[dev]'
```

`pyproject.toml` is the authoritative dependency definition. `requirements*.txt` are
compatibility wrappers only.

## Deterministic offline quickstart

Choose the output directory explicitly. All generated Parquet, JSON, SQLite, WAL, and SHM
files remain under that directory unless `--db-path` explicitly selects another location.

```bash
fdp run-all \
  --source synthetic \
  --seed 20270916 \
  --rows 1000 \
  --output-dir /tmp/fdp-run
```

The command performs two identical atomic full replacements so exact-rerun idempotency is
verified. It prints correctness fields as JSON and writes:

```text
/tmp/fdp-run/
  raw/prices_raw.parquet
  normalized/prices_normalized.parquet
  dataset_manifest.json
  correctness.json
  warehouse.db
```

The quickstart produces correctness evidence only. Comparative results are generated separately
by the controlled experiment harness described below.

## Controlled experiment

The benchmark harness is `scripts/benchmark.py`. It freezes SQLite WAL and
`synchronous=FULL`, runs stateful workload sequences from one fresh database per strategy and
repetition, rotates strategy order, validates every transition against the independent oracle,
and writes `environment.json`, `dataset_manifest.json`, `runs.jsonl`, `query_samples.jsonl`,
`summary.csv`, `correctness.csv`, and `recovery.csv`. Each accepted condition uses five fixed
queries with two warm-ups and 30 timed warm-cache samples. Analysis is regenerated from raw files
with `scripts/analyze_benchmark.py`. A small offline smoke is reproducible with:

```bash
make benchmark-small
```

The full experiment is intentionally separate from ordinary CI. It uses synthetic data only;
no financial or market conclusion is supported. Any report must identify the exact machine,
source hash, workload definitions, and limitations of its cohort.

## Optional configuration file

CLI values override a YAML file. Only `source`, `seed`, and `rows` are accepted:

```bash
fdp run-all --config config.yaml --output-dir /tmp/fdp-run
```

The package never searches the source checkout for configuration. It does not use `.env`, so
no `.env.example` is required.

## Logical model

The logical key is `(series_id, event_ts_utc)` and exact event identity is
`(series_id, event_ts_utc, revision)`. Timestamps are UTC Unix seconds aligned to one minute.
Prices and optional volume use fixed-point integers with scale `10^-6`.

Duplicate/update rules:

- an exact duplicate event is a safe no-op;
- different payloads for the same key and revision reject the entire batch, including across
  previously committed batches;
- the highest revision is current;
- a lower revision cannot regress the current state;
- an empty replacement is rejected by default.

The SQLite current-state table has a composite primary key, required checks, and an
`event_ts_utc` index. Loads use WAL, `synchronous=FULL`, foreign keys, a 5-second busy timeout,
and one explicit transaction. The staging table is validated against the independent oracle
before publication. A pre-commit failure rolls back to the prior committed table.

## Tests and local CI-equivalent checks

```bash
ruff check .
ruff format --check .
pytest -q

tmp_dir="$(mktemp -d)"
fdp run-all --source synthetic --seed 20270916 --rows 1000 \
  --output-dir "$tmp_dir/output"
```

Tests use temporary directories and make no live network calls.

## Docker

The image installs the package, runs as a non-root user, and defaults to the deterministic
offline 1,000-row flow:

```bash
docker build -t finance-data-pipelines:phase3d .
docker run --rm -v "$PWD/docker-output:/work/output" \
  finance-data-pipelines:phase3d
```

Docker support is part of the baseline, but a particular release should be called verified
only when build and run commands have actually executed in that release environment.

## Current maturity and limitations

- Three strategies with shared logical semantics; physical storage trade-offs differ.
- Single-process, single-writer SQLite baseline.
- Synthetic correctness fixture only; no market-behavior claims.
- No concurrency or distributed-system evaluation.
- Benchmark results are machine-specific and do not establish universal rankings.
- Deterministic exception injection and process-interruption tests cover transactional recovery;
  they are not a claim that every OS/power-loss mode has been tested.

## Project layout

```text
src/fdp/
  cli.py          installed Click interface
  pipeline.py     ordinary Python orchestration
  extract.py      deterministic synthetic generator
  transform.py    strict normalization
  validation.py   loader-side validation and revision resolution
  oracle.py       independent current-state oracle
  load.py         atomic SQLite full replacement
  encoding.py     canonical binary checksum encoding
  manifest.py     deterministic JSON manifests
  parquet_io.py   frozen Parquet schema
  strategies.py   alternative SQLite implementations with shared logical semantics
scripts/          benchmark.py and analyze_benchmark.py
tests/            isolated correctness and CLI tests
.github/workflows/ci.yml
```
