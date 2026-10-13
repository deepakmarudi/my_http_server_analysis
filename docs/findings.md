# Findings

## Status

Not run. No valid experiment rows are available in `data/clean.csv`.

Invalid or incomplete rows present: 0.

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
