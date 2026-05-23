#!/usr/bin/env bash
# outbound-zero-scan.sh — verify the runtime makes zero non-localhost outbound calls.
#
# Usage:
#   bash scripts/outbound-zero-scan.sh        # full tree scan (CI default)
#   bash scripts/outbound-zero-scan.sh --verbose  # show allowed matches too
#
# Rules codified here mirror .github/workflows/outbound-zero.yml exactly.
# Allowlist:
#   - http(s)://127.0.0.1, localhost, 0.0.0.0  — always allowed
#   - host.docker.internal                      — always allowed (docker compose)
#   - openrouter.ai                             — allowed ONLY in scripts/sonnet_rejudge.py
#   - github.com / githubusercontent.com          — allowed in comments/docs, NOT in call sites
#   - docs.nvidia.com and similar doc-only refs — allowed in comments/docs only
#   - api.anthropic.com                         — allowed ONLY in weighted_compact/baselines/compact_simulator.py

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERBOSE=0
if [ "${1:-}" = "--verbose" ]; then
    VERBOSE=1
fi

# ---------------------------------------------------------------------------
# Files to scan: runtime code + scripts + docker compose. Excludes:
#   - .venv/, build/, *.egg-info  (generated/vendor)
#   - the scan script itself and the outbound-zero workflow (they mention patterns)
#   - __pycache__
# ---------------------------------------------------------------------------
SCAN_DIRS=(
    "weighted_compact"
    "scripts"
    "tests"
    "docker-compose.yml"
    "docker-entrypoint.sh"
)

# Collect existing paths only
SCAN_TARGETS=()
for target in "${SCAN_DIRS[@]}"; do
    if [ -e "$target" ]; then
        SCAN_TARGETS+=("$target")
    fi
done

if [ ${#SCAN_TARGETS[@]} -eq 0 ]; then
    echo "outbound-zero-scan: no scan targets found — nothing to check" >&2
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1: find all HTTP(S) URLs with an external-looking domain (has a TLD).
# PCRE2 negative lookahead skips localhost/127.0.0.1/0.0.0.0/host.docker.internal
# immediately. Everything else flows into the allowlist filter below.
# ---------------------------------------------------------------------------
URL_PATTERN='https?://(?!127\.0\.0\.1|localhost|0\.0\.0\.0|host\.docker\.internal)[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}'

# rg exits 1 when no matches — treat that as clean
raw_hits="$(
    rg --pcre2 \
        --with-filename \
        --no-heading \
        --line-number \
        --color=never \
        --glob "!**/.venv/**" \
        --glob "!**/build/**" \
        --glob "!**/*.egg-info/**" \
        --glob "!**/__pycache__/**" \
        --glob "!scripts/outbound-zero-scan.sh" \
        --glob "!.github/workflows/outbound-zero.yml" \
        "$URL_PATTERN" \
        "${SCAN_TARGETS[@]}" 2>/dev/null || true
)"

if [ -z "$raw_hits" ]; then
    echo "outbound-zero-scan: PASS — no external URLs found"
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: apply the allowlist.
# Each rule is a grep -v pattern that removes lines we explicitly permit.
# Order: broadest first (localhost already excluded by rg), then specifics.
# ---------------------------------------------------------------------------

# Rule A: openrouter.ai is allowed ONLY inside scripts/sonnet_rejudge.py
# Rule B: github.com / githubusercontent.com allowed ONLY in comment/doc lines
#         Comment indicators: line content after "file:lineno:" starts with
#         optional whitespace then #, //, *, --, or is inside a docstring
#         (we detect """ or # prefix lines).
# Rule C: docs.nvidia.com — doc reference in a comment, always allowed
# Rule D: api.anthropic.com — allowed ONLY in weighted_compact/baselines/compact_simulator.py

violations=""

while IFS= read -r hit; do
    file_part="$(echo "$hit" | cut -d: -f1)"
    line_part="$(echo "$hit" | cut -d: -f2)"
    content="$(echo "$hit" | cut -d: -f3-)"

    # Strip leading whitespace from content for comment detection
    trimmed="$(echo "$content" | sed 's/^[[:space:]]*//')"

    # Is this line a comment? Covers #, //, *, --  prefixes and inline # after code
    is_comment=0
    if echo "$trimmed" | grep -qE '^(#|//|\*|--|""")'; then
        is_comment=1
    fi

    # Extract the domain from the URL for domain-level checks
    url_in_line="$(echo "$content" | grep -oE 'https?://[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}' | head -1)"
    domain="$(echo "$url_in_line" | sed 's|https\?://||' | cut -d/ -f1 | cut -d: -f1)"

    allowed=0

    case "$domain" in
        openrouter.ai)
            # Allowed only in scripts/sonnet_rejudge.py (maintainer one-off)
            if [ "$file_part" = "scripts/sonnet_rejudge.py" ]; then
                allowed=1
                [ "$VERBOSE" = "1" ] && echo "  [allowed:openrouter-exception] $hit"
            fi
            ;;
        github.com|raw.githubusercontent.com|githubusercontent.com|codeload.github.com|objects.githubusercontent.com)
            # Allowed in:
            #   - comment / doc lines (# prefix etc)
            #   - scripts/sonnet_rejudge.py (HTTP-Referer header value, not a call to github)
            #   - scripts/bench_vs_claude_mem.sh (die/error message install instructions)
            if [ "$is_comment" = "1" ] \
               || [ "$file_part" = "scripts/sonnet_rejudge.py" ] \
               || [ "$file_part" = "scripts/bench_vs_claude_mem.sh" ]; then
                allowed=1
                [ "$VERBOSE" = "1" ] && echo "  [allowed:github-ref] $hit"
            fi
            ;;
        api.anthropic.com)
            # Allowed only in weighted_compact/baselines/compact_simulator.py
            if [ "$file_part" = "weighted_compact/baselines/compact_simulator.py" ]; then
                allowed=1
                [ "$VERBOSE" = "1" ] && echo "  [allowed:anthropic-exception] $hit"
            fi
            ;;
        docs.nvidia.com|docs.docker.com|docs.python.org|docs.github.com)
            # Doc-site references in comments — always allowed
            if [ "$is_comment" = "1" ]; then
                allowed=1
                [ "$VERBOSE" = "1" ] && echo "  [allowed:docs-comment] $hit"
            fi
            ;;
        *)
            # Unknown external domain — violation
            ;;
    esac

    if [ "$allowed" = "0" ]; then
        violations="${violations}${hit}"$'\n'
    fi
done <<< "$raw_hits"

violations="$(echo "$violations" | grep -v '^$' || true)"

if [ -z "$violations" ]; then
    echo "outbound-zero-scan: PASS — all external URLs are within the allowlist"
    exit 0
fi

echo "outbound-zero-scan: FAIL — non-localhost outbound URLs detected:" >&2
echo >&2
echo "$violations" | while IFS= read -r line; do
    echo "  $line" >&2
done
echo >&2
echo "If this URL is intentional, update the allowlist in scripts/outbound-zero-scan.sh" >&2
echo "and document the exception in .github/workflows/outbound-zero.yml." >&2
exit 1
