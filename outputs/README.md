# CPU gravity benchmark

Start with **BENCHMARK_REPORT.md** for results, methods and limits.

- `benchmark_charts.png`: serial scaling, independent workers, sustained throughput, accuracy.
- `threaded_charts.png`: one simulation across multiple CPU threads.
- `benchmark_results.json`, `openmp_*.json`, `resource_samples.jsonl`: actual measurements.
- `gravity_benchmark.py`: CPU suite, including the ten-minute load test.
- `openmp_benchmark.py`, `build_openmp.sh`: supplemental native multicore build and tests.
- `DESIGN_NOTES.md`: implications for a future observatory.

From the parent task directory, use the existing `work/venv/bin/python`. The local environments are isolated under `work/`; no global Python installation was modified.

To regenerate reports from the saved results:

```sh
work/venv/bin/python outputs/make_report.py
work/venv/bin/python outputs/append_openmp_report.py
work/venv/bin/python outputs/verify_results.py
```

Run `sh outputs/build_openmp.sh` only to rebuild and rerun threaded tests. It uses the existing Homebrew libomp runtime and the installed macOS 26.5 SDK.
