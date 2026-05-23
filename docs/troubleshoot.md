# Troubleshooting — weighted-compact runtime

**First thing to run** when something feels wrong:

```bash
weighted-compact compat          # human-readable: deps, substrate, sessions, port
weighted-compact compat --json   # machine-readable: pipe to jq or grep
weighted-compact metrics         # footprint + REM-pass freshness + loader timings
```

These two commands cover ~80 % of diagnosis without touching the substrate files.
The table below maps the remaining symptoms to their cause and fix.

---

## Diagnostic flow

1. Run `weighted-compact compat`. If the substrate path shows `not created yet`, go to row 3.
2. Check `rem-pass: never run` in `weighted-compact metrics` output. If so, run `weighted-compact rem-pass`.
3. If `weighted-compact qa-gate` or `eval` fails immediately (before any LLM calls), the preflight check caught it — the error message contains the fix directive verbatim.
4. If fidelity numbers are 0 % or unchanged, check whether `importance.npz` is stale (row 4) or whether `qa-gate` exited with an empty qa_set (row 10).
5. If the labeler UI refuses to bind, check port 18890 (row 6).
6. For schema mismatch errors on `.npz` files, the error message tells you the rebuild command (row 7).

---

## Failure table

| # | Symptom | Likely cause | Fix command | Notes |
|---|---------|--------------|-------------|-------|
| 1 | `weighted-compact qa-gate` / `eval` exits immediately with `ollama is not reachable at http://localhost:11434 (…). Start it with: ollama serve` | Ollama daemon is not running | `ollama serve` | The preflight check fires once at the top of `run_eval`; bypass with `--no-preflight` only to reproduce the silent-judge-failure mode |
| 2 | Preflight exits with `MODEL='qwen2.5:7b' is not installed in ollama. Pull it with: ollama pull qwen2.5:7b` | Required model not pulled | `ollama pull qwen2.5:7b` (or the model named in the error) | The error names both `MODEL` and `JUDGE_MODEL` if either is missing; pull whichever is absent |
| 3 | `weighted-compact compat` shows `not created yet — run weighted-compact bootstrap`; MCP tools return `{"error": "substrate_not_built", …}` | Bootstrap has never been run on this machine | `weighted-compact bootstrap` | Creates `$WEIGHTED_COMPACT_DATA` (`~/.local/share/weighted-compact/` by default) and writes `pairs.jsonl` |
| 4 | Fidelity is 0 % or unchanged after new labels; `weighted-compact compat --json \| grep importance` shows `"features": false` | `importance.npz` is absent or was never rebuilt after relabeling | `weighted-compact importance` | Run after any labeling session; also re-run after `bootstrap` when the corpus grows |
| 5 | `weighted-compact metrics` shows `rem-pass: never run`; compaction ignores recency | `rem-pass` nightly timer not enabled or never run manually | `weighted-compact rem-pass` (manual) or `systemctl --user enable --now weighted-compact-rem-pass.timer` (recurring) | `rem_decay_ref_iso` in `metrics --json` shows the timestamp of the last run; a date older than 7 days means the decay factors are stale |
| 6 | `weighted-compact serve` exits with `[Errno 98] Address already in use` or compat shows `Labeler port 18890: in use` | Previous labeler instance still running (or another process on the port) | `lsof -i :18890` then `kill <PID>`, or `WEIGHTED_COMPACT_PORT=18891 weighted-compact serve` | Set `WEIGHTED_COMPACT_PORT` permanently in your shell profile to avoid conflicts |
| 7 | Any loader raises `RuntimeError: importance.npz: schema_ver N != current M. Rebuild with: weighted-compact importance` (or `rem-pass` / `weighted-compact baseline build --ranker <name>`) | `.npz` file was written by an older release; schema version bumped | Run the command shown verbatim in the error message | The `_check_schema_ver` guard fires for `importance.npz`, `rem_decay.npz`, and baseline `.npz` files; each error message names the exact rebuild command |
| 8 | `weighted-compact mcp-serve` exits with an ImportError and `Install the optional MCP extra: pipx install 'weighted-compact[mcp]'` | `mcp` extra not installed | `pipx install 'weighted-compact[mcp]'` or `pip install 'weighted-compact[mcp]'` inside a venv | Standard pipx installs omit the `[mcp]` extra; see `docs/mcp-integration.md` for the Claude Desktop config snippet |
| 9 | `bootstrap` completes but reports `Total pairs: 0` / `Sessions processed: 0` | Source dir is wrong or sessions are below the 5 KB minimum size filter | `weighted-compact compat` → check "Claude Code sessions" section; set `WEIGHTED_COMPACT_CLAUDE_SOURCES=/correct/path` and re-run `weighted-compact bootstrap` | Default source roots are `~/.claude/projects/` and `~/.claude-work/projects/`; override with the env var (colon-separated list of paths) |
| 10 | `weighted-compact qa-gate` exits with `total: 0 (easy_k=…)` and all bucket counts are 0 | `recon_qa_set.jsonl` is absent or empty — QA generation has never been run | `weighted-compact eval` to generate the QA set, or `weighted-compact qa-gate --write` after building the set | The QA set is built separately from the substrate; `load_qa_set()` returns `[]` when the file is missing, so `qa-gate` silently exits with zero rows |

---

## If none of these match

Run `weighted-compact compat --json` and share the output when filing an
issue — it captures version, Python, platform, all optional dependency
presence flags, substrate state, session counts, and port status in one
JSON blob.

File issues at: <https://github.com/zzallirog/weighted-compact/issues>

For substrate-path questions see `docs/install.md` §"Exception cases".
For QA-harness background see `docs/reconstruction-qa.md`.
