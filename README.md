# System Performance Analytics and Bottleneck Detection

This project measures how workload affects a from-scratch C++ HTTP/1.1 server built around `epoll`, then turns those measurements into a small data science workflow.

The main deliverable is not the benchmark command itself. The deliverable is a reproducible pipeline that collects raw measurements, parses them into structured CSV data, visualizes the results, and writes an evidence-based findings report.

## Questions

1. How does request load affect p50, p95, and p99 latency?
2. At what observed load does latency begin to deteriorate significantly?
3. Does achieved throughput continue to match requested throughput as load increases?
4. How do CPU and memory usage change as workload increases?
5. Which measured variables are associated with high latency?
6. How repeatable are results across independent runs?
7. If two server configurations are provided later, which performs better under matched workloads?

The seventh question is currently marked `Not run` because no second server configuration was provided.

## Architecture

```text
C++ HTTP server -> Docker container -> wrk2 open-loop load -> raw files -> clean CSV -> Python analysis -> figures and findings
```

Tools:

- Docker builds and runs the C++ server without modifying `../server`.
- wrk2 generates open-loop HTTP traffic at configured request rates.
- Docker stats provides coarse CPU and memory observations.
- pandas and NumPy support tabular analysis.
- matplotlib generates figures.

## Server Baseline

- Server repository: `../server`
- Initial server commit: `5efe0bd4c5c93c5fdc7de5bcd5d2268fe8a8a3ca`
- Initial server status: clean

The baseline is recorded in `data/raw/server_git_baseline.txt`. Experiment runs call `scripts/check_server_untouched.sh` on exit, including failure and interruption paths, to compare the current server commit and status with the baseline.

## Environment

Record local environment details before publishing results:

```bash
uname -a
docker --version
docker compose version
python3 --version
./loadtest/wrk2/wrk --version
```

If running inside WSL2, also record the Windows, WSL, and Docker Desktop versions in the final report. These values are intentionally not filled in here because they have not been measured by the experiment pipeline yet.

Observed during implementation:

- `uname -a`: `Linux deepakmarudi 6.6.87.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC Thu Jun 5 18:30:46 UTC 2025 x86_64 x86_64 x86_64 GNU/Linux`
- `python3 --version`: `Python 3.10.12`
- `docker --version`: Docker was not available inside this WSL2 distro; Docker Desktop WSL integration needs to be enabled before experiments can run here.
- `wsl.exe --version`: unavailable from this shell due to a WSL vsock error.
- `wrk2`: not installed yet.

## Setup

Create a Python environment and install analysis dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Build wrk2 locally inside this analytics repository:

```bash
./loadtest/setup_wrk2.sh
```

Review or edit `config.env` for rates, repeats, worker count, connection count, and target path.

## Run Experiments

Start with the smoke test:

```bash
./loadtest/run_experiments.sh smoke
```

The smoke run verifies that Docker can build the server image, the server starts, `GET /` succeeds, wrk2 can generate traffic, raw files are written, and the parser has data to read.

After the smoke data parses successfully, run the full workload sweep:

```bash
./loadtest/run_experiments.sh full
```

Raw output is stored under `data/raw/<run_id>/`.

## Parse and Analyze

```bash
python3 analysis/parse_results.py
python3 analysis/explore_data.py
python3 analysis/performance_analysis.py
```

Outputs:

- `data/clean.csv`
- `results/figures/latency_vs_load.png`
- `results/figures/throughput_requested_vs_achieved.png`
- `results/figures/resource_usage_vs_load.png`
- `results/figures/error_rate_vs_load.png`
- `results/figures/latency_variation_repeats.png`
- `docs/findings.md`

## Dataset Columns

- `run_id`: unique run directory identifier.
- `valid`: whether required benchmark fields parsed successfully and wrk2 exited cleanly.
- `failure_reason`: explanation for invalid or incomplete runs.
- `mode`: `smoke` or `full`.
- `workload_name`: label from `config.env`.
- `requested_rate`: offered load passed to wrk2, in requests/second.
- `achieved_throughput`: throughput reported by wrk2, in requests/second.
- `throughput_ratio`: achieved throughput divided by requested rate.
- `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`: latency percentiles in milliseconds.
- `total_requests`: total requests reported by wrk2.
- `error_count`: socket errors plus non-2xx/3xx responses reported by wrk2.
- `timeout_count`: wrk2 socket timeout count.
- `cpu_percent_avg`, `cpu_percent_max`: Docker CPU samples for the server container.
- `memory_bytes_avg`, `memory_bytes_max`: Docker memory usage samples for the server container.
- `duration_seconds`: configured run duration.
- `wrk_threads`, `wrk_connections`: wrk2 workload settings.
- `server_workers`: C++ server worker thread count.
- `target_url`: benchmark URL.
- `started_at`, `ended_at`: UTC timestamps.
- `repeat`: repeat index for the load level.
- `raw_dir`: source raw run directory.
- `server_commit`: server commit used for the run.

## Current Findings

Not run. No benchmark experiment has been executed yet, so there are no evidence-based claims about latency, throughput, CPU, memory, errors, repeatability, or bottlenecks.

The current findings report is [docs/findings.md](docs/findings.md). It will be overwritten with measured observations after running `analysis/performance_analysis.py`.

## Limitations

- Results will describe this server, endpoint, payload, hardware, Docker setup, and wrk2 client environment only.
- Docker stats are coarse resource samples and may miss short spikes.
- wrk2 is useful for overload testing because it keeps offering the configured rate, but the client machine can still become the bottleneck.
- Associations between latency and CPU, memory, errors, or throughput degradation do not prove causality.

## Reproduction

1. Confirm the server baseline:

   ```bash
   ./scripts/check_server_untouched.sh --check
   ```

2. Install dependencies and wrk2.
3. Run `./loadtest/run_experiments.sh smoke`.
4. Parse and analyze the smoke output.
5. Run `./loadtest/run_experiments.sh full` only after the smoke run is valid.
6. Re-run the analysis scripts.

