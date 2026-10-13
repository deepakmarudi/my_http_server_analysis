#!/usr/bin/env python3
"""Parse raw wrk2 output and Docker resource samples into one clean CSV."""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Any

OUTPUT_COLUMNS = [
    "run_id",
    "valid",
    "failure_reason",
    "mode",
    "workload_name",
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
    "cpu_percent_max",
    "memory_bytes_avg",
    "memory_bytes_max",
    "duration_seconds",
    "wrk_threads",
    "wrk_connections",
    "server_workers",
    "target_url",
    "started_at",
    "ended_at",
    "repeat",
    "raw_dir",
    "server_commit",
]

MICRO_UNITS = "\u00b5\xb5\u03bc"
LATENCY_RE = re.compile(
    r"^\s*(?P<pct>\d+(?:\.\d+)?)%\s+(?P<value>\d+(?:\.\d+)?)(?P<unit>[A-Za-z"
    + MICRO_UNITS
    + r"]+)"
)
DETAILED_LATENCY_RE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s+(?P<pct>[01](?:\.\d+)?)\s+(?P<count>\d+)\s+"
)
REQUESTS_RE = re.compile(r"(?P<requests>\d+)\s+requests\s+in\s+(?P<duration>\d+(?:\.\d+)?)(?P<unit>[A-Za-z]+)")
THROUGHPUT_RE = re.compile(r"Requests/sec:\s+(?P<throughput>\d+(?:\.\d+)?)")
SOCKET_ERRORS_RE = re.compile(
    r"Socket errors:\s+connect\s+(?P<connect>\d+),\s+read\s+(?P<read>\d+),\s+write\s+(?P<write>\d+),\s+timeout\s+(?P<timeout>\d+)"
)
NON_2XX_RE = re.compile(r"Non-2xx or 3xx responses:\s+(?P<count>\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw", type=Path)
    parser.add_argument("--output", default="data/clean.csv", type=Path)
    return parser.parse_args()


def read_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if not path.exists():
        return metadata

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def latency_to_ms(value: str, unit: str) -> float:
    normalized = unit.lower().replace("\u00b5", "u").replace("\xb5", "u").replace("\u03bc", "u")
    number = float(value)
    if normalized in {"us", "usec"}:
        return number / 1000.0
    if normalized in {"ms", "msec"}:
        return number
    if normalized in {"s", "sec"}:
        return number * 1000.0
    if normalized in {"m", "min"}:
        return number * 60_000.0
    raise ValueError(f"Unsupported latency unit: {unit}")


def duration_to_seconds(value: str, unit: str) -> float:
    normalized = unit.lower()
    number = float(value)
    if normalized in {"us", "usec"}:
        return number / 1_000_000.0
    if normalized in {"ms", "msec"}:
        return number / 1000.0
    if normalized in {"s", "sec"}:
        return number
    if normalized in {"m", "min"}:
        return number * 60.0
    if normalized in {"h", "hr"}:
        return number * 3600.0
    raise ValueError(f"Unsupported duration unit: {unit}")


def bytes_to_float(value: str) -> float | None:
    text = value.strip()
    match = re.match(r"^(?P<number>\d+(?:\.\d+)?)(?P<unit>[A-Za-z]+)$", text)
    if not match:
        return None

    number = float(match.group("number"))
    unit = match.group("unit").lower()
    scale = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
    }.get(unit)
    if scale is None:
        return None
    return number * scale


def parse_wrk_output(path: Path) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "p50_latency_ms": None,
        "p95_latency_ms": None,
        "p99_latency_ms": None,
        "achieved_throughput": None,
        "total_requests": None,
        "observed_duration_seconds": None,
        "error_count": 0,
        "timeout_count": 0,
    }

    if not path.exists():
        metrics["parse_error"] = "missing wrk.txt"
        return metrics

    latency_percentiles: dict[float, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        latency_match = LATENCY_RE.match(line)
        if latency_match:
            try:
                percentile = float(latency_match.group("pct"))
                latency_percentiles[percentile] = latency_to_ms(
                    latency_match.group("value"), latency_match.group("unit")
                )
            except ValueError as exc:
                metrics["parse_error"] = str(exc)
            continue

        detailed_match = DETAILED_LATENCY_RE.match(line)
        if detailed_match:
            percentile = float(detailed_match.group("pct")) * 100.0
            latency_percentiles[percentile] = float(detailed_match.group("value"))
            continue

        request_match = REQUESTS_RE.search(line)
        if request_match:
            metrics["total_requests"] = int(request_match.group("requests"))
            metrics["observed_duration_seconds"] = duration_to_seconds(
                request_match.group("duration"), request_match.group("unit")
            )
            continue

        throughput_match = THROUGHPUT_RE.search(line)
        if throughput_match:
            metrics["achieved_throughput"] = float(throughput_match.group("throughput"))
            continue

        socket_errors_match = SOCKET_ERRORS_RE.search(line)
        if socket_errors_match:
            connect = int(socket_errors_match.group("connect"))
            read = int(socket_errors_match.group("read"))
            write = int(socket_errors_match.group("write"))
            timeout = int(socket_errors_match.group("timeout"))
            metrics["timeout_count"] = timeout
            metrics["error_count"] += connect + read + write + timeout
            continue

        non_2xx_match = NON_2XX_RE.search(line)
        if non_2xx_match:
            metrics["error_count"] += int(non_2xx_match.group("count"))

    for requested, column in [(50.0, "p50_latency_ms"), (95.0, "p95_latency_ms"), (99.0, "p99_latency_ms")]:
        metrics[column] = percentile_lookup(latency_percentiles, requested)

    return metrics


def percentile_lookup(latencies: dict[float, float], requested: float) -> float | None:
    for percentile, latency in latencies.items():
        if abs(percentile - requested) <= 0.001:
            return latency
    return None


def resource_summary(path: Path) -> dict[str, float | None]:
    cpu_values: list[float] = []
    memory_values: list[float] = []

    if not path.exists():
        return {
            "cpu_percent_avg": None,
            "cpu_percent_max": None,
            "memory_bytes_avg": None,
            "memory_bytes_max": None,
        }

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            cpu = parse_float(row.get("cpu_percent"))
            memory = bytes_to_float(row.get("mem_usage", ""))
            if cpu is not None:
                cpu_values.append(cpu)
            if memory is not None:
                memory_values.append(memory)

    return {
        "cpu_percent_avg": mean(cpu_values),
        "cpu_percent_max": max(cpu_values) if cpu_values else None,
        "memory_bytes_avg": mean(memory_values),
        "memory_bytes_max": max(memory_values) if memory_values else None,
    }


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def empty_to_none(value: Any) -> Any:
    if value == "":
        return None
    return value


def validate_row(row: dict[str, Any]) -> None:
    reasons: list[str] = []

    if parse_int(row.get("wrk_exit_code")) not in (0, None):
        reasons.append(f"wrk_exit_code={row.get('wrk_exit_code')}")

    required_numeric = ["requested_rate", "achieved_throughput", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms"]
    for column in required_numeric:
        value = row.get(column)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            reasons.append(f"missing {column}")
        elif float(value) < 0:
            reasons.append(f"negative {column}")

    if row.get("total_requests") is None:
        reasons.append("missing total_requests")

    row["valid"] = not reasons
    row["failure_reason"] = "; ".join(reasons)


def parse_run(run_dir: Path) -> dict[str, Any]:
    metadata = read_metadata(run_dir / "metadata.env")
    wrk_metrics = parse_wrk_output(run_dir / "wrk.txt")
    resources = resource_summary(run_dir / "resources.csv")

    requested_rate = parse_float(metadata.get("requested_rate"))
    achieved_throughput = wrk_metrics.get("achieved_throughput")
    throughput_ratio = None
    if requested_rate and achieved_throughput is not None:
        throughput_ratio = float(achieved_throughput) / requested_rate

    row: dict[str, Any] = {
        "run_id": metadata.get("run_id", run_dir.name),
        "mode": metadata.get("mode"),
        "workload_name": metadata.get("workload_name"),
        "requested_rate": requested_rate,
        "achieved_throughput": achieved_throughput,
        "throughput_ratio": throughput_ratio,
        "p50_latency_ms": wrk_metrics.get("p50_latency_ms"),
        "p95_latency_ms": wrk_metrics.get("p95_latency_ms"),
        "p99_latency_ms": wrk_metrics.get("p99_latency_ms"),
        "total_requests": wrk_metrics.get("total_requests"),
        "error_count": wrk_metrics.get("error_count"),
        "timeout_count": wrk_metrics.get("timeout_count"),
        "duration_seconds": parse_float(metadata.get("duration_seconds")) or wrk_metrics.get("observed_duration_seconds"),
        "wrk_threads": parse_int(metadata.get("wrk_threads")),
        "wrk_connections": parse_int(metadata.get("wrk_connections")),
        "server_workers": parse_int(metadata.get("server_workers")),
        "target_url": metadata.get("target_url"),
        "started_at": metadata.get("started_at"),
        "ended_at": metadata.get("ended_at"),
        "repeat": parse_int(metadata.get("repeat")),
        "raw_dir": str(run_dir),
        "server_commit": metadata.get("server_commit"),
        "wrk_exit_code": parse_int(metadata.get("wrk_exit_code")),
    }
    row.update(resources)

    if wrk_metrics.get("parse_error"):
        row["failure_reason"] = wrk_metrics["parse_error"]

    validate_row(row)
    if wrk_metrics.get("parse_error"):
        prefix = row["failure_reason"]
        row["failure_reason"] = f"{prefix}; {wrk_metrics['parse_error']}" if prefix else wrk_metrics["parse_error"]
        row["valid"] = False

    return {column: empty_to_none(row.get(column)) for column in OUTPUT_COLUMNS}


def discover_runs(raw_dir: Path) -> list[Path]:
    if not raw_dir.exists():
        return []
    return sorted(path for path in raw_dir.iterdir() if path.is_dir() and (path / "metadata.env").exists())


def write_output(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    rows = [parse_run(run_dir) for run_dir in discover_runs(args.raw_dir)]
    write_output(rows, args.output)

    valid_count = sum(1 for row in rows if row["valid"])
    print(f"Wrote {len(rows)} rows to {args.output} ({valid_count} valid).")
    if not rows:
        print("No experiment runs found. This is expected before running the smoke test.")


if __name__ == "__main__":
    main()

