# Claude Code integration

weighted-compact reads its substrate from Claude Code session files on
disk. It does not call any API, does not modify your sessions, and does
not require Claude Code to be running.

## Where Claude Code keeps sessions

Claude Code persists session transcripts under two roots:

```
~/.claude/projects/<project-slug>/<session-uuid>.jsonl
~/.claude-work/projects/<project-slug>/<session-uuid>.jsonl
```

The `<project-slug>` is derived from the working directory of the Claude
Code session — typically `-home-<user>-foo-bar` for a session run in
`/home/<user>/foo/bar`. Every project gets its own subdir; every session
within a project gets its own JSONL.

Each JSONL is append-only, one event per line. Event shape is
documented [in Anthropic's docs](https://docs.anthropic.com/en/docs/claude-code)
under "session-files."

## What weighted-compact extracts

`extract_pairs.py` walks every subdir under each configured source root
(`~/.claude/projects/`, `~/.claude-work/projects/`) and processes each
JSONL. It builds **(premise, correction) pairs**:

- **`premise`** — an assistant turn that prompted a user correction.
- **`correction`** — the user turn that followed, expressing satisfaction
  (`keep`), neutral (`maybe`), or dissatisfaction (`skip`).

Pairs are detected by a regex over the user turn:

```python
RE_POS = re.compile(
    r"\b(exactly|that's it|that's right|perfect|great|nailed it|"
    r"nice|correct)\b", re.IGNORECASE)

RE_NEG = re.compile(
    r"\b(no|not that|not what|not right|not quite|wrong|incorrect|"
    r"stop|wait|hold on|nope|don't|revert|undo|again)\b",
    re.IGNORECASE)

RE_TAG = re.compile(
    r"\(([^)]*?(mark|think|neutral)[^)]*?)\)",
    re.IGNORECASE)
```

These patterns cover English correction and validation markers. The
patterns are intentionally narrow — they err on the side of missing
pairs rather than producing false positives, because a false positive
pollutes the substrate while a missed pair just means you label it
manually later.

### Adding other languages

The marker regex set lives in `weighted_compact/extract_pairs.py`. A PR
adding patterns for another language should:

1. Add patterns to `RE_POS` / `RE_NEG` / `RE_TAG`.
2. Add a fixture in `tests/test_extract_pairs.py` with a synthetic pair
   in the new language.
3. Update this doc with the language and the new patterns.

PRs that broaden existing patterns are not accepted — broader patterns
produce more false positives, which silently degrade the substrate. If
your language overlaps with English ("super" is positive in both, but
also a brand name in some contexts), keep the patterns separate per
language.

## What weighted-compact skips

```python
SKIP_PREFIXES = (
    "<command",
    "<local-command",
    "<bash-input",
    "<bash-stdout",
    "<bash-stderr",
    "<task-notification",
    "<system-reminder",
    "<user-prompt",
    "<image",
    "<attachment",
)
```

These are Claude Code's internal tool-output prefixes. They are not
conversational turns and have no labeling value. Skipping them
keeps the substrate signal/noise high and prevents the topic
segmentor from confusing tool floods with topic boundaries.

## How the bootstrap walks sessions

```python
# extract_pairs.py
from weighted_compact import config

DIRS = [str(p) for p in config.claude_source_dirs()]
OUT = str(config.pairs_path())
```

Default behavior:

- Read `$XDG_DATA_HOME/weighted-compact/pairs.jsonl` (or create it).
- Walk every subdir under each path in `DIRS`.
- For each JSONL above `MIN_FILE_SIZE` (5 KB), extract pairs.
- Append new pairs (incremental mode preserves existing `pair_idx`).

Override via environment:

```bash
WEIGHTED_COMPACT_DATA=/path/to/substrate          # where to write
WEIGHTED_COMPACT_CLAUDE_SOURCES=/path/a:/path/b   # where to read (colon-separated)
```

## Read-only guarantees

`extract_pairs.py` opens session files in read mode only. It never
modifies, deletes, or renames them. Claude Code can be running concurrently
without conflict — session files are append-only on Claude Code's side,
and `extract_pairs.py` re-reads them each run.

The output `pairs.jsonl` lives under `$XDG_DATA_HOME/weighted-compact/`,
not under `~/.claude/`. weighted-compact never writes anywhere under
`~/.claude/` or `~/.claude-work/`.

## What this is good for, what it isn't

**Good for:**
- Sessions where you correct the assistant frequently (the substrate
  signal is strongest at correction points).
- Long-running projects where you have ~30+ sessions of history.
- Multi-language workflows — RU/EN/UK are first-class; add more via PR.

**Not good for:**
- Single-session use. The CAPTCHA labeler needs ~50 labels before the
  classifier produces stable predictions; a fresh project doesn't have
  enough corpus.
- Mostly-bash sessions. If your conversations are dominated by tool
  output, the skip prefixes filter most of the substrate away.
- Sessions with no negative corrections. If you never push back, the
  `RE_NEG` regex never fires and the substrate is one-sided.

## Sanity check

```bash
weighted-compact compat
```

The output's "Claude Code sessions" section shows how many JSONL files
were detected per source root. If both show `0`, you either don't have
Claude Code installed, or your sessions live in non-default locations —
override with `WEIGHTED_COMPACT_CLAUDE_SOURCES`.
