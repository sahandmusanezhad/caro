#!/usr/bin/env bash
# Get to a working interpreter with numpy, without needing root.
#
# Four routes, tried in order of how little they disturb the machine. Most
# people never get past the first two, and nobody should need sudo to run a
# test suite.
#
# The reason this is longer than `pip install numpy`: on Debian-family
# systems the system Python is externally managed (PEP 668) AND `python3-venv`
# is a separate package. So the obvious command fails, and the obvious fix
# also fails, and both failures point at `apt` — which needs root the user
# may not have. This script routes around that.

set -uo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
echo "python: $($PY --version 2>&1)"
echo

ok() { echo; echo "✓ $1"; echo; echo "  $2"; echo; exit 0; }

# ---- 1. numpy already present -------------------------------------------
# Distributions ship python3-numpy far more often than people expect, and if
# it is there the whole suite runs with nothing installed at all.
if $PY -c "import numpy" 2>/dev/null; then
  ok "numpy is already available — nothing to install." \
     "$PY tests/run_all.py"
fi

# ---- 2. a virtual environment --------------------------------------------
if [ ! -d .venv ]; then
  if $PY -m venv .venv 2>/dev/null; then
    :
  else
    echo "venv unavailable (python3-venv is a separate package on Debian)."
    rm -rf .venv
  fi
fi

if [ -x .venv/bin/python ]; then
  .venv/bin/python -m pip install --quiet --upgrade pip 2>/dev/null
  if .venv/bin/python -m pip install --quiet numpy; then
    ok "numpy installed into .venv" \
       "source .venv/bin/activate && python tests/run_all.py"
  fi
fi

# ---- 3. a user-site install ----------------------------------------------
# --user writes to ~/.local, which apt does not manage, so this does not
# actually put the system packages at risk despite the flag's name. For a
# leaf package like numpy it is the pragmatic route when venv is missing.
echo "trying a user-site install (~/.local, not the system python)…"
if $PY -m pip install --user --break-system-packages --quiet numpy 2>/dev/null \
   || $PY -m pip install --user --quiet numpy 2>/dev/null; then
  if $PY -c "import numpy" 2>/dev/null; then
    ok "numpy installed to ~/.local" "$PY tests/run_all.py"
  fi
fi

# ---- 4. out of options that avoid root -----------------------------------
cat <<'MSG'

Could not install numpy without root. Pick whichever suits you:

  # the distribution's own numpy — no pip involved
  sudo apt install python3-numpy

  # or enable venv, then re-run this script
  sudo apt install python3.14-venv

  # or, with no sudo at all, uv brings its own Python
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv venv && uv pip install numpy
  source .venv/bin/activate && python tests/run_all.py

numpy is the only hard dependency. Everything else in CARO is stdlib.
MSG
exit 1
