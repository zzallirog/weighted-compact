#!/usr/bin/env bash
# docker-entrypoint.sh — weighted-compact container entry point.
#
# Behaviour:
#   - If CMD is "serve" (default): check substrate exists first.
#     Exit with a clear message if bootstrap has not been run.
#   - If CMD is "rem-loop": sleep-loop wrapper for nightly REM pass.
#   - All other CMDs are passed straight through to weighted-compact.

set -euo pipefail

SUBSTRATE_DATA="${WEIGHTED_COMPACT_DATA:-/data/weighted-compact}"
PAIRS_FILE="${SUBSTRATE_DATA}/pairs.jsonl"

cmd="${1:-serve}"

if [ "$cmd" = "rem-loop" ]; then
    # Nightly REM-decay pass. Sleeps until the next 04:00 UTC, runs
    # weighted-compact rem-pass, then repeats every 24 hours.
    echo "weighted-compact rem-loop: will run rem-pass nightly at 04:00 UTC"
    while true; do
        now_epoch=$(date -u +%s)
        # Next 04:00 UTC
        today_4=$(date -u -d "today 04:00" +%s 2>/dev/null \
            || date -u -j -f "%Y-%m-%d %H:%M:%S" "$(date -u +%Y-%m-%d) 04:00:00" +%s)
        if [ "$today_4" -le "$now_epoch" ]; then
            tomorrow_4=$((today_4 + 86400))
            sleep_secs=$((tomorrow_4 - now_epoch))
        else
            sleep_secs=$((today_4 - now_epoch))
        fi
        echo "rem-loop: sleeping ${sleep_secs}s until next 04:00 UTC"
        sleep "$sleep_secs"
        echo "rem-loop: running weighted-compact rem-pass at $(date -u --iso-8601=seconds)"
        weighted-compact rem-pass || echo "rem-pass exited non-zero — continuing loop"
    done
fi

if [ "$cmd" = "serve" ]; then
    if [ ! -f "$PAIRS_FILE" ]; then
        echo ""
        echo "  ERROR: substrate not found at ${SUBSTRATE_DATA}/pairs.jsonl"
        echo ""
        echo "  Run bootstrap first:"
        echo "    docker compose run --rm weighted-compact bootstrap"
        echo ""
        echo "  Then start the labeler:"
        echo "    docker compose up -d weighted-compact"
        echo ""
        exit 1
    fi
fi

exec weighted-compact "$@"
