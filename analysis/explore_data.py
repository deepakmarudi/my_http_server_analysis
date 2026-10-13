#!/usr/bin/env python3
"""Generate exploratory performance figures from data/clean.csv."""

from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("results/.matplotlib").resolve()))
warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/clean.csv", type=Path)
    parser.add_argument("--figures-dir", default="results/figures", type=Path)
    return parser.parse_args()


def load_valid_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    if df.empty or "valid" not in df:
        return pd.DataFrame()

    valid = df[df["valid"].astype(str).str.lower().isin(["true", "1"])].copy()
    numeric_columns = [
        "requested_rate",
        "achieved_throughput",
        "throughput_ratio",
        "p50_latency_ms",
        "p95_latency_ms",
        "p99_latency_ms",
        "total_requests",
        "error_count",
        "cpu_percent_avg",
        "memory_bytes_avg",
    ]
    for column in numeric_columns:
        if column in valid:
            valid.loc[:, column] = pd.to_numeric(valid[column], errors="coerce")
    return valid


def save_no_data_marker(figures_dir: Path) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    marker = figures_dir / "NOT_RUN.txt"
    marker.write_text(
        "No valid experiment rows were available, so figures were not generated.\n"
        "Run ./loadtest/run_experiments.sh smoke, parse the results, and rerun this script.\n",
        encoding="utf-8",
    )


def plot_latency_vs_load(df: pd.DataFrame, figures_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    for column, label in [
        ("p50_latency_ms", "p50"),
        ("p95_latency_ms", "p95"),
        ("p99_latency_ms", "p99"),
    ]:
        grouped = df.groupby("requested_rate", as_index=False)[column].median()
        ax.plot(grouped["requested_rate"], grouped[column], marker="o", label=f"{label} median")
        ax.scatter(df["requested_rate"], df[column], alpha=0.25, s=20)

    ax.set_title("Latency Percentiles vs Offered Load")
    ax.set_xlabel("Requested rate (requests/second)")
    ax.set_ylabel("Latency (milliseconds)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figures_dir / "latency_vs_load.png", dpi=160)
    plt.close(fig)


def plot_throughput(df: pd.DataFrame, figures_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df["requested_rate"], df["achieved_throughput"], alpha=0.8, label="Observed runs")
    max_rate = max(df["requested_rate"].max(), df["achieved_throughput"].max())
    ax.plot([0, max_rate], [0, max_rate], linestyle="--", color="black", label="requested = achieved")
    ax.set_title("Requested vs Achieved Throughput")
    ax.set_xlabel("Requested rate (requests/second)")
    ax.set_ylabel("Achieved throughput (requests/second)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figures_dir / "throughput_requested_vs_achieved.png", dpi=160)
    plt.close(fig)


def plot_resources(df: pd.DataFrame, figures_dir: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    grouped = df.groupby("requested_rate", as_index=False).agg(
        cpu_percent_avg=("cpu_percent_avg", "mean"),
        memory_mib_avg=("memory_bytes_avg", lambda values: values.mean() / 1024 / 1024),
    )

    axes[0].plot(grouped["requested_rate"], grouped["cpu_percent_avg"], marker="o", label="CPU avg")
    axes[0].scatter(df["requested_rate"], df["cpu_percent_avg"], alpha=0.25, s=20)
    axes[0].set_title("CPU Usage vs Offered Load")
    axes[0].set_ylabel("CPU utilization (%)")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(grouped["requested_rate"], grouped["memory_mib_avg"], marker="o", color="tab:green", label="Memory avg")
    axes[1].scatter(df["requested_rate"], df["memory_bytes_avg"] / 1024 / 1024, alpha=0.25, s=20, color="tab:green")
    axes[1].set_title("Memory Usage vs Offered Load")
    axes[1].set_xlabel("Requested rate (requests/second)")
    axes[1].set_ylabel("Memory usage (MiB)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(figures_dir / "resource_usage_vs_load.png", dpi=160)
    plt.close(fig)


def plot_errors(df: pd.DataFrame, figures_dir: Path) -> None:
    error_rate = df["error_count"] / df["total_requests"].replace(0, pd.NA)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(df["requested_rate"], error_rate.fillna(0), alpha=0.8, label="Observed runs")
    grouped = pd.DataFrame({"requested_rate": df["requested_rate"], "error_rate": error_rate}).groupby(
        "requested_rate", as_index=False
    )["error_rate"].mean()
    ax.plot(grouped["requested_rate"], grouped["error_rate"].fillna(0), marker="o", label="Mean error rate")
    ax.set_title("Error Rate vs Offered Load")
    ax.set_xlabel("Requested rate (requests/second)")
    ax.set_ylabel("Errors / total requests")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figures_dir / "error_rate_vs_load.png", dpi=160)
    plt.close(fig)


def plot_repeat_variation(df: pd.DataFrame, figures_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    rates = sorted(df["requested_rate"].dropna().unique())
    values = [df.loc[df["requested_rate"] == rate, "p95_latency_ms"].dropna() for rate in rates]

    if any(len(series) > 1 for series in values):
        ax.boxplot(values, labels=[str(int(rate)) for rate in rates], showmeans=True)
    else:
        ax.scatter(df["requested_rate"].astype(str), df["p95_latency_ms"], alpha=0.8)

    ax.set_title("Run-to-Run Variation in p95 Latency")
    ax.set_xlabel("Requested rate (requests/second)")
    ax.set_ylabel("p95 latency (milliseconds)")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(figures_dir / "latency_variation_repeats.png", dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    figures_dir = args.figures_dir
    figures_dir.mkdir(parents=True, exist_ok=True)
    df = load_valid_data(args.input)

    if df.empty:
        save_no_data_marker(figures_dir)
        print("No valid rows found; wrote NOT_RUN marker instead of figures.")
        return

    plot_latency_vs_load(df, figures_dir)
    plot_throughput(df, figures_dir)
    plot_resources(df, figures_dir)
    plot_errors(df, figures_dir)
    plot_repeat_variation(df, figures_dir)
    print(f"Wrote figures to {figures_dir}")


if __name__ == "__main__":
    main()

