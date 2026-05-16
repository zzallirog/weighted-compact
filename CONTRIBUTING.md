# Contributing to weighted-compact

Short-scope PRs welcome. weighted-compact is intentionally a single-user
workbench; it says no to features that pull it toward multi-tenant SaaS.

## What this project accepts readily

- **Bug fixes** in the framework code (anything under `weighted_compact/`).
- **Documentation** — typos, missing files, broken links, better examples.
- **Test additions** for existing modules, using synthetic fixtures.
- **Distro support** — make the bootstrap or installer detect a new package
  manager / Python layout. CI matrix additions welcome.
- **Language-pattern contributions** to `extract_pairs.py` — the marker
  regex set currently covers RU/EN/UK; PRs for other languages welcome.
- **Importance-mixture variants** as **optional** weight presets — never
  changes to the default mixture without an issue first.

## What needs design discussion first (open an issue)

- New top-level config key.
- Anything that changes the on-disk substrate schema (jsonl line shape,
  npz array layout). Substrate is forward-compatible; breaking it
  invalidates everyone's labels.
- Anything that pulls weighted-compact toward server-mode, multi-user,
  or shared-substrate operation. These are not bugs; they are explicit
  non-goals. See [`docs/invariants.md`](docs/invariants.md).
- New classifier architecture. The vector-first invariant means classifiers
  are interchangeable refinement layers, but the contract they implement
  needs to be stable.

## What this project does NOT accept

- **PRs containing labeled data, conversation excerpts, or substrate
  artifacts** — `*.jsonl`, `*.npz`, `*.model`. Every install grows its
  own substrate. Sharing trained weights or labeled pairs would leak the
  contributor's conversation history into the public repo and is rejected
  on sight. `.gitignore` and a pre-commit hook catch most of these
  automatically.
- **Features that require an external API key** (OpenAI, Anthropic,
  Tencent Cloud, etc.). The substrate is local-first and stays that way.
- **Telemetry, "anonymous usage stats," update checkers** — nothing
  phones home, ever.

## Development setup

```bash
git clone https://github.com/zzallirog/weighted-compact
cd weighted-compact
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ml]'
pytest
```

The pre-commit hook scans the staged diff for substrate filename patterns
and known leak markers. Install it once:

```bash
scripts/install-hooks.sh
```

## Filing issues

Include `weighted-compact compat --json` in any bug report that involves
the substrate pipeline. It captures distro, Python version, detected
Claude Code session count, and missing optional dependencies — usually
enough to triage without back-and-forth.

For UI bugs, a screen recording of the labeler is worth a hundred words.
For pipeline bugs, the bootstrap log under
`$XDG_STATE_HOME/weighted-compact/bootstrap.log` is the right artifact.

## Support expectations

There is no SLA. The maintainer is one person, working part-time, and
the repo will go quiet for weeks. Patches that come with tests and a
clear motivation merge fastest.
