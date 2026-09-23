#!/usr/bin/env python3
"""Stateful, reproducible benchmark runner for the three SQLite strategies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import sqlite3
import statistics
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fdp.extract import GENERATOR_VERSION, generate_synthetic
from fdp.oracle import OracleError, build_oracle
from fdp.strategies import inspect_strategy, query_sql, strategy_loader
from fdp.validation import ValidationError

STRATEGIES = ("A_atomic_full_replace", "B_incremental_upsert", "C_append_history_materialized")
CONDITIONS = (
    "initial_load",
    "exact_rerun",
    "duplicate_heavy_25pct",
    "mixed_updates_50pct",
    "stale_revisions",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=list).encode()).hexdigest()


def environment() -> dict[str, object]:
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    return {
        "timestamp_utc": utc_now(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "cpu_count": os.cpu_count(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "dependency_freeze_sha256": hashlib.sha256(freeze.encode()).hexdigest(),
        "benchmark_version": "2.0.0",
        "durability": {
            "journal_mode": "WAL",
            "synchronous": "FULL",
            "foreign_keys": True,
            "busy_timeout_ms": 5000,
        },
    }


def workload_sequence(events):
    updates = tuple(
        replace(e, revision=2, close_micros=e.close_micros + 7) if i % 2 == 0 else e
        for i, e in enumerate(events)
    )
    stale = tuple(replace(e, revision=1) for e in events[: max(1, len(events) // 20)])
    duplicate = tuple(e for i, e in enumerate(events) if i % 4 == 0)
    conflict_base = events[0]
    conflict = (replace(conflict_base, close_micros=conflict_base.close_micros + 999),)
    return {
        "initial_load": events,
        "exact_rerun": events,
        "duplicate_heavy_25pct": events + duplicate,
        "mixed_updates_50pct": updates,
        "stale_revisions": stale,
        "conflicting_same_revision": conflict,
    }


def run_query_samples(database: Path, state, strategy, workload, size, repetition, run_id, out):
    sqls = query_sql(tuple(state))
    values = {}
    with sqlite3.connect(database) as connection:
        for name, (sql, params) in sqls.items():
            warmup_values = [connection.execute(sql, params).fetchone() for _ in range(2)]
            samples = []
            for sample in range(30):
                start = time.perf_counter_ns()
                value = connection.execute(sql, params).fetchone()
                samples.append((time.perf_counter_ns() - start) / 1_000_000)
                values[name] = value
                out.write(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "strategy": strategy,
                            "workload": workload,
                            "dataset_size": size,
                            "repetition": repetition,
                            "query": name,
                            "sample": sample + 1,
                            "latency_ms": samples[-1],
                            "warm_cache": True,
                            "result_signature": stable_hash(value),
                            "warmup_signatures": [stable_hash(v) for v in warmup_values],
                        }
                    )
                    + "\n"
                )
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scales", nargs="+", type=int, default=[100000])
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20270916)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    dbdir = root / "databases"
    dbdir.mkdir()
    env = environment()
    (root / "environment.json").write_text(json.dumps(env, indent=2, sort_keys=True) + "\n")
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": args.seed,
        "scales": args.scales,
        "repetitions": args.repetitions,
        "conditions": list(CONDITIONS) + ["conflicting_same_revision"],
        "stateful_sequence": [
            "empty_db",
            "initial_load",
            "exact_rerun",
            "duplicate_heavy_25pct",
            "mixed_updates_50pct",
            "stale_revisions",
            "conflicting_same_revision",
        ],
        "query_suite": [
            "Q1_point",
            "Q2_range",
            "Q3_period_aggregate",
            "Q4_latest",
            "Q5_filtered_return",
        ],
        "query_warmups": 2,
        "query_samples": 30,
        "durability": env["durability"],
    }
    (root / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    runs_path, queries_path = root / "runs.jsonl", root / "query_samples.jsonl"
    correctness_path, recovery_path = root / "correctness.csv", root / "recovery.csv"
    runs = []
    with (
        runs_path.open("w") as runs_file,
        queries_path.open("w") as query_file,
        correctness_path.open("w", newline="") as correctness_file,
        recovery_path.open("w", newline="") as recovery_file,
    ):
        cw = csv.DictWriter(
            correctness_file,
            fieldnames=[
                "strategy",
                "size",
                "repetition",
                "workload",
                "checksum_equal",
                "integrity_check",
                "missing",
                "extra",
                "wrong",
            ],
        )
        rw = csv.DictWriter(
            recovery_file,
            fieldnames=[
                "strategy",
                "size",
                "repetition",
                "failure",
                "prior_valid",
                "integrity_check",
                "rerun_valid",
            ],
        )
        cw.writeheader()
        rw.writeheader()
        for size in args.scales:
            base = generate_synthetic(rows=size, seed=args.seed)
            if size > 100_000:
                plans = [(0, (*CONDITIONS, "conflicting_same_revision"))]
                plans.extend(
                    (repetition, ("initial_load", "exact_rerun"))
                    for repetition in range(1, args.repetitions + 1)
                )
            else:
                plans = [
                    (repetition, (*CONDITIONS, "conflicting_same_revision"))
                    for repetition in range(1, args.repetitions + 1)
                ]
            for repetition, planned_workloads in plans:
                order = list(STRATEGIES)
                random.Random(args.seed + size + repetition).shuffle(order)
                for strategy in order:
                    loader = strategy_loader(strategy)
                    database = dbdir / f"{strategy}__{size}__r{repetition}.db"
                    accepted = tuple()
                    sequence = workload_sequence(base)
                    for workload in planned_workloads:
                        batch = sequence[workload]
                        expected_after_events = accepted + (
                            () if workload == "conflicting_same_revision" else batch
                        )
                        run_id = f"{strategy}-{size}-r{repetition}-{workload}"
                        start = time.perf_counter_ns()
                        error = None
                        try:
                            loader(batch, database_path=database)
                            if workload != "conflicting_same_revision":
                                accepted = expected_after_events
                        except (ValidationError, OracleError, ValueError) as exc:
                            error = f"{type(exc).__name__}: {exc}"
                        elapsed = (time.perf_counter_ns() - start) / 1_000_000
                        expected = build_oracle(accepted).state if accepted else ()
                        storage_bytes = database.stat().st_size if database.exists() else 0
                        check = (
                            inspect_strategy(database, strategy, expected)
                            if database.exists()
                            else {
                                "checksum_equal": False,
                                "integrity_check": "missing",
                                "missing_key_count": len(expected),
                                "extra_key_count": 0,
                                "stale_or_wrong_value_count": 0,
                            }
                        )
                        record = {
                            "run_id": run_id,
                            "timestamp_utc": utc_now(),
                            "strategy": strategy,
                            "workload": workload,
                            "dataset_size": size,
                            "input_rows": len(batch),
                            "repetition": repetition,
                            "execution_order": order,
                            "duration_ms": elapsed,
                            "throughput_rows_sec": len(batch) / (elapsed / 1000) if elapsed else 0,
                            "affected_logical_keys": len(expected),
                            "storage_bytes": storage_bytes,
                            "correctness": check,
                            "error": error,
                        }
                        runs.append(record)
                        runs_file.write(json.dumps(record, sort_keys=True) + "\n")
                        runs_file.flush()
                        cw.writerow(
                            {
                                "strategy": strategy,
                                "size": size,
                                "repetition": repetition,
                                "workload": workload,
                                "checksum_equal": check.get("checksum_equal", False),
                                "integrity_check": check.get("integrity_check"),
                                "missing": check.get("missing_key_count", -1),
                                "extra": check.get("extra_key_count", -1),
                                "wrong": check.get("stale_or_wrong_value_count", -1),
                            }
                        )
                        correctness_file.flush()
                        if workload != "conflicting_same_revision" and (
                            size <= 100_000 or repetition != 0
                        ):
                            run_query_samples(
                                database,
                                expected,
                                strategy,
                                workload,
                                size,
                                repetition,
                                run_id,
                                query_file,
                            )
                    # Recovery rerun on the committed final state.
                    try:
                        prior = inspect_strategy(database, strategy, accepted)
                        loader(sequence["exact_rerun"], database_path=database)
                        recovered = inspect_strategy(database, strategy, accepted)
                        rw.writerow(
                            {
                                "strategy": strategy,
                                "size": size,
                                "repetition": repetition,
                                "failure": "not_injected_in_benchmark",
                                "prior_valid": prior["checksum_equal"],
                                "integrity_check": prior["integrity_check"],
                                "rerun_valid": recovered["checksum_equal"],
                            }
                        )
                    except Exception as exc:
                        rw.writerow(
                            {
                                "strategy": strategy,
                                "size": size,
                                "repetition": repetition,
                                "failure": f"recovery_error:{type(exc).__name__}",
                                "prior_valid": False,
                                "integrity_check": "unknown",
                                "rerun_valid": False,
                            }
                        )
                    recovery_file.flush()
    with (root / "summary.csv").open("w", newline="") as summary_file:
        fields = [
            "strategy",
            "workload",
            "dataset_size",
            "n",
            "median_ms",
            "min_ms",
            "max_ms",
            "iqr_ms",
            "median_rows_sec",
            "all_correct",
        ]
        writer = csv.DictWriter(summary_file, fieldnames=fields)
        writer.writeheader()
        groups = {}
        for r in runs:
            if r["repetition"] == 0:
                continue
            groups.setdefault((r["strategy"], r["workload"], r["dataset_size"]), []).append(r)
        for key, group in sorted(groups.items()):
            ds = sorted(r["duration_ms"] for r in group)
            q1 = ds[(len(ds) - 1) // 4]
            q3 = ds[3 * (len(ds) - 1) // 4]
            writer.writerow(
                {
                    "strategy": key[0],
                    "workload": key[1],
                    "dataset_size": key[2],
                    "n": len(group),
                    "median_ms": statistics.median(ds),
                    "min_ms": min(ds),
                    "max_ms": max(ds),
                    "iqr_ms": q3 - q1,
                    "median_rows_sec": statistics.median(r["throughput_rows_sec"] for r in group),
                    "all_correct": all(
                        r["correctness"].get("checksum_equal")
                        and r["correctness"].get("integrity_check") == "ok"
                        for r in group
                    ),
                }
            )
    print(
        json.dumps(
            {
                "output_dir": str(root),
                "runs": len(runs),
                "query_samples": sum(1 for _ in queries_path.open()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
