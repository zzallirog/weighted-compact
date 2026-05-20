"""weighted-compact command-line entry point.

Subcommands:
    bootstrap        Extract pairs from ~/.claude/projects/ into the substrate.
    serve            Run the labeler at http://127.0.0.1:18890/.
    compat           Read-only diagnostic. Print what was detected; --json for machine output.
    install-units    Write the systemd user unit under ~/.config/systemd/user/.
    train            Fit the classifier on the current substrate.
    eval             Run the reconstruction-QA gate against current labels.
    qa-gate          Segment the recon-QA set by informativeness (admission gate).
    importance       Recompose the six-signal importance mixture.
    paths            Print substrate paths for sourcing in shell scripts.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import platform
import socket
from pathlib import Path
from typing import Any

import click

from weighted_compact import __version__, config

log = logging.getLogger("weighted_compact.cli")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _distro() -> str:
    """Return /etc/os-release ID via stdlib (Python 3.10+) — empty string on non-Linux."""
    try:
        return platform.freedesktop_os_release().get("ID", "unknown")
    except (OSError, AttributeError):
        return "unknown"


def _has_module(name: str) -> bool:
    """Check without importing — preserves cold-start latency.

    Importing torch / sentence_transformers / sklearn at compat time would
    add ~2.5s. find_spec resolves the package metadata without loading.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
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


def _file_size_or_zero(p: Path) -> int:
    try:
        return p.stat().st_size
    except FileNotFoundError:
        return 0


def _substrate_state() -> dict[str, Any]:
    wd = config.workdir()
    state: dict[str, Any] = {"path": str(wd), "exists": wd.exists()}
    if not wd.exists():
        return state
    state["pairs"] = _file_size_or_zero(config.pairs_path())
    state["labels"] = _file_size_or_zero(config.labels_path())
    state["features"] = config.features_path().exists()
    state["classifier"] = config.classifier_path().exists()
    return state


# Optional deps — keys are pip names, values are the import name to probe.
# `click` and the core runtime deps are not listed: they are mandatory and
# the CLI cannot start without them, so reporting them as "present" is noise.
_OPTIONAL_DEPS: dict[str, str] = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "numpy": "numpy",
    "sentence-transformers": "sentence_transformers",
    "scikit-learn": "sklearn",
    "torch": "torch",
    "requests": "requests",
}


def _compat_report() -> dict[str, Any]:
    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.system(),
        "distro": _distro(),
        "deps": {pip_name: _has_module(import_name) for pip_name, import_name in _OPTIONAL_DEPS.items()},
        "substrate": _substrate_state(),
        "sessions": _count_sessions(),
        "port_free": _port_free(config.labeler_port()),
        "port": config.labeler_port(),
    }


def _run_module_main(module_name: str) -> None:
    """Import and call `main()` on a sibling module. Fail loudly if missing."""
    mod = importlib.import_module(f"weighted_compact.{module_name}")
    main_fn = getattr(mod, "main", None)
    if main_fn is None:
        raise click.ClickException(f"{module_name}.py has no main() function — file a bug")
    main_fn()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Debug logging.")
@click.version_option(version=__version__, prog_name="weighted-compact")
def main(verbose: bool) -> None:
    """weighted-compact — trainable context-compaction substrate."""
    _setup_logging(verbose)


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
        click.echo(f"  {mark} {name}")
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
    config.workdir().mkdir(parents=True, exist_ok=True)
    config.state_dir().mkdir(parents=True, exist_ok=True)

    # Re-evaluate paths at command time so env overrides exported after the
    # `weighted_compact` package was imported (e.g. WEIGHTED_COMPACT_DATA set
    # in a one-shot shell wrapper) actually take effect.
    dirs = [str(p) for p in config.claude_source_dirs()]
    out = str(config.pairs_path())

    if dry_run:
        click.echo(f"Would scan: {dirs}")
        click.echo(f"Would write: {out}")
        return

    _run_module_main("extract_pairs")
    click.echo(f"Wrote pairs to {out}")


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", type=int, default=None, help="Override port (default: $WEIGHTED_COMPACT_PORT or 18890).")
def serve(host: str, port: int | None) -> None:
    """Launch the labeler UI at http://HOST:PORT/."""
    import uvicorn

    from weighted_compact import tool

    config.workdir().mkdir(parents=True, exist_ok=True)
    p = port or config.labeler_port()
    log.info("labeler → http://%s:%d/", host, p)
    uvicorn.run(tool.app, host=host, port=p, log_level="info")


@main.command()
def importance() -> None:
    """Recompose the seven-signal importance mixture."""
    _run_module_main("importance")


@main.command()
def train() -> None:
    """Fit the classifier on the current substrate."""
    _run_module_main("train")


@main.command(name="eval")
def eval_cmd() -> None:
    """Run the reconstruction-QA gate."""
    _run_module_main("eval")


@main.command(name="qa-gate")
@click.option("--easy-k", default=0.0, type=float,
              help="Weak compaction (fraction of pairs dropped).")
@click.option("--hard-k", default=0.9, type=float,
              help="Strong compaction (fraction of pairs dropped).")
@click.option("--ranker", default="importance",
              type=click.Choice(["importance", "density"]))
@click.option("--signal", default="judge",
              type=click.Choice(["judge", "substring"]),
              help="Pass metric: judge (recommended) or substring.")
@click.option("--write", is_flag=True,
              help="Write the informative subset to the substrate dir.")
def qa_gate(easy_k: float, hard_k: float, ranker: str, signal: str,
            write: bool) -> None:
    """Segment the recon-QA set by informativeness for compaction.

    Two eval runs (weak vs strong compaction), bucketing entries into
    trivial / impossible / informative / inverted. For ablation only the
    informative bucket is worth looking at — that is where the gradient is.
    """
    from weighted_compact import recon_qa

    res = recon_qa.classify_difficulty(
        easy_k=easy_k, hard_k=hard_k, ranker=ranker, signal=signal,
    )
    click.echo(
        f"total: {res['total']} "
        f"(easy_k={easy_k}, hard_k={hard_k}, ranker={ranker}, signal={signal})"
    )
    for bucket, n in res["counts"].items():
        pct = (100.0 * n / res["total"]) if res["total"] else 0.0
        click.echo(f"  {bucket:12s} {n:4d}  ({pct:5.1f}%)")
    dis = res["signal_disagreement_easy"]
    click.echo(
        f"signal disagreement on easy: "
        f"substring-only-pass={dis['substring_only_pass']}, "
        f"judge-only-pass={dis['judge_only_pass']}"
    )
    if write:
        qa_set = recon_qa.load_qa_set()
        keep_idx = set(res["buckets"]["informative"])
        out = config.workdir() / "qa_informative_subset.jsonl"
        with open(out, "w") as f:
            for i, entry in enumerate(qa_set):
                if i in keep_idx:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        click.echo(f"informative subset → {out} ({len(keep_idx)} entries)")


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
    candidates = [
        here.parent / "systemd" / "weighted-compact.service",
        here / "data" / "weighted-compact.service",
    ]
    src = next((c for c in candidates if c.exists()), None)
    if src is None:
        raise click.ClickException("weighted-compact.service template not found")

    dest_dir = Path.home() / ".config" / "systemd" / "user"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "weighted-compact.service"
    if dest.exists() and not force:
        raise click.ClickException(f"{dest} already exists — pass --force to overwrite")
    dest.write_text(src.read_text())
    click.echo(f"Wrote {dest}")
    click.echo()
    click.echo("Next:")
    click.echo("  systemctl --user daemon-reload")
    click.echo("  systemctl --user enable --now weighted-compact")
    click.echo(f"  xdg-open http://127.0.0.1:{config.labeler_port()}/")


if __name__ == "__main__":
    main()
