# Cursor MCP integration

Cursor can launch the local `weighted-compact mcp-serve` stdio server from an
`mcp.json` file. The server stays local-only: Cursor owns the subprocess,
communicates over stdio, and no HTTP/SSE port is opened.

## Prerequisites

Install the optional MCP extra before adding the config:

```sh
pipx install 'weighted-compact[mcp]'
# or, inside a virtualenv:
pip install 'weighted-compact[mcp]'
```

Build the substrate you want Cursor to query:

```sh
weighted-compact bootstrap
weighted-compact importance
```

`substrate_info` still works when nothing is built, but `search_pairs` and
`compact_session` need the substrate artefacts described in
[`../mcp-integration.md`](../mcp-integration.md).

## Choose project or global config

Cursor supports two `mcp.json` locations:

- Project-local: `.cursor/mcp.json` in the repository you are editing.
- Global: `~/.cursor/mcp.json` for tools available in every Cursor project.

Use project-local config when you want the tool only for a specific workbench;
use global config when your weighted-compact substrate is part of your normal
Cursor setup.

## Minimal config

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

After saving the file, reload Cursor or restart the MCP server from Cursor's
MCP settings. Call `substrate_info` first; it is cheap and confirms that Cursor
can spawn the process.

## Config with an absolute command path

If Cursor cannot resolve the same `PATH` as your shell, point `command` at the
installed executable:

```json
{
  "mcpServers": {
    "weighted-compact": {
      "command": "/Users/you/.local/bin/weighted-compact",
      "args": ["mcp-serve"]
    }
  }
}
```

For a virtualenv install, use that environment's executable path instead:

```json
{
  "mcpServers": {
    "weighted-compact": {
      "command": "/path/to/venv/bin/weighted-compact",
      "args": ["mcp-serve"]
    }
  }
}
```

## Smoke-test workflow

1. Save one of the configs above.
2. Reload Cursor's MCP servers.
3. Run `substrate_info` from Cursor's tool picker.
4. If `pair_count` is greater than zero, try `search_pairs` with a short query
   from your own Claude Code history.
5. Use `compact_session` only after `substrate_info` shows `has_importance: true`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Cursor shows the server as failed | Run `weighted-compact mcp-serve` in a terminal; missing `[mcp]` extra reports an install hint. |
| Cursor cannot find `weighted-compact` | Use the absolute-path config above. |
| Tools return `substrate_not_built` | Run `weighted-compact bootstrap` and `weighted-compact importance`, then reload the server. |
| Search is slow on first call | `search_pairs` loads the embedding model lazily; later calls reuse it in the same server process. |

## Privacy notes

The MCP server reads local substrate files that may contain raw conversation
text. Prefer project-local config for experiments and keep the server on stdio;
do not wrap it in a remote transport unless you add your own authentication and
explicitly accept that privacy trade-off.
