#!/usr/bin/env python3
"""Write an evidence-based findings report from the cleaned dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/clean.csv", type=Path)
    parser.add_argument("--output", default="docs/findings.md", type=Path)
    return parser.parse_args()


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return df
    for column in [
        "requested_rate",
        "achieved_throughput",
        "throughput_ratio",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "total_requests",
        "error_count",
        "timeout_count",
        "cpu_percent_avg",
        "memory_bytes_avg",
    ]:
        if column in df:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    if "valid" in df:
        df["valid"] = df["valid"].astype(str).str.lower().isin(["true", "1"])
    return df


def fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "not measured"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def grouped_summary(valid: pd.DataFrame) -> pd.DataFrame:
    summary = valid.groupby("requested_rate", as_index=False).agg(
        runs=("run_id", "count"),
        p50_ms=("p50_latency_ms", "median"),
        p95_ms=("p95_latency_ms", "median"),
        p99_ms=("p99_latency_ms", "median"),
        achieved_rps=("achieved_throughput", "median"),
        throughput_ratio=("throughput_ratio", "median"),
        cpu_percent=("cpu_percent_avg", "mean"),
        memory_mib=("memory_bytes_avg", lambda values: values.mean() / 1024 / 1024),
        error_rate=("error_count", lambda values: values.sum() / valid.loc[values.index, "total_requests"].sum()),
    )
    return summary.sort_values("requested_rate")


def find_degradation(summary: pd.DataFrame) -> str:
    if len(summary) < 2:
        return "Not enough tested load levels to identify a degradation point."

    baseline = summary.iloc[0]["p95_ms"]
    previous = summary.iloc[0]

    for _, current in summary.iloc[1:].iterrows():
        previous_p95 = previous["p95_ms"]
        current_p95 = current["p95_ms"]
        if pd.isna(previous_p95) or pd.isna(current_p95) or pd.isna(baseline):
            previous = current
            continue

        relative_jump = current_p95 / previous_p95 if previous_p95 > 0 else float("inf")
        baseline_ratio = current_p95 / baseline if baseline > 0 else float("inf")
        absolute_jump = current_p95 - previous_p95

        if relative_jump >= 1.5 and baseline_ratio >= 2.0 and absolute_jump >= max(1.0, baseline * 0.2):
            return (
                "The first sharp p95 latency increase by this simple heuristic appears between "
                f"{fmt(previous['requested_rate'], 0)} and {fmt(current['requested_rate'], 0)} requests/second. "
                f"Median p95 rose from {fmt(previous_p95)} ms to {fmt(current_p95)} ms."
            )
        previous = current

    return "No sharp latency degradation point was detected by the current heuristic."


def correlation_sentence(valid: pd.DataFrame, x: str, y: str, label: str) -> str:
    subset = valid[[x, y]].dropna()
    if len(subset) < 3 or subset[x].nunique() < 2 or subset[y].nunique() < 2:
        return f"{label}: not enough variation to summarize."
    corr = subset[x].corr(subset[y])
    return f"{label}: Pearson correlation with p95 latency was {fmt(corr, 2)} across valid runs."


def repeatability_notes(valid: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    grouped = valid.groupby("requested_rate")
    for rate, group in grouped:
        if len(group) < 2:
            notes.append(f"- {fmt(rate, 0)} requests/second: one valid run, so repeatability was not measured.")
            continue
        mean = group["p95_latency_ms"].mean()
        std = group["p95_latency_ms"].std()
        cv = std / mean if mean else float("nan")
        notes.append(
            f"- {fmt(rate, 0)} requests/second: {len(group)} valid runs, p95 mean {fmt(mean)} ms, "
            f"standard deviation {fmt(std)} ms, coefficient of variation {fmt(cv, 3)}."
        )
    return notes


def summary_table(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "Not run."

    lines = [
        "| Requested rps | Runs | p50 ms | p95 ms | p99 ms | Achieved rps | Throughput ratio | CPU % | Memory MiB | Error rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in summary.iterrows():
        lines.append(
            "| "
            f"{fmt(row['requested_rate'], 0)} | {fmt(int(row['runs']))} | {fmt(row['p50_ms'])} | "
            f"{fmt(row['p95_ms'])} | {fmt(row['p99_ms'])} | {fmt(row['achieved_rps'])} | "
            f"{fmt(row['throughput_ratio'], 3)} | {fmt(row['cpu_percent'])} | {fmt(row['memory_mib'])} | "
            f"{fmt(row['error_rate'], 4)} |"
        )
    return "\n".join(lines)


def write_not_run(output: Path, all_rows: pd.DataFrame) -> None:
    invalid_count = len(all_rows) if not all_rows.empty else 0
    text = f"""# Findings

## Status

Not run. No valid experiment rows are available in `data/clean.csv`.

Invalid or incomplete rows present: {invalid_count}.

## Evidence

No benchmark evidence has been collected yet, so the project cannot support claims about latency, throughput, CPU usage, memory usage, or bottlenecks.

## Optional Configuration Comparison

Not run. No second server configuration was provided.

## Next Experiment

Run `./loadtest/run_experiments.sh smoke`, then run:

```bash
python3 analysis/parse_results.py
python3 analysis/explore_data.py
python3 analysis/performance_analysis.py
```

Only run `./loadtest/run_experiments.sh full` after the smoke run starts the server, receives successful responses, records raw output, and parses into at least one valid row.
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def write_report(output: Path, all_rows: pd.DataFrame, valid: pd.DataFrame) -> None:
    summary = grouped_summary(valid)
    invalid = all_rows[~all_rows["valid"]] if "valid" in all_rows else pd.DataFrame()
    degradation = find_degradation(summary)

    resource_notes = [
        correlation_sentence(valid, "cpu_percent_avg", "p95_latency_ms", "CPU association"),
        correlation_sentence(valid, "memory_bytes_avg", "p95_latency_ms", "Memory association"),
        correlation_sentence(valid, "throughput_ratio", "p95_latency_ms", "Throughput-ratio association"),
    ]

    text = f"""# Findings

## Status

Analyzed {len(valid)} valid runs from `data/clean.csv`. Failed or incomplete runs retained in the clean dataset: {len(invalid)}.

## Workload Summary

{summary_table(summary)}

## Latency Degradation

{degradation}

This is a descriptive threshold, not a proof of a bottleneck. It uses the first adjacent load step where median p95 latency rises by at least 50%, is at least twice the lowest-load median p95, and increases by a meaningful absolute amount.

## Throughput

At the highest tested load, median achieved throughput was {fmt(summary.iloc[-1]['achieved_rps'])} requests/second against {fmt(summary.iloc[-1]['requested_rate'], 0)} requested requests/second. Median throughput ratio was {fmt(summary.iloc[-1]['throughput_ratio'], 3)}.

## Resource Associations

{chr(10).join(f"- {note}" for note in resource_notes)}

These associations do not establish causality. To test causality, run targeted experiments that change one factor at a time, such as worker count, static file size, connection count, or CPU limits.

## Repeatability

{chr(10).join(repeatability_notes(valid))}

## Figures

- [Latency vs load](../results/figures/latency_vs_load.png)
- [Requested vs achieved throughput](../results/figures/throughput_requested_vs_achieved.png)
- [Resource usage vs load](../results/figures/resource_usage_vs_load.png)
- [Error rate vs load](../results/figures/error_rate_vs_load.png)
- [Latency variation across repeats](../results/figures/latency_variation_repeats.png)

## Optional Configuration Comparison

Not run. No second server configuration was provided.

## Limitations

- Results apply only to the tested host, Docker setup, endpoint, payload, connection count, worker count, and rate range.
- CPU and memory samples are coarse Docker-level observations and may miss short spikes.
- wrk2 is an open-loop generator, so it is useful for overload behavior, but the client machine can become a bottleneck too.
- Correlation between high latency and resource usage is evidence of association only.

## Recommended Next Experiment

If degradation appears, rerun a narrower load sweep around that range with more repeats. If degradation does not appear, extend the load range gradually while watching for client-side saturation and errors.
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    all_rows = load_data(args.input)

    if all_rows.empty or "valid" not in all_rows:
        write_not_run(args.output, all_rows)
        print(f"Wrote Not run report to {args.output}")
        return

    valid = all_rows[all_rows["valid"]].copy()
    if valid.empty:
        write_not_run(args.output, all_rows)
        print(f"Wrote Not run report to {args.output}")
        return

    write_report(args.output, all_rows, valid)
    print(f"Wrote findings to {args.output}")


if __name__ == "__main__":
    main()

