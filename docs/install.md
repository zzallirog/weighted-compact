# Install

A practical reference covering: what the install actually puts on your
machine, which platforms are supported and which aren't, what runs after
install, what fails and where it logs.

## Supported platforms

| OS / Distro | Status | Notes |
|---|---|---|
| **Arch Linux** | ✅ first-class | CI matrix gate |
| **Ubuntu 22.04 / 24.04** | ✅ first-class | CI matrix gate |
| **Debian stable / testing** | ✅ first-class | CI matrix gate |
| **Fedora** | 🟡 expected to work | not CI-gated; report issues |
| **openSUSE Tumbleweed** | 🟡 expected to work | not CI-gated; report issues |
| **WSL2 (Ubuntu)** | 🟡 CLI works | systemd `--user` requires `systemd-genie` or similar |
| **macOS** | 🟡 CLI works | no systemd unit; run `weighted-compact serve` directly |
| **Windows (native)** | ❌ not supported | POSIX paths, fork-style FastAPI |
| **Alpine / musl** | ❌ unstable | sentence-transformers wheels need glibc; build from source if needed |
| **NixOS** | ✅ via `pip install` inside a venv | system Python tightly managed |
| **Proxmox VE base** | ✅ in LXC | needs `apt install python3-venv python3-pip` first |

## Supported hardware

| Component | Required | Recommended |
|---|---|---|
| CPU | x86_64 or ARM64 | 4+ cores for embedding extraction |
| RAM | 2 GB free | 8 GB if you train the classifier |
| Disk | 200 MB substrate per ~1000 session JSONLs | SSD strongly preferred |
| GPU | not required | optional CUDA / ROCm for classifier training (`torch` extra) |

The labeler and recon-QA loop are CPU-only. The classifier trainer
(`weighted-compact train`) accelerates ~5× on a single GPU but works fine
on CPU.

## What gets installed

### Path A — pipx (recommended)

```bash
pipx install git+https://github.com/zzallirog/weighted-compact
```

Creates an isolated venv at `~/.local/share/pipx/venvs/weighted-compact/`
containing:

- `weighted-compact` itself
- Hard deps: `fastapi`, `uvicorn[standard]`, `pydantic`, `numpy`, `click`
- Symlink `~/.local/bin/weighted-compact` → the entry point

Total install size: **~85 MB** (mostly numpy + uvicorn[standard]).

Nothing else is touched. No system files, no service registered, no
substrate created. The substrate dir under
`$XDG_DATA_HOME/weighted-compact/` is created lazily on first `bootstrap`.

### Path B — pip --user

```bash
pip install --user --break-system-packages git+https://github.com/zzallirog/weighted-compact
```

Same packages, installed under `~/.local/lib/python3.X/site-packages/`.
Smaller footprint (no separate venv), but shares site-packages with other
`pip --user` installs — be mindful of conflicts.

### Path C — development checkout

```bash
git clone https://github.com/zzallirog/weighted-compact
cd weighted-compact
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,ml]'
scripts/install-hooks.sh   # leak-scan pre-commit guard
```

With the `dev` extra: `pytest`, `ruff`.
With the `ml` extra: `scikit-learn`, `sentence-transformers` (and its
pytorch dependency — ~2 GB).

### Optional: systemd user unit

```bash
weighted-compact install-units
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact
```

Writes one file:

```
~/.config/systemd/user/weighted-compact.service
```

Marks the service for autostart at user login. Hardware actuators are
**not** part of weighted-compact — it never writes to `/sys`, never asks
for sudo, and the systemd unit has `ProtectSystem=full` plus
`NoNewPrivileges=yes`.

## What runs after install

Right after install, three things are true:

1. **`weighted-compact compat` works.** Read-only diagnostic; safe to run
   anywhere; never modifies state. Returns JSON with `--json`.
2. **No daemon is running.** Nothing listens on `:18890` until you run
   `weighted-compact serve` or enable the systemd unit.
3. **No files have been written under `~/.local/share/weighted-compact/`** —
   the substrate dir is created on first `bootstrap`.

## First-run walkthrough

```bash
# 1. Verify the install
weighted-compact compat
# Expect: ✓ for hard deps, your distro detected, ports free.

# 2. Build the substrate from your Claude Code sessions
weighted-compact bootstrap
# Reads ~/.claude/projects/*/*.jsonl (one subdir per CWD slug, one jsonl
# per session). Read-only on the Claude side.
# Writes ~/.local/share/weighted-compact/pairs.jsonl.

# 3. Launch the labeler
weighted-compact serve
# Open http://127.0.0.1:18890/ in a browser.

# 4. Label 20-50 pairs. Walk away. Come back when you want.
```

## Requirements drilldown

### Python version

- **3.11 minimum.** We use PEP 604 union syntax (`int | None`) and
  `platform.freedesktop_os_release()` (added in 3.10, but 3.10 has other
  rough edges).
- **3.12 and 3.13 are CI-tested.**
- **3.14 may segfault** when `sentence-transformers` loads on systems
  where torch wheels lag. Use 3.12 or 3.13 if you hit this.

### System packages (Debian/Ubuntu)

```bash
sudo apt install python3 python3-pip python3-venv git
```

That's all that is needed. No compilation, no system libraries beyond
glibc. `sentence-transformers` ships pre-built wheels for x86_64 + ARM64
Linux.

### System packages (Arch)

```bash
sudo pacman -S python python-pip git
```

`pipx` is in the official repos: `sudo pacman -S python-pipx`.

### System packages (Fedora)

```bash
sudo dnf install python3 python3-pip git
```

## Exception cases — what fails and where it logs

| Symptom | Cause | Fix |
|---|---|---|
| `weighted-compact: command not found` | `~/.local/bin` not on `$PATH` | Add `export PATH="$HOME/.local/bin:$PATH"` to your shell rc |
| `bootstrap` returns 0 pairs | No Claude Code sessions on this host, or they live in non-default location | `WEIGHTED_COMPACT_CLAUDE_SOURCES=/path/to/sessions weighted-compact bootstrap` |
| `serve` exits with `[Errno 98] Address already in use` | Port 18890 occupied | `WEIGHTED_COMPACT_PORT=18891 weighted-compact serve` |
| `compat` shows `numpy` missing | Install used wrong Python | Verify with `which python3 && which weighted-compact` — same prefix? |
| `recon_qa.eval` returns `Connection refused: localhost:11434` | Ollama not running | `systemctl --user enable --now ollama` (or skip recon-QA, it's optional) |
| Labels UI shows `loading...` forever | Substrate not bootstrapped | Run `weighted-compact bootstrap` first |
| `git config dubious ownership` inside CI container | UID mismatch between runner and container | Add `safe.directory` step (the bundled `.github/workflows/test.yml` does this) |
| Pre-commit hook blocks commit with "personal pattern matched" | A staged file contains a flagged identifier — by design | Inspect the diff; either remove the leak or extend `scripts/leak-scan.sh:PERSONAL_PATTERNS` |
| `weighted-compact bootstrap` fails with `PermissionError` on `~/.claude/projects/` | Claude Code session files owned by another UID | Run as the user that owns the sessions |

## Logging

| Component | Where it logs | Level control |
|---|---|---|
| CLI (`weighted-compact ...`) | stderr via stdlib `logging` | `-v` / `--verbose` flag → DEBUG |
| Labeler (`weighted-compact serve`) | stderr via stdlib `logging` + uvicorn access log | `WEIGHTED_COMPACT_LOG_LEVEL=DEBUG` env (planned v0.1) |
| systemd user unit | `journalctl --user -u weighted-compact -f` | unit's stdout/stderr captured |
| Bootstrap journal | `$XDG_STATE_HOME/weighted-compact/bootstrap.log` | append-only, one record per run |
| Test failures | pytest stdout + `.pytest_cache/lastfailed` | `-v` for verbose |

All logs stay on the local host. There is no remote log shipping, no
crash reporter, no usage analytics.

## Uninstall

### pipx

```bash
pipx uninstall weighted-compact
```

Removes the venv and the `~/.local/bin/weighted-compact` symlink.

### pip --user

```bash
pip uninstall weighted-compact
```

### Substrate cleanup (optional, **destructive** — your labels go too)

```bash
rm -rf ~/.local/share/weighted-compact/
rm -rf ~/.local/state/weighted-compact/
rm -f  ~/.config/systemd/user/weighted-compact.service
systemctl --user daemon-reload
```

The substrate dir contains your labels, your inline annotations, your
trained classifier weights. **Once deleted, they cannot be reconstructed
from any other source.** weighted-compact never uploads them anywhere.

## Verifying a clean install

```bash
# 1. The binary is on $PATH
command -v weighted-compact

# 2. Compat shows green
weighted-compact compat

# 3. Tests pass (development install only)
pytest -q

# 4. Leak-scan is clean (development install only)
bash scripts/leak-scan.sh
```

If all four succeed, the install is healthy. The next step is `bootstrap`.
