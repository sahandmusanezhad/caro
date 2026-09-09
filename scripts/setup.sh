#!/usr/bin/env bash
# Get to a working interpreter with what the suites need, without needing root.
#
#     ./scripts/setup.sh                 numpy — the only hard dependency
#     ./scripts/setup.sh --extras        …and scipy + the API packages, so all
#                                        ten suites run instead of eight
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
#
# `--extras` exists because the README used to say "pip install scipy" in
# plain text — a command this very script documents as failing on exactly the
# platform most readers are on. Telling someone to run a command that cannot
# work is the same defect whether it is in a README or a docstring, and the
# fix is to route the extras through the ladder that already works rather
# than to write the caveat down a second time.

set -uo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

WANT_EXTRAS=0
[ "${1:-}" = "--extras" ] && WANT_EXTRAS=1

# scipy builds the oracle in tests/test_appraisal.py; fastapi and pydantic are
# what the API contract suite imports. Neither is needed by `caro/` itself —
# that stays numpy-only, which is the claim the README makes and this script
# must not quietly break.
if [ "$WANT_EXTRAS" = "1" ]; then
  PKGS="numpy scipy fastapi pydantic uvicorn"
  WHAT="numpy and the test extras"
  THEN="all ten suites"
else
  PKGS="numpy"
  WHAT="numpy"
  THEN="eight of ten suites — run with --extras for the other two"
fi

echo "python: $($PY --version 2>&1)"
echo "installing: $PKGS"
echo

ok() { echo; echo "✓ $1"; echo; echo "  $2"; echo; echo "  → $THEN"; echo; exit 0; }

# `import numpy` is not enough once extras are wanted: numpy alone would
# short-circuit the ladder and leave scipy missing, which is how a "success"
# message ends with two suites still skipped.
have_all() {
  local py="$1" m
  for m in $PKGS; do
    $py -c "import $m" 2>/dev/null || return 1
  done
  return 0
}

# ---- 1. already present ---------------------------------------------------
# Distributions ship python3-numpy far more often than people expect, and if
# it is there the whole suite runs with nothing installed at all.
if have_all "$PY"; then
  ok "$WHAT already available — nothing to install." \
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
  # shellcheck disable=SC2086
  if .venv/bin/python -m pip install --quiet $PKGS 2>/dev/null \
     && have_all .venv/bin/python; then
    ok "$WHAT installed into .venv" \
       "source .venv/bin/activate && python tests/run_all.py"
  fi
  # A venv without pip is worse than no venv: `bin/python` exists so it looks
  # usable, but `bin/activate` may not, and a later `source .venv/bin/activate`
  # fails confusingly. Debian creates exactly this when python3-venv is absent.
  echo "the venv came out without pip — removing it so it cannot mislead later"
  rm -rf .venv
fi

# ---- 3. a user-site install ----------------------------------------------
# --user writes to ~/.local, which apt does not manage, so this does not
# actually put the system packages at risk despite the flag's name.
echo "trying a user-site install (~/.local, not the system python)…"
# shellcheck disable=SC2086
if $PY -m pip install --user --break-system-packages --quiet $PKGS 2>/dev/null \
   || $PY -m pip install --user --quiet $PKGS 2>/dev/null; then
  if have_all "$PY"; then
    ok "$WHAT installed to ~/.local" "$PY tests/run_all.py"
  fi
fi

# ---- 4. out of options that avoid root -----------------------------------
cat <<MSG

Could not install $WHAT without root. Pick whichever suits you:

  # the distribution's own packages — no pip involved
  sudo apt install python3-numpy$([ "$WANT_EXTRAS" = 1 ] && echo " python3-scipy")

  # or enable venv, then re-run this script
  sudo apt install python3-venv

  # or, with no sudo at all, uv brings its own Python
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv venv && uv pip install $PKGS
  source .venv/bin/activate && python tests/run_all.py

numpy is the only hard dependency of caro/ itself. Without the extras the
suite still runs — it skips two of the ten by name and says so.
MSG
exit 1
