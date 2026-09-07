#!/usr/bin/env bash
# Bootstrap a virtual environment.
#
# Debian, Ubuntu and Fedora ship an "externally managed" Python (PEP 668):
# pip refuses to install into the system interpreter, and correctly so. A
# venv is the answer, not --break-system-packages.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
echo "python: $($PY --version)"

if [ ! -d .venv ]; then
  $PY -m venv .venv || {
    echo "venv failed. On Debian/Ubuntu: sudo apt install python3-venv" >&2
    exit 1; }
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet numpy

echo
echo "core installed. the whole test suite runs on numpy alone:"
echo "    source .venv/bin/activate"
echo "    python tests/run_all.py"
echo
echo "live collection additionally needs a browser:"
echo "    pip install playwright && playwright install chromium"
echo "    export CARO_SELLER_SALT=\"\$(head -c 24 /dev/urandom | base64)\""
echo "    python scripts/first_run.py --source bama --limit 50"
