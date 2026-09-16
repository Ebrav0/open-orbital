#!/bin/sh
# Run from the task directory. Requires Apple's compiler and Homebrew libomp.
set -eu
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
CFLAGS='-Xpreprocessor -fopenmp -DOPENMP -I/opt/homebrew/opt/libomp/include -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk' \
LDFLAGS='-L/opt/homebrew/opt/libomp/lib -lomp -Wl,-rpath,/opt/homebrew/opt/libomp/lib -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk' \
work/venv/bin/pip install --no-cache-dir --no-deps --no-binary=rebound --upgrade --target work/openmp rebound==5.1.1
for threads in 1 4 8 10 14; do
  PYTHONPATH="$PWD/work/openmp" OMP_WAIT_POLICY=PASSIVE work/venv/bin/python outputs/openmp_benchmark.py "$threads"
done
work/venv/bin/python outputs/append_openmp_report.py
