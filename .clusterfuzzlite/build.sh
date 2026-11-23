#!/bin/bash -eu

# base-builder-python doesn't ship atheris itself -- every OSS-Fuzz Python
# project installs it explicitly in build.sh.
pip3 install atheris

# Installs backend/app as a real importable package (pyproject.toml already
# declares `packages = [{ include = "app" }]`), so the fuzz harnesses below
# can `import app.scanner.*` without any PYTHONPATH wiring.
cd "$SRC/magewiki/backend"
pip3 install .

cd "$SRC/magewiki"
for fuzzer in .clusterfuzzlite/fuzz_*.py; do
  compile_python_fuzzer "$fuzzer"
done
