# MCP integration: local-only stdio server over the substrate

weighted-compact ships an optional Model Context Protocol (MCP) server
that exposes three read-only substrate operations to any MCP-speaking
client — Claude Desktop, mcp-cli, IDE plugins. The server speaks stdio
only and runs entirely on the host. There is no network listener, no
auto-injection, no labeling, no write path: the client decides when to
call.

If you want a quick read of why this is shaped the way it is, the short
version is at the bottom of this file ("What it is, what it isn't"). The
rest of this document is the practical install + integration.

## What it is, what it isn't

- **Is**: a query surface over an already-built substrate. The same
  `pairs.jsonl`, `importance.npz`, `rem_decay.npz` you build with
  `bootstrap` / `importance` / `rem-pass`. Read-only.
- **Is**: stdio transport. Spawned as a subprocess by the client. Dies
  when the client disconnects. Nothing listens on a port.
- **Isn't**: a writer. There is no `label_pair`, no `annotate_span`, no
  `trigger_rem_pass`. Labeling stays in the localhost FastAPI labeler
  (`weighted-compact serve`) where the CAPTCHA-style UI lives.
- **Isn't**: an auto-injector. The model on the other side polls when it
  wants; nothing in this server initiates context delivery.
- **Isn't**: a network server. No HTTP, no SSE, no WebSocket. If someone
  wants remote access, they can fork — the local-only framing is the
  whole point.

## Install

The `mcp` Python SDK is an *optional* extra so the base install stays
slim for the labeler / eval crowd that doesn't speak MCP.

```sh
pipx install 'weighted-compact[mcp]'
# or, inside a venv:
pip install 'weighted-compact[mcp]'
```

If you forget the extra, `weighted-compact mcp-serve` fails with a clear
install instruction rather than crashing on import.

## Run

```sh
weighted-compact mcp-serve
```

The process reads MCP framing from stdin and writes responses to stdout.
Logs (if any) go to stderr. Ctrl-C exits cleanly.

You normally don't run this by hand — your MCP client spawns it as a
subprocess and pipes the stdio. The bare invocation is useful only for
smoke-testing the install.

## Tools

The server registers exactly three tools. Tool descriptions below are
the docstrings the MCP client sees on `tools/list`.

### `search_pairs(query: str, top_k: int = 10)`

> Cosine-search the substrate's correction-text embeddings.
>
> Returns the top-K most-similar pairs to `query`, each as a dict
> with pair_idx, session_id, premise_preview (≤200 chars),
> correction_preview (≤200 chars), and cosine score in [-1, 1].
>
> Requires `features.npz` (built by `weighted-compact bootstrap --full`)
> and the [baselines] extra (sentence-transformers). On the first
> call the e5-multilingual-small model is loaded into memory and
> cached for subsequent calls.
>
> On missing substrate or import error returns a single dict with
> an `error` key rather than raising — the stdio loop must not die
> on a misconfigured client.

### `compact_session(source_pair_idx: int, k_drop: float = 0.5, ranker: str = "importance", rem_decay: bool = False)`

> Assemble a compacted-markdown view of the source pair's session.
>
> Hides the source pair (so it can be used as ground truth in
> reconstruction-QA) and returns the remaining session pairs
> ranked by the chosen scoring source, truncated to keep
> `(1 - k_drop)` of the session.
>
> Args:
>     source_pair_idx: index into pairs.jsonl identifying the
>         pair whose session should be compacted. The pair itself
>         is hidden from the output.
>     k_drop: fraction of session pairs to drop (0.0 = keep all,
>         0.9 = aggressive compaction).
>     ranker: scoring source. Currently only "importance" is
>         supported here (query-aware rankers belong in
>         search_pairs).
>     rem_decay: if True, multiply scores by the nightly REM-decay
>         map (requires `weighted-compact rem-pass` to have run).
>
> Returns a dict with `markdown` (the compacted context, ready to
> paste into a prompt) and `meta` (budget-transparency: pairs_total,
> pairs_kept, input_chars, output_chars, tokens_estimate,
> compaction_ratio, signals_top3, ranker label).
>
> On invalid input or missing substrate returns a dict with an
> `error` key rather than raising.

### `substrate_info()`

> Report what's built and what isn't — cheap diagnostic.
>
> Returns a dict with pair_count, session_count, has_importance,
> has_rem_decay, rem_decay_ref_iso (ISO timestamp of the last
> REM pass), and signals_present (names of the importance mixture
> components). Includes path of the substrate workdir.
>
> Use this on connect to know which other tools will succeed
> without paying their setup cost first. Always returns a dict
> even when nothing is built.

## Claude Desktop config snippet

Wire the server into `claude_desktop_config.json` (on Linux that's
`~/.config/Claude/claude_desktop_config.json`; on macOS it's
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "weighted-compact": {
      "command": "weighted-compact",
      "args": ["mcp-serve"]
    }
  }
}
```

If `weighted-compact` is installed via `pipx` and your shell sees it on
`PATH`, the above is enough. Otherwise spell out the absolute path:

```json
{
  "mcpServers": {
    "weighted-compact": {
      "command": "/home/you/.local/bin/weighted-compact",
      "args": ["mcp-serve"]
    }
  }
}
```

After editing, restart Claude Desktop. The three tools appear in the
tools picker; call `substrate_info` first to confirm the connection.

## Why no HTTP/SSE/WebSocket

This server is intentionally local-only. The substrate carries raw
conversation text from your own `~/.claude/projects/` — it is not
something you want sitting on a port. Stdio means the client and the
server share a process boundary, the OS does the lifecycle, and there is
no authentication surface to get wrong.

If you want a remote MCP endpoint, fork the module and add an SSE / HTTP
transport behind your own auth layer. That's a separate concern and a
separate PR.

## Substrate behaviour when things are missing

Each tool degrades cleanly:

| Missing artefact      | `search_pairs`            | `compact_session`         | `substrate_info` |
|-----------------------|---------------------------|---------------------------|------------------|
| `pairs.jsonl`         | `error: substrate_not_built` | `error: substrate_not_built` | counts 0, flags false |
| `features.npz`        | `error: substrate_not_built` | works                     | flag false       |
| `importance.npz`      | works                     | `error: substrate_not_built` | flag false       |
| `rem_decay.npz`       | works                     | works (without REM); errors only if `rem_decay=True` requested | flag false, `rem_decay_ref_iso` null |
| `mcp` SDK not installed | n/a (CLI never starts)  | n/a                       | n/a              |

Errors are returned as JSON payloads with an `error` key and a `hint`
field where useful. The stdio loop never dies on a missing artefact —
the client can call `substrate_info` to recover and act accordingly.

## Open questions

- **Date-range filter on `search_pairs`?** Currently no. The cosine
  ranker scores against all indexed pairs and lets the client pick from
  the top-K. If "search only within the last 7 days" turns out to be a
  common ask, the natural shape is an optional `since: str` (ISO date)
  argument that intersects with the REM-decay session timestamps before
  the cosine pass. Filed as an open question, not implemented.

## Related

- `docs/integrations/cursor.md` — Cursor `mcp.json` setup and smoke-test flow
- `docs/01-substrate.md` — what's in `pairs.jsonl` / `features.npz`
- `docs/rem-decay.md` — the REM-decay multiplier this server respects
- `docs/claude-code-integration.md` — how the substrate is built from
  `~/.claude/projects/` in the first place
