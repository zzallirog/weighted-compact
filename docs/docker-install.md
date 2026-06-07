# Docker install guide

## Why Docker

weighted-compact requires Python 3.11+, a handful of pip packages, and a
running Ollama instance for the eval harness. Setting all of that up by hand
on Windows involves multiple installers, PATH edits, and virtualenv
housekeeping. Docker Desktop gives Windows users a single install that runs
the full stack in an isolated environment with no interference to their system
Python. macOS and Linux users get the same reproducible environment and the
same privacy guarantees.

Nothing in the container ever writes back to your Claude sessions directory.
The substrate (the processed output) lives in a named Docker volume on your
machine and never leaves it.

---

## Prerequisites

| Platform | Requirement |
|---|---|
| Windows 10/11 | [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/) 4.x+ (WSL 2 backend) |
| macOS | [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/) 4.x+ |
| Linux | docker-compose v2 plugin (`docker compose` not `docker-compose`) |

**Disk space estimate:**

- weighted-compact image: ~200 MB
- Ollama image: ~1 GB
- Ollama models: ~3 GB (gemma3:4b) + ~5 GB (qwen2.5:7b) = ~8 GB first pull
- Substrate volume: depends on your session count, typically 10–200 MB

Make sure Docker Desktop has access to at least 12 GB of disk before pulling
models.

---

## First-time setup — three commands

```bash
# 1. Clone the repo (skip if you already have it)
git clone https://github.com/zzallirog/weighted-compact
cd weighted-compact

# 2. Pull the upstream images (ollama/ollama, python:3.11-slim)
docker compose pull

# 3. Run bootstrap --full — reads your Claude sessions, builds the full substrate
docker compose run --rm weighted-compact bootstrap --full
```

Bootstrap (`--full`) scans `/claude-sessions` (mounted read-only from your
`~/.claude/projects/`) and writes `pairs.jsonl` plus the full signal chain
(features → density → spans → topic → `importance.npz`) to the
`wc-substrate` named volume. It is safe to re-run; it does not overwrite
existing labels.

After bootstrap, start the labeler:

```bash
docker compose up -d weighted-compact
```

Open `http://127.0.0.1:18890/` in your browser.

---

## Pulling Ollama models

The Ollama sidecar starts without any models. Pull them once — they are stored
in the `ollama-models` named volume and survive container restarts.

```bash
# Start the ollama sidecar if it is not already running
docker compose up -d ollama

# Pull the judge model — used by the eval harness and schema extractor
docker compose exec ollama ollama pull gemma3:4b   # ~3 GB download

# Pull the narrative model — used by the Drift Inspector iter chain
docker compose exec ollama ollama pull qwen2.5:7b  # ~5 GB download
```

These commands stream progress to your terminal. The first pull takes a few
minutes on a typical broadband connection. Subsequent starts are instant.

---

## Bind-mount paths per platform

The compose file mounts your Claude sessions directory read-only so the
container can scan session transcripts during `bootstrap` and `rem-pass`.

### Linux

The default in `docker-compose.yml` works without changes:

```yaml
volumes:
  - ~/.claude/projects:/claude-sessions:ro
```

### macOS

Same as Linux — the `~` tilde is expanded by the compose file. Docker
Desktop for macOS will ask you to grant file-sharing access to your home
directory the first time. Accept the prompt.

### Windows — PowerShell syntax

Windows paths use backslashes and a drive letter, which Docker cannot use
directly. Use the `CLAUDE_SESSIONS_PATH` environment variable to pass the
path in POSIX form, or edit `docker-compose.yml` directly.

**Option A — set an env var before running compose (PowerShell):**

The equivalent of `~/.claude/projects` on Windows is
`%USERPROFILE%\.claude\projects` (cmd.exe) or
`$env:USERPROFILE\.claude\projects` (PowerShell).

```powershell
$env:CLAUDE_SESSIONS_PATH = "$env:USERPROFILE\.claude\projects" -replace '\\', '/'
docker compose up -d weighted-compact
```

**Option B — edit `docker-compose.yml` directly:**

Replace the bind-mount line in the `weighted-compact` service:

```yaml
volumes:
  - wc-substrate:/data/weighted-compact
  # Replace the line below with the Windows path to your Claude projects folder:
  - C:/Users/YourName/.claude/projects:/claude-sessions:ro
```

Use forward slashes, not backslashes. Docker Desktop on Windows accepts both,
but YAML strings with backslashes need quoting and are error-prone.

**Docker Desktop file-sharing prompt:**

On Windows, Docker Desktop will show a dialog asking permission to share the
drive the first time a bind mount touches it. Click "Share it" and check
"Don't ask again for this path" to avoid repeat prompts.

---

## REM nightly pass in Docker

The `weighted-compact rem-pass` command recomputes the wall-clock importance
decay (`rem_decay.npz`) and is designed to run once a day, around 04:00.
Two options:

### Option A — sleep-loop container (simplest, Docker-only)

Uncomment the `weighted-compact-rem` service block at the bottom of
`docker-compose.yml`, then:

```bash
docker compose up -d weighted-compact-rem
```

The container's entrypoint recognises the special command `rem-loop`:
it sleeps until 04:00 UTC, runs `rem-pass`, and repeats every 24 hours.
The multiplier is written to the shared `wc-substrate` volume and is
immediately available to the labeler.

**Pros:** self-contained, no host scheduler required, restarts automatically.  
**Cons:** a container runs around the clock for a job that takes ~5 seconds.
UTC 04:00 is fixed — if you want a different timezone adjust the sleep
arithmetic in `docker-entrypoint.sh`.

### Option B — host cron / Task Scheduler (minimal footprint)

**Linux / macOS cron:**

```bash
crontab -e
# Add:
0 4 * * * docker compose -f /path/to/weighted-compact/docker-compose.yml run --rm weighted-compact rem-pass
```

**Windows Task Scheduler (PowerShell):**

```powershell
$action = New-ScheduledTaskAction -Execute "docker" `
    -Argument "compose -f C:\path\to\weighted-compact\docker-compose.yml run --rm weighted-compact rem-pass"
$trigger = New-ScheduledTaskTrigger -Daily -At 4am
Register-ScheduledTask -TaskName "WC-RemPass" -Action $action -Trigger $trigger -RunLevel Highest
```

**Pros:** zero overhead between runs, respects local time.  
**Cons:** requires a host scheduler; Docker must be running at 04:00.

---

## Labeler access

Open `http://127.0.0.1:18890/` after `docker compose up -d weighted-compact`.

> **Note:** the labeler is opt-in, not mandatory. The weighted-compact
> pipeline builds and recomposes the importance mixture without any manual
> labels — the labeler accelerates convergence but is not required for the
> substrate to work. See the README for the opt-in framing.

The port is bound to `127.0.0.1` (loopback only). It is not reachable from
other machines on your network. Do not change the port binding to
`0.0.0.0` unless you understand the security implications — the labeler
contains raw conversation text from your Claude sessions.

---

## Disabling the ollama sidecar

If you already run Ollama on the host (e.g. via `systemd` or a standalone
install), you do not need the sidecar. Two steps:

1. In `docker-compose.yml`, comment out the entire `ollama` service block and
   the `ollama-models` volume.

2. In the `weighted-compact` service `environment` section, change:

   ```yaml
   OLLAMA_HOST: http://ollama:11434
   ```

   to:

   ```yaml
   OLLAMA_HOST: http://host.docker.internal:11434
   ```

   `host.docker.internal` resolves to the host machine from inside a Docker
   container on Windows, macOS, and Linux (Docker Desktop). On Linux with a
   plain Docker Engine install you may need to add
   `--add-host=host.docker.internal:host-gateway` or use the host's actual IP.

Also remove the `depends_on: ollama` stanza from the `weighted-compact` service.

---

## Reset / uninstall

**Stop all containers:**

```bash
docker compose down
```

This stops and removes containers but keeps the substrate volume and model
cache intact.

**Remove the substrate (data loss — irreversible):**

```bash
docker compose down -v
```

> Warning: `-v` removes all named volumes including `wc-substrate`. Your
> labels, annotations, and importance signals are gone. Run this only if you
> want a clean start or are uninstalling completely.

**Remove images:**

```bash
docker rmi weighted-compact:latest ollama/ollama:latest
```

---

## Common gotchas

### SELinux on Fedora / RHEL / CentOS

SELinux blocks bind mounts by default. Add the `:z` relabeling flag to the
Claude sessions volume:

```yaml
volumes:
  - ~/.claude/projects:/claude-sessions:ro,z
```

The `:z` flag lets the container access the files without disabling SELinux.
Use `:Z` (capital Z) if the mount is exclusive to this container.

### Docker Desktop file-sharing prompts on Windows

Docker Desktop manages a whitelist of shared paths. If you get a "drive not
shared" error, open Docker Desktop → Settings → Resources → File Sharing and
add the folder containing your Claude projects (typically
`C:\Users\YourName\.claude`).

### GPU passthrough for ollama

The ollama sidecar runs on CPU by default (~3–15 tokens/s depending on the
model and your machine). To enable GPU acceleration uncomment the `deploy`
block in the `ollama` service and ensure you have the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
installed:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

AMD GPU passthrough with ROCm requires a different image tag
(`ollama/ollama:rocm`) and the ROCm drivers on the host.

### "substrate not found" on first start

The labeler will not start if `bootstrap` has not been run. You will see:

```
ERROR: substrate not found at /data/weighted-compact/pairs.jsonl
Run bootstrap first:
  docker compose run --rm weighted-compact bootstrap
```

Run the bootstrap command and restart the labeler. This is intentional — the
labeler has nothing to show without a substrate.

### Checking if the labeler is alive

```bash
curl http://127.0.0.1:18890/api/progress
```

Returns a JSON object with pair count and queue state. If the connection
refuses, check `docker compose logs weighted-compact`.
