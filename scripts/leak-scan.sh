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
#
# `/home/<user>/` and `/Users/<user>/` (and `/root/`) are caught via the
# GENERIC_PATH_REGEX sweep below — this list is for maintainer-specific
# string identifiers only. README/CLAUDE.md claim leak-scan catches
# "/home/*/..." paths; the generic sweep makes that claim accurate
# regardless of which user installed.
PERSONAL_PATTERNS=(
    "zaikina"
    "radost"
    "strong-host"
)

# Generic home-path regex. Matches /home/<user>/<file>, /Users/<user>/<file>,
# /root/<file> — anybody's personal-substrate path looks like a leak. We
# require *something* after the trailing slash to avoid catching prose like
# "/home/<user>/" or "/root/" used illustratively in release notes.
GENERIC_PATH_REGEX='(/home/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|/root/[A-Za-z0-9_.-])'

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

# 3. Generic home-path patterns — /home/<user>/, /Users/<user>/, /root/.
#    Docs intentionally show placeholder paths (/home/your-name/...) and
#    weighted_compact/auto_label.py uses /home/ as a path-prefix regex in
#    its detector. docker-compose.yml mounts container-internal /root/.ollama
#    (canonical home for the root user inside the ollama image, not a leak).
#    Exclude those from the generic sweep; PERSONAL_PATTERNS above still
#    scans them for maintainer-specific identifiers.
GENERIC_EXCLUDE='^docs/|^CHANGELOG\.md$|^weighted_compact/auto_label\.py$|^docker-compose\.yml$'
generic_targets="$(echo "$FILES" | grep -vE "$GENERIC_EXCLUDE" || true)"
generic_matches="$(echo "$generic_targets" | xargs -d '\n' -r grep -lIE --color=never -- "$GENERIC_PATH_REGEX" 2>/dev/null || true)"
if [ -n "$generic_matches" ]; then
    echo "leak-scan: generic personal-path matched (regex: $GENERIC_PATH_REGEX)" >&2
    echo "$generic_matches" | awk '{print "  " $0}' >&2
    fail=1
fi

if [ "$fail" -ne 0 ]; then
    echo >&2
    echo "Refusing to proceed. Remove the leak or extend leak-scan.sh deliberately." >&2
    exit 1
fi

exit 0
