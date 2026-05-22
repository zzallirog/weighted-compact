"""schema_extraction.cli — click subgroup mounted under main `weighted-compact` CLI.

Subcommands:
    build-bank   Auto-collect case bank from memory + HANDOFF roots.
    run          Validate bank cases via LLM extract + judge → coverage report.
    all          build-bank (idempotent) + run, end-to-end.
    paths        Print schema-extraction substrate paths.
"""

from __future__ import annotations

import click

from .. import config
from . import bank_builder, pipeline
from ._constants import EXTRACT_MODEL, JUDGE_MODEL


@click.group(name="schema")
def schema_group() -> None:
    """Schema-extraction tier — extract reusable rules from your memory dir."""


@schema_group.command("build-bank")
@click.option("--force", is_flag=True, help="Rebuild even if bank file already exists.")
@click.option("--quiet", is_flag=True, help="Suppress per-candidate progress lines.")
def build_bank_cmd(force: bool, quiet: bool) -> None:
    """Auto-collect case bank from ~/.claude/projects/*/memory/ + ~/.claude/work/."""
    path = bank_builder.build_bank(force=force, verbose=not quiet)
    click.echo(f"Bank: {path}")


@schema_group.command("run")
@click.option("--limit", type=int, default=None, help="Run only first N cases (for quick sanity).")
@click.option("--extract-model", default=EXTRACT_MODEL, show_default=True, help="Ollama model for rule extraction.")
@click.option("--judge-model", default=JUDGE_MODEL, show_default=True, help="Ollama model for MATCH/NEAR/MISMATCH judging.")
@click.option("--no-auto-build", is_flag=True, help="Fail if bank is missing instead of auto-building.")
def run_cmd(limit: int | None, extract_model: str, judge_model: str, no_auto_build: bool) -> None:
    """Validate case bank: extract rules and judge against expected. Writes coverage report."""
    result = pipeline.run_pipeline(
        limit=limit,
        extract_model=extract_model,
        judge_model=judge_model,
        auto_build=not no_auto_build,
    )
    if result.get("error") == "no_bank":
        raise click.ClickException("Bank not found and --no-auto-build set. Run `schema build-bank` first.")


@schema_group.command("all")
@click.option("--force-build", is_flag=True, help="Rebuild bank before running.")
@click.option("--limit", type=int, default=None, help="Run only first N cases.")
def all_cmd(force_build: bool, limit: int | None) -> None:
    """End-to-end: build-bank (idempotent unless --force-build) then run."""
    bank_builder.build_bank(force=force_build)
    pipeline.run_pipeline(limit=limit)


@schema_group.command("paths")
def paths_cmd() -> None:
    """Print schema-extraction paths for shell scripts."""
    click.echo(f"BANK={config.schema_bank_path()}")
    click.echo(f"RUNS={config.schema_runs_dir()}")
