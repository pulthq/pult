#!/bin/bash
# What CI does, here, before any build (review 2026-10-27, Т10): a fresh environment from both requirements, a home of
# its own and none of this shell's settings (env -i), the four suites, then the lint and the consistency check. About
# 3 minutes and 300 MB (the Agent SDK carries Claude Code) in a temporary folder that goes at the end. Windows is
# checked on GitHub only.
#   bash tools/ci_local.sh               PYTHON=<path> — another interpreter than 3.12
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
base=${TMPDIR:-/tmp}
T=$(mktemp -d "${base%/}/pult-ci-XXXXXX")
trap 'rm -rf "$T"' EXIT
PY=${PYTHON:-$(command -v python3.12 || command -v python3)}      # CI runs 3.12
echo "environment: $("$PY" --version) → $T"
"$PY" -m venv "$T/venv" || exit 2
"$T/venv/bin/pip" install -q --disable-pip-version-check -r requirements.txt -r relay/requirements.txt \
  ruff==0.17.3 shellcheck-py==0.11.0.1 || exit 2
mkdir "$T/home" "$T/tmp"
# what a runner has: git, and node for the app's markdown tests; nothing of this computer's Pult or proxies
NODE=$(command -v node || true)
P="$T/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin${NODE:+:$(dirname "$NODE")}"
run() { env -i HOME="$T/home" PATH="$P" PYTHONUTF8=1 LANG=en_US.UTF-8 TMPDIR="$T/tmp" "$@"; }
fail=0
for t in test_pult test_setup test_web test_relay; do
  if out=$(run python "tests/$t.py" 2>&1); then
    printf '%-11s %s\n' "$t" "$(echo "$out" | grep -E '^(Ran|OK)' | tr '\n' ' ')"
  else
    printf '%-11s FAILED\n' "$t"
    echo "$out" | tail -30
    fail=1
  fi
done
run ruff check --no-cache . || fail=1
run shellcheck install.sh deploy/relay/install.sh src/pult-tab.sh tools/ci_local.sh && echo "shellcheck: clean" || fail=1
run python tools/consistency.py || fail=1
[ "$fail" = 0 ] && echo "all as on CI" || echo "something fails — see above"
exit "$fail"
