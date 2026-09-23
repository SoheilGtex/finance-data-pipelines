#!/usr/bin/env python3
"""Regenerate Phase 3E analysis artifacts from raw JSONL/CSV files only."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def chart(
    path: Path,
    title: str,
    labels: list[str],
    values: dict[tuple[str, str], float],
    series: list[str],
) -> None:
    width, height, left, top, plot = 1200, 650, 110, 85, 930
    maximum = max(values.values() or [1]) * 1.15
    colors = ["#4c78a8", "#f58518", "#54a24b"]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="40" text-anchor="middle" font-family="sans-serif" font-size="24" font-weight="bold">{title}</text>',  # noqa: E501
    ]
    for i in range(6):
        y = top + plot * (1 - i / 5)
        value = maximum * i / 5
        svg += [
            f'<line x1="{left}" y1="{y}" x2="{left + plot}" y2="{y}" stroke="#ddd"/>',
            f'<text x="{left - 8}" y="{y + 4}" text-anchor="end" font-family="sans-serif" font-size="12">{value:.0f}</text>',  # noqa: E501
        ]
    group = plot / max(1, len(labels))
    bar = group / (len(series) + 1)
    for li, label in enumerate(labels):
        gx = left + li * group
        svg.append(
            f'<text x="{gx + group / 2}" y="{top + plot + 30}" text-anchor="middle" font-family="sans-serif" font-size="12">{label}</text>'  # noqa: E501
        )
        for si, strategy in enumerate(series):
            value = values.get((label, strategy), 0)
            bh = value / maximum * plot
            svg.append(
                f'<rect x="{gx + (si + 0.5) * bar}" y="{top + plot - bh}" width="{bar * 0.78}" height="{bh}" fill="{colors[si % len(colors)]}"><title>{label} {strategy}: {value}</title></rect>'  # noqa: E501
            )
    for si, strategy in enumerate(series):
        x = left + plot - 360 + si * 120
        svg += [
            f'<rect x="{x}" y="{height - 55}" width="14" height="14" fill="{colors[si % len(colors)]}"/>',  # noqa: E501
            f'<text x="{x + 20}" y="{height - 43}" font-family="sans-serif" font-size="11">{strategy[:14]}</text>',  # noqa: E501
        ]
    svg.append("</svg>")
    path.write_text("\n".join(svg))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs = [
        json.loads(line) for line in (args.raw_dir / "runs.jsonl").read_text().splitlines() if line
    ]
    queries = [
        json.loads(line)
        for line in (args.raw_dir / "query_samples.jsonl").read_text().splitlines()
        if line
    ]
    groups = defaultdict(list)
    performance_groups = defaultdict(list)
    for row in runs:
        key = (row["strategy"], row["workload"], row["dataset_size"])
        groups[key].append(row)
        if row.get("repetition") != 0:
            performance_groups[key].append(row)
    with (args.output_dir / "summary.csv").open("w", newline="") as handle:
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
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (strategy, workload, size), rows in sorted(performance_groups.items()):
            durations = sorted(float(row["duration_ms"]) for row in rows)
            q1 = durations[(len(durations) - 1) // 4]
            q3 = durations[3 * (len(durations) - 1) // 4]
            writer.writerow(
                {
                    "strategy": strategy,
                    "workload": workload,
                    "dataset_size": size,
                    "n": len(rows),
                    "median_ms": statistics.median(durations),
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                    "iqr_ms": q3 - q1,
                    "median_rows_sec": statistics.median(
                        row["throughput_rows_sec"] for row in rows
                    ),
                    "all_correct": all(
                        row["correctness"]["checksum_equal"]
                        and row["correctness"]["integrity_check"] == "ok"
                        for row in rows
                    ),
                }
            )
    with (args.output_dir / "correctness.csv").open("w", newline="") as handle:
        fields = [
            "strategy",
            "workload",
            "dataset_size",
            "runs",
            "all_checksums_equal",
            "all_integrity_ok",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key, rows in sorted(groups.items()):
            writer.writerow(
                {
                    "strategy": key[0],
                    "workload": key[1],
                    "dataset_size": key[2],
                    "runs": len(rows),
                    "all_checksums_equal": all(
                        row["correctness"]["checksum_equal"] for row in rows
                    ),
                    "all_integrity_ok": all(
                        row["correctness"]["integrity_check"] == "ok" for row in rows
                    ),
                }
            )
    qgroups = defaultdict(list)
    for row in queries:
        qgroups[(row["strategy"], row["workload"], row["dataset_size"], row["query"])].append(
            float(row["latency_ms"])
        )
    with (args.output_dir / "query_summary.csv").open("w", newline="") as handle:
        fields = ["strategy", "workload", "dataset_size", "query", "n", "median_ms", "p95_ms"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key, values in sorted(qgroups.items()):
            values.sort()
            writer.writerow(
                {
                    "strategy": key[0],
                    "workload": key[1],
                    "dataset_size": key[2],
                    "query": key[3],
                    "n": len(values),
                    "median_ms": statistics.median(values),
                    "p95_ms": values[max(0, math.ceil(0.95 * len(values)) - 1)],
                }
            )
    labels = sorted({workload for _, workload, _ in performance_groups})
    strategies = sorted({strategy for strategy, _, _ in performance_groups})
    ingestion = {
        (label, strategy): statistics.median(float(row["duration_ms"]) for row in rows)
        for (strategy, label, _), rows in performance_groups.items()
    }
    storage = {
        (label, strategy): statistics.median(float(row.get("storage_bytes", 0)) for row in rows)
        for (strategy, label, _), rows in performance_groups.items()
    }
    chart(
        args.output_dir / "ingestion_wall_time.svg",
        "Median ingestion wall time (ms)",
        labels,
        ingestion,
        strategies,
    )
    chart(
        args.output_dir / "storage_footprint.svg",
        "Median storage footprint (bytes)",
        labels,
        storage,
        strategies,
    )
    query_labels = sorted({row["query"] for row in queries})
    qvalues = {
        (label, strategy): statistics.median(values)
        for (strategy, _, _, label), values in qgroups.items()
    }
    chart(
        args.output_dir / "query_latency.svg",
        "Median warm-cache query latency (ms)",
        query_labels,
        qvalues,
        strategies,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
