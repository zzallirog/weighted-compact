"""weighted-compact command-line entry point.

Subcommands:
    bootstrap        Extract pairs from ~/.claude/projects/ into the substrate.
    serve            Run the labeler at http://127.0.0.1:18890/.
    mcp-serve        Run the local-only stdio MCP server over the substrate.
    compat           Read-only diagnostic. Print what was detected; --json for machine output.
    metrics          Read-only footprint + freshness numbers for the local substrate.
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
    state["rem_decay"] = config.rem_decay_path().exists()
    state["recon_qa"] = _file_size_or_zero(config.recon_qa_set_path())
    return state


def _next_step(substrate_state: dict[str, Any]) -> str | None:
    """Return a single directive string based on what is missing in the substrate."""
    if not substrate_state.get("exists"):
        return "Next: weighted-compact bootstrap"
    pairs_bytes = substrate_state.get("pairs", 0)
    if pairs_bytes == 0:
        return "Next: weighted-compact bootstrap"
    if not substrate_state.get("features"):
        return "Next: weighted-compact importance"
    if not substrate_state.get("rem_decay"):
        return "Next: weighted-compact rem-pass"
    recon_bytes = substrate_state.get("recon_qa", 0)
    if recon_bytes == 0:
        return "Next: open the labeler at http://127.0.0.1:18890/ and seed a few Q&A entries"
    return "Next: weighted-compact qa-gate --signal judge   # check fidelity"


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


from weighted_compact.schema_extraction.cli import schema_group as _schema_group  # noqa: E402
main.add_command(_schema_group)


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
    directive = _next_step(report["substrate"])
    if directive:
        click.echo()
        click.secho(directive, fg="cyan")


@main.command()
@click.option("--no-bootstrap", is_flag=True, help="Skip bootstrap (use existing substrate).")
def quickstart(no_bootstrap: bool) -> None:
    """One-command first-run: compat → bootstrap → importance → preview top 5."""
    import sys

    # ── step 1: compat ───────────────────────────────────────────────────────
    click.secho("== compat ==", fg="cyan", bold=True)
    report = _compat_report()
    sub = report["substrate"]
    click.echo(f"Substrate: {sub['path']} ({'exists' if sub['exists'] else 'absent'})")
    click.echo(f"  pairs.jsonl  {sub.get('pairs', 0)} bytes")
    click.echo(f"  features.npz {'present' if sub.get('features') else 'absent'}")

    # ── step 2: bootstrap ────────────────────────────────────────────────────
    need_bootstrap = sub.get("pairs", 0) == 0 and not no_bootstrap
    if need_bootstrap:
        click.echo()
        click.secho("== bootstrap ==", fg="cyan", bold=True)
        config.workdir().mkdir(parents=True, exist_ok=True)
        config.state_dir().mkdir(parents=True, exist_ok=True)
        try:
            _run_module_main("extract_pairs")
        except Exception as exc:
            click.secho(f"bootstrap failed: {exc}", fg="red", err=True)
            click.secho("Fix the error above, then re-run: weighted-compact bootstrap", fg="yellow")
            sys.exit(1)
        # re-read substrate state after bootstrap
        sub = _substrate_state()
        if sub.get("pairs", 0) == 0:
            click.secho("Bootstrap produced 0 pairs. Check that ~/.claude/projects/ has session files.", fg="yellow")
            sys.exit(1)
        click.echo(f"  pairs.jsonl  {sub['pairs']} bytes")

    # ── step 3: importance ───────────────────────────────────────────────────
    if not sub.get("features"):
        click.echo()
        click.secho("== importance ==", fg="cyan", bold=True)
        try:
            _run_module_main("importance")
        except Exception as exc:
            click.secho(f"importance failed: {exc}", fg="red", err=True)
            click.secho("Fix the error above, then re-run: weighted-compact importance", fg="yellow")
            sys.exit(1)

    # ── step 4: top-5 preview ────────────────────────────────────────────────
    click.echo()
    click.secho("== top-5 high-importance pairs ==", fg="cyan", bold=True)
    try:
        import numpy as np

        from weighted_compact.recon_qa.context import load_pairs

        pairs = load_pairs()
        imp_path = config.importance_path()
        if pairs and imp_path.exists():
            imp = np.load(imp_path, allow_pickle=True)
            scores = imp["scores"]
            pair_indices = imp["pair_indices"]
            order = np.argsort(-scores)
            shown = 0
            for rank_i in order:
                pid = int(pair_indices[rank_i])
                if pid >= len(pairs):
                    continue
                p = pairs[pid]
                preview = (p.get("correction_text") or p.get("premise_text") or "").replace("\n", " ")[:80]
                click.echo(f"  [{pid:4d}] {preview}")
                shown += 1
                if shown >= 5:
                    break
        else:
            click.echo("  (no pairs or importance.npz to preview)")
    except Exception as exc:
        click.echo(f"  (preview failed: {exc})")

    # ── step 5: next directive ───────────────────────────────────────────────
    click.echo()
    sub = _substrate_state()
    final = _next_step(sub)
    if final:
        click.secho(final, fg="cyan")
    click.echo()
    click.echo("  Open the labeler: weighted-compact serve")
    click.echo(f"  then visit      : http://127.0.0.1:{config.labeler_port()}/welcome")


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

    # Read back the freshly-written pairs to give the operator something
    # concrete: counts + the next command in the pipeline. Without this
    # the only signal was "Wrote pairs to <path>" which doesn't tell a
    # new user whether it scanned anything useful.
    from weighted_compact.recon_qa.context import load_pairs
    try:
        pairs = load_pairs()
    except (FileNotFoundError, OSError):
        pairs = []
    n_pairs = len(pairs)
    n_sessions = len({p.get("session_id") for p in pairs if p.get("session_id")})
    click.echo("")
    click.echo("Bootstrap complete.")
    click.echo(f"  pairs:    {n_pairs}")
    click.echo(f"  sessions: {n_sessions}")
    click.echo(f"  scanned:  {', '.join(dirs)}")
    click.echo(f"  output:   {out}")
    click.echo("")
    click.echo("Next: weighted-compact importance     # build the seven-signal mixture")
    click.echo("      weighted-compact rem-pass       # nightly wall-clock decay")


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.option("--port", type=int, default=None, help="Override port (default: $WEIGHTED_COMPACT_PORT or 18890).")
def serve(host: str, port: int | None) -> None:
    """Launch the labeler UI at http://HOST:PORT/."""
    import uvicorn

    from weighted_compact import tool

    config.workdir().mkdir(parents=True, exist_ok=True)
    p = port or config.labeler_port()
    # Pre-check: refuse with a paste-ready hint instead of an opaque uvicorn
    # OSError stack. The labeler is the most-restarted command and "port in use"
    # is the single most common failure for users running it more than once.
    if not _port_free(p):
        raise click.ClickException(
            f"Port {p} is already in use on {host}. Find what's holding it: "
            f"lsof -i :{p}   # or: ss -tlnp 'sport = :{p}'   "
            f"(another labeler? stop with: systemctl --user stop weighted-compact)"
        )
    log.info("labeler → http://%s:%d/", host, p)
    uvicorn.run(tool.app, host=host, port=p, log_level="info")


@main.command(name="mcp-serve")
def mcp_serve() -> None:
    """Run the local-only stdio MCP server over the substrate.

    Exposes three read-only tools (search_pairs, compact_session,
    substrate_info) to any MCP-speaking client via stdio. No network,
    no auto-injection — the client decides when to call.

    Requires the [mcp] extra. Install with:

        pipx install 'weighted-compact[mcp]'

    See docs/mcp-integration.md for the Claude Desktop config snippet.
    """
    try:
        from weighted_compact import mcp_server
    except ImportError as exc:
        raise click.ClickException(
            f"{exc}\n\n"
            "Install the optional MCP extra:\n"
            "    pipx install 'weighted-compact[mcp]'\n"
            "or, inside a venv:\n"
            "    pip install 'weighted-compact[mcp]'"
        ) from exc

    try:
        mcp_server.run_stdio()
    except ImportError as exc:
        # The lazy import inside mcp_server.build_server() surfaces here
        # if the SDK is missing even though the module itself imported.
        raise click.ClickException(
            f"{exc}\n\n"
            "Install the optional MCP extra:\n"
            "    pipx install 'weighted-compact[mcp]'"
        ) from exc


@main.command()
def importance() -> None:
    """Recompose the seven-signal importance mixture."""
    _run_module_main("importance")


@main.command(name="rem-pass")
@click.option("--half-life-days", default=7.0, type=float,
              help="Half-life of the wall-clock decay in days "
                   "(7.0 → yesterday ≈ 0.91, week ago ≈ 0.50, month ago ≈ 0.05).")
def rem_pass(half_life_days: float) -> None:
    """Recompute the REM-decay multiplier from current wall-clock time.

    Designed to run nightly via the bundled systemd-user timer. The output
    `rem_decay.npz` is a per-pair multiplier consumed by the compaction
    reader when `--rem-decay` is passed to the eval / qa-gate runs.

    Independent of importance.py: importance encodes content properties
    (stable), REM encodes time (refreshes every day).
    """
    from weighted_compact import rem_decay
    summary = rem_decay.build(half_life_days=half_life_days)
    click.echo(f"Output: {summary['path']}")
    click.echo(
        f"N={summary['pair_count']}  "
        f"sessions={summary['session_count']}  "
        f"aged={summary['aged_session_count']}  "
        f"missing={summary['missing_session_count']}"
    )
    click.echo(
        f"half-life={summary['half_life_days']} days  "
        f"max_age_seen={summary['max_age_days_seen']:.1f} days  "
        f"ref={summary['ref_iso']}"
    )
    click.echo(
        f"factor: min={summary['factor_min']:.3f}  "
        f"mean={summary['factor_mean']:.3f}  max={summary['factor_max']:.3f}"
    )


@main.group(name="baseline")
def baseline() -> None:
    """Baseline rankers for fidelity comparison against the mixture."""


@baseline.command(name="build")
@click.option("--ranker",
              type=click.Choice(["random", "recency", "rem"]),
              required=True,
              help="Which baseline ranker to (re)generate.")
@click.option("--seed", default=42, type=int,
              help="Random seed (random ranker only).")
@click.option("--half-life-days", default=7.0, type=float,
              help="REM-decay half-life in days (rem ranker only).")
def baseline_build(ranker: str, seed: int, half_life_days: float) -> None:
    """Generate the baseline ranker's npz artefact.

    The resulting file lives at `<substrate>/baseline_<ranker>.npz` and is
    a drop-in replacement for `importance.npz` (same schema). Consume it via
    `weighted-compact qa-gate --ranker <ranker>`.
    """
    if ranker == "random":
        from weighted_compact.baselines import random_ranker as mod
        summary = mod.build(seed=seed)
    elif ranker == "recency":
        from weighted_compact.baselines import recency_ranker as mod
        summary = mod.build()
    elif ranker == "rem":
        from weighted_compact.baselines import rem_ranker as mod
        summary = mod.build(half_life_days=half_life_days)
    else:
        raise click.ClickException(f"unknown baseline ranker: {ranker}")
    click.echo(f"Output: {summary['path']}")
    click.echo(
        f"N={summary['n']}  "
        f"min={summary['min']:.3f} mean={summary['mean']:.3f} max={summary['max']:.3f}"
    )


_BASELINE_RUN_ALL_DEFAULT = (
    "importance,density,random,recency,cosine,bm25,compact_qwen"
)


@baseline.command(name="run-all")
@click.option(
    "--include",
    default=_BASELINE_RUN_ALL_DEFAULT,
    help=(
        "Comma-separated ranker names. Default excludes compact_sonnet "
        "(cloud, opt-in). Pass 'all' to include every registered ranker."
    ),
)
@click.option("--k-drop", default=0.5, type=float,
              help="Compaction strength: fraction of pairs dropped.")
@click.option("--signal", default="judge",
              type=click.Choice(["judge", "substring"]))
@click.option("--output", default=None,
              help="Path to write JSON results; default <substrate>/baseline_results.json")
def baseline_run_all(include: str, k_drop: float, signal: str,
                      output: str | None) -> None:
    """Run recon-QA evaluation for each baseline; emit a comparison table.

    Static baselines are auto-built if their .npz is missing. Each ranker
    runs through the same `run_eval(k_drop, ranker)` pipeline against the
    same qa_set, producing a judge-yes fraction directly comparable to
    the mixture's headline number.

    Output JSON shape:

        {
          "harness": {"k_drop": …, "signal": …, "n_qa": …},
          "results": {
            "importance": {"judge_yes_fraction": …, "substring_pass_fraction": …, …},
            "random":     {…},
            …
          }
        }

    Expensive — each ranker is one full eval pass over the qa_set. Plan
    overnight runs accordingly.
    """
    from weighted_compact import recon_qa
    from weighted_compact.recon_qa.fidelity import _RANKER_LOADERS

    if include == "all":
        names = list(_RANKER_LOADERS)
    else:
        names = [n.strip() for n in include.split(",") if n.strip()]
    unknown = [n for n in names if n not in _RANKER_LOADERS]
    if unknown:
        raise click.ClickException(
            f"unknown rankers: {unknown}; "
            f"known: {sorted(_RANKER_LOADERS)}"
        )

    # Auto-build static baselines if their npz is missing
    if "random" in names and not config.baseline_random_path().exists():
        click.echo("Building baseline_random.npz …")
        from weighted_compact.baselines import random_ranker
        random_ranker.build()
    if "recency" in names and not config.baseline_recency_path().exists():
        click.echo("Building baseline_recency.npz …")
        from weighted_compact.baselines import recency_ranker
        recency_ranker.build()

    qa_set = recon_qa.load_qa_set()
    results: dict[str, Any] = {
        "harness": {
            "k_drop": k_drop,
            "signal": signal,
            "n_qa": len(qa_set),
        },
        "results": {},
    }

    for name in names:
        click.echo(f"\n=== Running ranker={name} ===")
        try:
            run = recon_qa.run_eval(k_drop=k_drop, ranker=name)
        except Exception as exc:
            click.echo(f"  ERROR: {exc}")
            results["results"][name] = {"error": str(exc)}
            continue
        n = len(run)
        if n == 0:
            results["results"][name] = {"n": 0, "note": "empty qa_set"}
            click.echo("  qa_set is empty — nothing to evaluate")
            continue
        sub_pass = sum(1 for r in run if r.get("substring_pass"))
        judge_yes = sum(
            1 for r in run if r.get("judge", {}).get("verdict") == "yes"
        )
        results["results"][name] = {
            "n": n,
            "substring_pass_fraction": sub_pass / n,
            "judge_yes_fraction": judge_yes / n,
            "judge_yes": judge_yes,
            "substring_pass": sub_pass,
        }
        click.echo(
            f"  n={n}  judge_yes={judge_yes}/{n} ({judge_yes / n:.3f})  "
            f"substring_pass={sub_pass}/{n} ({sub_pass / n:.3f})"
        )

    out_path = (
        Path(output).expanduser()
        if output
        else (config.workdir() / "baseline_results.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    click.echo(f"\nResults: {out_path}")


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
              help="Ranker name (built-in or registered plugin). "
                   "List options: `weighted-compact rankers`.")
@click.option("--signal", default="judge",
              type=click.Choice(["judge", "substring"]),
              help="Pass metric: judge (recommended) or substring.")
@click.option("--rem-decay/--no-rem-decay", default=False,
              help="Multiply candidate scores by rem_decay.npz (nightly "
                   "REM pass). Silently no-ops if the REM pass has never "
                   "been run.")
@click.option("--no-preflight", "no_preflight", is_flag=True,
              help="Skip the ollama reachability + model probe. Only use "
                   "this to deliberately reproduce the silent-judge-failure "
                   "mode; default is to fail fast with a fix directive.")
@click.option("--write", is_flag=True,
              help="Write the informative subset to the substrate dir.")
def qa_gate(easy_k: float, hard_k: float, ranker: str, signal: str,
            rem_decay: bool, no_preflight: bool, write: bool) -> None:
    """Segment the recon-QA set by informativeness for compaction.

    Two eval runs (weak vs strong compaction), bucketing entries into
    trivial / impossible / informative / inverted. For ablation only the
    informative bucket is worth looking at — that is where the gradient is.
    """
    from weighted_compact import recon_qa
    # Force-import fidelity so the built-in rankers register before we
    # validate the --ranker argument against RANKER_REGISTRY.
    from weighted_compact.recon_qa import fidelity  # noqa: F401
    from weighted_compact.ranker import RANKER_REGISTRY

    if ranker not in RANKER_REGISTRY:
        raise click.ClickException(
            f"unknown ranker {ranker!r}; "
            f"registered: {sorted(RANKER_REGISTRY)}. "
            f"List details with `weighted-compact rankers`."
        )

    res = recon_qa.classify_difficulty(
        easy_k=easy_k, hard_k=hard_k, ranker=ranker, signal=signal,
        rem_decay=rem_decay, preflight=not no_preflight,
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


@main.command()
@click.option("--json", "as_json", is_flag=True,
              help="Emit machine-readable JSON instead of the text table.")
def rankers(as_json: bool) -> None:
    """List every registered ranker (built-in and third-party plugins).

    The registry is :data:`weighted_compact.ranker.RANKER_REGISTRY`.
    Built-in entries are registered as a side effect of importing
    ``weighted_compact.recon_qa.fidelity``; external packages register
    via the ``@register`` decorator or ``RANKER_REGISTRY.add(...)``.

    See ``docs/extension-recipe.md`` for a worked example of adding a
    new ranker from an external package.
    """
    # Importing fidelity registers the eight shipped rankers.
    from weighted_compact.recon_qa import fidelity  # noqa: F401
    from weighted_compact.ranker import list_rankers

    specs = list_rankers()
    if as_json:
        payload = [
            {
                "name": s.name,
                "description": s.description,
                "requires_extras": list(s.requires_extras),
                "query_aware": s.query_aware,
                "since_version": s.since_version,
            }
            for s in specs
        ]
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if not specs:
        click.echo("(no rankers registered)")
        return

    # Column widths sized to the data, with a sensible minimum so the
    # header still reads cleanly when only short names are registered.
    name_w = max(8, max(len(s.name) for s in specs))
    since_w = max(7, max(len(s.since_version) for s in specs))
    qa_w = 11  # len("query_aware")

    header = (
        f"{'name':<{name_w}}  "
        f"{'query_aware':<{qa_w}}  "
        f"{'since':<{since_w}}  "
        f"extras / description"
    )
    click.echo(header)
    click.echo("-" * len(header))
    for s in specs:
        extras = ",".join(s.requires_extras) if s.requires_extras else "-"
        click.echo(
            f"{s.name:<{name_w}}  "
            f"{str(s.query_aware):<{qa_w}}  "
            f"{s.since_version:<{since_w}}  "
            f"[{extras}] {s.description}"
        )


@main.command()
@click.option("--json", "as_json", is_flag=True,
              help="Emit machine-readable JSON instead of the plain-text view.")
def metrics(as_json: bool) -> None:
    """Print footprint + freshness metrics for the local substrate.

    Read-only. Reports substrate path, total + per-file size, *.bak.*
    cleanup overhead, pair/session counts, REM-pass freshness, and a
    warm-cache micro-timing of `load_pairs` + `load_importance`.

    Pair with `weighted-compact compat` for the dependency view; together
    they cover "what is detected" and "what does it cost".
    """
    from weighted_compact import metrics as _metrics
    report = _metrics.collect()
    if as_json:
        click.echo(json.dumps(report, indent=2))
        return
    click.echo(_metrics.format_text(report))


@main.command(name="install-units")
@click.option("--force", is_flag=True, help="Overwrite existing unit files.")
def install_units(force: bool) -> None:
    """Write all systemd user units under ~/.config/systemd/user/.

    Installs:
      - weighted-compact.service           — labeler UI on :18890 (manual start)
      - weighted-compact-rem-pass.service  — nightly REM-decay refresh
      - weighted-compact-rem-pass.timer    — daily 04:00 trigger for the above
    """
    here = Path(__file__).resolve().parent
    systemd_src_dirs = [here.parent / "systemd", here / "data"]
    unit_files = [
        "weighted-compact.service",
        "weighted-compact-rem-pass.service",
        "weighted-compact-rem-pass.timer",
    ]

    dest_dir = Path.home() / ".config" / "systemd" / "user"
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    skipped: list[Path] = []
    for unit in unit_files:
        src = next((d / unit for d in systemd_src_dirs if (d / unit).exists()), None)
        if src is None:
            click.echo(f"  · template not found, skipped: {unit}", err=True)
            continue
        dest = dest_dir / unit
        if dest.exists() and not force:
            skipped.append(dest)
            continue
        dest.write_text(src.read_text())
        written.append(dest)

    for p in written:
        click.echo(f"Wrote {p}")
    for p in skipped:
        click.echo(f"Exists, skipped (pass --force): {p}")

    if not written and not skipped:
        raise click.ClickException("no systemd templates found in the install tree")

    click.echo()
    click.echo("Next:")
    click.echo("  systemctl --user daemon-reload")
    click.echo("  systemctl --user enable --now weighted-compact-rem-pass.timer")
    click.echo("  # labeler is opt-in (the published ablation makes it optional):")
    click.echo("  # systemctl --user enable --now weighted-compact")
    click.echo(f"  # xdg-open http://127.0.0.1:{config.labeler_port()}/")


if __name__ == "__main__":
    main()
