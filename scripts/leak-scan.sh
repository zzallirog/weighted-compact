#!/usr/bin/env bash
# Pre-commit guard against leaking personal substrate into the public repo.
#
# Blocks any staged change that introduces:
#   - Substrate filename patterns (*.jsonl, *.npz, *.model, *.bak.*)
#   - Hardcoded paths into a specific user's home (/home/<name>/work/weighted-compact)
#   - Known personal identifiers — extend PERSONAL_PATTERNS as needed
#
# Run manually:
#   scripts/leak-scan.sh         # scans entire tree
#   scripts/leak-scan.sh --staged  # scans only staged diff
#
# Install as a pre-commit hook:
#   scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Tunable: identifiers that must never appear in the public repo.
# Add lowercase substrings here when collaborators report leaks.
PERSONAL_PATTERNS=(
    "/home/zzalli"
    "zaikina"
    "radost"
    "strong-host"
)

FORBIDDEN_FILE_PATTERNS=(
    "*.jsonl"
    "*.npz"
    "*.model"
    "*.pkl"
    "*.pickle"
    "*.bak.*"
)

MODE="all"
if [ "${1:-}" = "--staged" ]; then
    MODE="staged"
fi

if [ "$MODE" = "staged" ]; then
    FILES="$(git diff --cached --name-only --diff-filter=ACMR)"
else
    FILES="$(git ls-files)"
fi

# This file lists the patterns by literal so they will (by design) match
# against themselves. Exclude leak-scan.sh from the file list so it does
# not self-report. Same for the CI workflow which mentions the patterns
# in the run command.
FILES="$(echo "$FILES" | grep -vE '^scripts/leak-scan\.sh$|^\.github/workflows/test\.yml$' || true)"

if [ -z "$FILES" ]; then
    exit 0
fi

fail=0

# 1. Forbidden file patterns.
while IFS= read -r f; do
    for pat in "${FORBIDDEN_FILE_PATTERNS[@]}"; do
        if [[ "$f" == $pat ]]; then
            echo "leak-scan: forbidden file path $f (matches $pat)" >&2
            fail=1
        fi
    done
done <<< "$FILES"

# 2. Personal identifiers inside text files. One combined ERE pass over the
#    file list so the cost scales with content size, not pattern count.
ere="$(IFS='|'; echo "${PERSONAL_PATTERNS[*]}")"
matches="$(echo "$FILES" | xargs -d '\n' -r grep -lIE --color=never -- "$ere" 2>/dev/null || true)"
if [ -n "$matches" ]; then
    echo "leak-scan: personal pattern matched (regex: $ere)" >&2
    echo "$matches" | awk '{print "  " $0}' >&2
    fail=1
fi

if [ "$fail" -ne 0 ]; then
    echo >&2
    echo "Refusing to proceed. Remove the leak or extend leak-scan.sh deliberately." >&2
    exit 1
fi

exit 0
