#!/usr/bin/env bash
# Install weighted-compact's pre-commit hook into .git/hooks/pre-commit.
# Idempotent: re-runs replace the symlink.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if ! [ -d "$HOOKS_DIR" ]; then
    echo "ERROR: $HOOKS_DIR not found — is this a git checkout?" >&2
    exit 1
fi

cat > "$HOOKS_DIR/pre-commit" <<'EOF'
#!/usr/bin/env bash
# weighted-compact pre-commit — leak-scan + ruff (if available).
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
"$REPO_ROOT/scripts/leak-scan.sh" --staged
if command -v ruff >/dev/null 2>&1; then
    ruff check "$REPO_ROOT/weighted_compact"
fi
EOF
chmod +x "$HOOKS_DIR/pre-commit"
echo "installed: $HOOKS_DIR/pre-commit"
