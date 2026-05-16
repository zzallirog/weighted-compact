"""weighted-compact command-line entry point.

Subcommands:
    bootstrap        Extract pairs from ~/.claude/projects/ into the substrate.
    serve            Run the labeler at http://127.0.0.1:18890/.
    compat           Read-only diagnostic. Print what was detected; --json for machine output.
    install-units    Write the systemd user unit under ~/.config/systemd/user/.
    train            Fit the classifier on the current substrate.
    eval             Run the reconstruction-QA gate against current labels.
    importance       Recompose the six-signal importance mixture.
    paths            Print substrate paths for sourcing in shell scripts.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any

import click

from weighted_compact import __version__, config


def _resolve_distro() -> str:
    """Return /etc/os-release ID (e.g. 'arch', 'debian') or 'unknown'."""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def _has_module(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _count_sessions() -> dict[str, int]:
    counts: dict[str, int] = {}
    for src in config.claude_source_dirs():
        if not src.exists():
            counts[str(src)] = -1
            continue
        n = 0
        for project_dir in src.iterdir():
            if not project_dir.is_dir():
                continue
            n += sum(1 for _ in project_dir.glob("*.jsonl"))
        counts[str(src)] = n
    return counts


def _substrate_state() -> dict[str, Any]:
    wd = config.workdir()
    state: dict[str, Any] = {"path": str(wd), "exists": wd.exists()}
    if not wd.exists():
        return state
    state["pairs"] = config.pairs_path().exists() and config.pairs_path().stat().st_size or 0
    state["labels"] = config.labels_path().exists() and config.labels_path().stat().st_size or 0
    state["features"] = config.features_path().exists()
    state["classifier"] = config.classifier_path().exists()
    return state


def _compat_report() -> dict[str, Any]:
    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.system(),
        "distro": _resolve_distro(),
        "deps": {
            "fastapi": _has_module("fastapi"),
            "uvicorn": _has_module("uvicorn"),
            "numpy": _has_module("numpy"),
            "click": _has_module("click"),
            "sentence_transformers": _has_module("sentence_transformers"),
            "sklearn": _has_module("sklearn"),
            "torch": _has_module("torch"),
            "requests": _has_module("requests"),
        },
        "substrate": _substrate_state(),
        "sessions": _count_sessions(),
        "port_free": _port_free(config.labeler_port()),
        "port": config.labeler_port(),
    }


@click.group()
@click.version_option(version=__version__, prog_name="weighted-compact")
def main() -> None:
    """weighted-compact — trainable context-compaction substrate."""


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def compat(as_json: bool) -> None:
    """Read-only diagnostic — what was detected, what is missing."""
    report = _compat_report()
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return

    click.echo(f"weighted-compact {report['version']} on {report['platform']} ({report['distro']}), Python {report['python']}")
    click.echo()
    click.echo("Dependencies:")
    for name, present in report["deps"].items():
        mark = "✓" if present else "·"
        kind = "" if name in ("fastapi", "uvicorn", "numpy", "click") else " (optional)"
        click.echo(f"  {mark} {name}{kind}")
    click.echo()
    sub = report["substrate"]
    click.echo(f"Substrate: {sub['path']}")
    if not sub["exists"]:
        click.echo("  · not created yet — run `weighted-compact bootstrap`")
    else:
        click.echo(f"  · pairs.jsonl   {sub.get('pairs', 0)} bytes")
        click.echo(f"  · labels.jsonl  {sub.get('labels', 0)} bytes")
        click.echo(f"  · features.npz  {'present' if sub.get('features') else 'absent'}")
        click.echo(f"  · classifier    {'trained' if sub.get('classifier') else 'untrained'}")
    click.echo()
    click.echo("Claude Code sessions:")
    for path, count in report["sessions"].items():
        if count < 0:
            click.echo(f"  · {path} (not present)")
        else:
            click.echo(f"  · {path} — {count} session files")
    click.echo()
    state = "free" if report["port_free"] else "in use"
    click.echo(f"Labeler port {report['port']}: {state}")


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be extracted without writing.")
def bootstrap(dry_run: bool) -> None:
    """Extract conversation pairs from ~/.claude/projects/ into the substrate."""
    from weighted_compact import extract_pairs as ep

    config.workdir().mkdir(parents=True, exist_ok=True)
    config.state_dir().mkdir(parents=True, exist_ok=True)

    if dry_run:
        click.echo(f"Would scan: {ep.DIRS}")
        click.echo(f"Would write: {ep.OUT}")
        return

    if not hasattr(ep, "main"):
        click.echo("ERROR: extract_pairs.py does not expose main() — call its functions directly.")
        sys.exit(1)
    ep.main()
    click.echo(f"Wrote pairs to {ep.OUT}")


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", type=int, default=None, help="Override port (default: $WEIGHTED_COMPACT_PORT or 18890).")
def serve(host: str, port: int | None) -> None:
    """Launch the labeler UI at http://HOST:PORT/."""
    import uvicorn

    from weighted_compact import tool

    config.workdir().mkdir(parents=True, exist_ok=True)
    p = port or config.labeler_port()
    click.echo(f"weighted-compact labeler → http://{host}:{p}/")
    uvicorn.run(tool.app, host=host, port=p, log_level="info")


@main.command()
def importance() -> None:
    """Recompose the six-signal importance mixture."""
    from weighted_compact import importance as imp

    if hasattr(imp, "main"):
        imp.main()
    else:
        click.echo("ERROR: importance.py does not expose main()")
        sys.exit(1)


@main.command()
def train() -> None:
    """Fit the classifier on the current substrate."""
    from weighted_compact import train as tr

    if hasattr(tr, "main"):
        tr.main()
    else:
        click.echo("ERROR: train.py does not expose main()")
        sys.exit(1)


@main.command(name="eval")
def eval_cmd() -> None:
    """Run the reconstruction-QA gate."""
    from weighted_compact import eval as ev

    if hasattr(ev, "main"):
        ev.main()
    else:
        click.echo("ERROR: eval.py does not expose main()")
        sys.exit(1)


@main.command()
def paths() -> None:
    """Print substrate paths in shell-sourceable form."""
    click.echo(f"WEIGHTED_COMPACT_DATA={config.workdir()}")
    click.echo(f"WEIGHTED_COMPACT_STATE={config.state_dir()}")
    click.echo(f"WEIGHTED_COMPACT_PORT={config.labeler_port()}")


@main.command(name="install-units")
@click.option("--force", is_flag=True, help="Overwrite existing unit files.")
def install_units(force: bool) -> None:
    """Write the systemd user unit under ~/.config/systemd/user/."""
    here = Path(__file__).resolve().parent
    src = here.parent / "systemd" / "weighted-compact.service"
    if not src.exists():
        # Fall back to a built-in template when installed from a wheel.
        src = here / "data" / "weighted-compact.service"
    if not src.exists():
        click.echo("ERROR: weighted-compact.service template not found.")
        sys.exit(1)

    dest_dir = Path.home() / ".config" / "systemd" / "user"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "weighted-compact.service"
    if dest.exists() and not force:
        click.echo(f"{dest} already exists — pass --force to overwrite.")
        sys.exit(1)
    dest.write_text(src.read_text())
    click.echo(f"Wrote {dest}")
    click.echo()
    click.echo("Next:")
    click.echo("  systemctl --user daemon-reload")
    click.echo("  systemctl --user enable --now weighted-compact")
    click.echo(f"  xdg-open http://127.0.0.1:{config.labeler_port()}/")


if __name__ == "__main__":
    main()
