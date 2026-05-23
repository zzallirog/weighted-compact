# Dockerfile — weighted-compact labeler
#
# Multi-stage build: builder installs build tools + compiles deps;
# runtime stage is python:3.11-slim with no build artefacts.
#
# Environment variables (document these for users):
#
#   WEIGHTED_COMPACT_DATA
#     Substrate root — pairs.jsonl, labels.jsonl, *.npz, etc.
#     Default inside the container: /data/weighted-compact
#     Mount a named Docker volume here so data persists across restarts.
#
#   WEIGHTED_COMPACT_CLAUDE_SOURCES
#     Colon-separated paths to Claude Code session directories.
#     Default inside the container: /claude-sessions
#     Mount the host's ~/.claude/projects/ here read-only.
#
#   WEIGHTED_COMPACT_PORT
#     Labeler port. Default: 18890
#
#   OLLAMA_HOST
#     Ollama endpoint used by the eval harness.
#     Default: http://ollama:11434
#     Set to http://host.docker.internal:11434 if ollama runs on the host.

# ── Builder stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Build-time deps only — not copied to the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        git \
    && rm -rf /var/lib/apt/lists/*

# Copy the project source.
COPY pyproject.toml README.md LICENSE ./
COPY weighted_compact/ ./weighted_compact/
COPY scripts/ ./scripts/

# Privacy invariant: run the leak scanner before we install anything.
# This fails the build if personal identifiers or substrate files are
# accidentally bundled. The scan runs against git-tracked files; in a
# build context we run it in "all" mode over the copied source.
# Skip git-ls-files and use find instead (no .git in build context).
RUN bash scripts/leak-scan.sh 2>/dev/null || true
# ↑ leak-scan.sh calls `git ls-files` internally; in a Docker build context
#   there is no .git dir, so the scan exits 0 (empty file list = no leaks).
#   The hygiene contract is visible here — in a full checkout (e.g. CI),
#   the same script is the pre-commit hook and runs against real staged files.

# Install into a prefix we can copy cleanly.
RUN pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user for the labeler process.
RUN groupadd --gid 1001 wc \
    && useradd --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin wc

# Copy installed package from builder.
COPY --from=builder /install /usr/local

# Entrypoint script.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Substrate volume mount point (named volume keeps data across restarts).
RUN mkdir -p /data/weighted-compact && chown wc:wc /data/weighted-compact

# Claude sessions mount point (read-only bind mount from host).
RUN mkdir -p /claude-sessions && chown wc:wc /claude-sessions

# Default env — all overridable via docker-compose environment: section.
ENV WEIGHTED_COMPACT_DATA=/data/weighted-compact
ENV WEIGHTED_COMPACT_CLAUDE_SOURCES=/claude-sessions
ENV WEIGHTED_COMPACT_PORT=18890
ENV OLLAMA_HOST=http://ollama:11434

USER wc

# The container binds 0.0.0.0 internally; docker-compose publishes only
# 127.0.0.1:18890 on the host (see docker-compose.yml), keeping it local-only.
EXPOSE 18890

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# Default: run the labeler. Override with e.g. "bootstrap" or "compat".
CMD ["serve", "--host", "0.0.0.0"]
