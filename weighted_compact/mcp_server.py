"""Local-only stdio MCP server over the weighted-compact substrate.

Read-only query surface. Exposes three substrate operations to any
MCP-speaking client (Claude Desktop, mcp-cli, IDE plugins) via stdio:

    search_pairs     — cosine search over correction-text embeddings
    compact_session  — assemble a compacted-markdown view of the source
                       pair's session with budget meta
    substrate_info   — cheap diagnostic of what's built and available

Architectural constraints (intentional, locked):

    - Read-only. No write tools, no labeling, no timers, no auto-injection.
      The client polls; the server answers.
    - Stdio transport only. No HTTP/SSE/WebSocket in this module — that
      would defeat the local-only framing.
    - Lazy import of the `mcp` SDK. `import weighted_compact` must keep
      working when the optional `[mcp]` extra is not installed. The
      ImportError surfaces with an install instruction below.
    - Substrate-disable-clean. If `pairs.jsonl` / `importance.npz` /
      `features.npz` is missing, the tool returns an explicit error
      payload — never crashes the stdio loop.

Run via:

    weighted-compact mcp-serve

The CLI entry point handles the install-instruction error if the SDK
isn't present; this module is safe to import (no top-level `mcp` import)
but `run_stdio()` will raise if invoked without the extra.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from weighted_compact import config
from weighted_compact.recon_qa.context import (
    build_compacted_context_with_meta,
    load_importance,
    load_pairs,
    load_rem_decay,
    load_topic_map,
)

# Optional dependency. Import inside `_require_mcp()` so this module loads
# even when the `[mcp]` extra is not installed, letting CLI surface the
# install instruction cleanly.
_INSTALL_HINT = (
    "the 'mcp' Python SDK is not installed — "
    "install with `pipx install 'weighted-compact[mcp]'` "
    "(or `pip install 'weighted-compact[mcp]'` in a venv)"
)


def _require_mcp():
    """Import the mcp SDK lazily; raise a clear error if missing."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc
    return FastMCP


# Preview helper — bounded read prevents accidental megabyte payloads
# when the substrate has long premises/corrections.
_PREVIEW_CHARS = 200


def _preview(text: str, n: int = _PREVIEW_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _substrate_missing(name: str, path) -> dict[str, Any]:
    """Standard error payload for missing substrate artefacts."""
    return {
        "error": "substrate_not_built",
        "missing": name,
        "expected_path": str(path),
        "hint": (
            "run `weighted-compact bootstrap` to build pairs+features, "
            "then `weighted-compact importance` for the mixture, "
            "and (optionally) `weighted-compact rem-pass` for REM decay"
        ),
    }


# ---------------------------------------------------------------------------
# Tool implementations — pure-Python; wrapped by FastMCP in `build_server()`.
# Each one returns a JSON-serialisable dict / list. Errors are returned as
# structured payloads, not raised, so the stdio loop never dies on a missing
# substrate.
# ---------------------------------------------------------------------------


def _tool_search_pairs(query: str, top_k: int = 10) -> list[dict[str, Any]] | dict[str, Any]:
    """Cosine-rank pairs against the query and return top-k previews.

    Uses the existing CosineRanker (e5 dense over the windowed feature
    matrix). Lazy-loaded so we don't pay model-load cost until the first
    search call.
    """
    pairs_path = config.pairs_path()
    feats_path = config.features_path()
    if not pairs_path.exists():
        return _substrate_missing("pairs.jsonl", pairs_path)
    if not feats_path.exists():
        return _substrate_missing("features.npz", feats_path)

    try:
        from weighted_compact.baselines.cosine_ranker import CosineRanker
    except ImportError as exc:
        return {
            "error": "ranker_import_failed",
            "detail": str(exc),
            "hint": "install the [baselines] extra: `pip install 'weighted-compact[baselines]'`",
        }

    try:
        ranker = CosineRanker()
    except FileNotFoundError as exc:
        return {"error": "substrate_not_built", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surface verbatim, don't crash stdio
        return {"error": "ranker_init_failed", "detail": str(exc)}

    try:
        scores = ranker(query)
    except Exception as exc:  # noqa: BLE001
        return {"error": "ranker_call_failed", "detail": str(exc)}

    pairs = load_pairs()
    pairs_by_idx = {p["pair_idx"]: p for p in pairs}

    k = max(1, int(top_k))
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]

    out: list[dict[str, Any]] = []
    for pair_idx, score in ranked:
        p = pairs_by_idx.get(pair_idx)
        if p is None:
            # Index in features.npz but not in pairs.jsonl — substrate drift,
            # skip silently rather than half-fill the row.
            continue
        out.append({
            "pair_idx": int(pair_idx),
            "session_id": p.get("session_id", ""),
            "premise_preview": _preview(p.get("premise_text", "")),
            "correction_preview": _preview(p.get("correction_text", "")),
            "score": float(score),
        })
    return out


def _tool_compact_session(
    source_pair_idx: int,
    k_drop: float = 0.5,
    ranker: str = "importance",
    rem_decay: bool = False,
) -> dict[str, Any]:
    """Build a compacted markdown view of the source pair's session.

    Hides the source pair (ground-truth reservation) and returns the
    remaining session pairs ranked by the chosen scoring source,
    truncated to `(1 - k_drop)` of the session. Honors REM-decay
    multiplier when `rem_decay=True` and `rem_decay.npz` exists.
    """
    pairs_path = config.pairs_path()
    if not pairs_path.exists():
        return _substrate_missing("pairs.jsonl", pairs_path)

    pairs = load_pairs()
    if not pairs:
        return {"error": "empty_substrate", "hint": "pairs.jsonl is empty"}

    if source_pair_idx < 0 or source_pair_idx >= len(pairs):
        return {
            "error": "source_pair_idx_out_of_range",
            "source_pair_idx": int(source_pair_idx),
            "valid_range": [0, len(pairs) - 1],
            "pair_count": len(pairs),
        }

    if ranker == "importance":
        try:
            scoring = load_importance()
        except FileNotFoundError as exc:
            return {"error": "substrate_not_built", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"error": "scoring_load_failed", "detail": str(exc)}
    else:
        # Reserve the slot for future rankers; today only importance is
        # supported via this tool. Other rankers (cosine/bm25) need a
        # query argument which `compact_session` does not take.
        return {
            "error": "unsupported_ranker",
            "ranker": ranker,
            "supported": ["importance"],
            "hint": "query-aware rankers (cosine, bm25) require a query; "
                    "use search_pairs for that surface",
        }

    topic_map = load_topic_map() or None
    rem_decay_map = load_rem_decay() if rem_decay else None
    if rem_decay and not rem_decay_map:
        # Asked for it, but the nightly pass has never run. Surface it.
        return {
            "error": "rem_decay_not_built",
            "expected_path": str(config.rem_decay_path()),
            "hint": "run `weighted-compact rem-pass` (or enable the timer)",
        }

    try:
        markdown, meta = build_compacted_context_with_meta(
            source_pair_idx=int(source_pair_idx),
            pairs=pairs,
            scoring=scoring,
            k_drop=float(k_drop),
            topic_map=topic_map,
            rem_decay_map=rem_decay_map,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": "build_failed", "detail": str(exc)}

    return {"markdown": markdown, "meta": meta}


def _tool_substrate_info() -> dict[str, Any]:
    """Cheap diagnostic — counts and presence flags for substrate artefacts.

    Returns:
        pair_count, session_count, has_importance, has_rem_decay,
        rem_decay_ref_iso, signals_present
    """
    pairs_path = config.pairs_path()
    importance_path = config.importance_path()
    rem_decay_path = config.rem_decay_path()
    features_path = config.features_path()

    info: dict[str, Any] = {
        "workdir": str(config.workdir()),
        "pair_count": 0,
        "session_count": 0,
        "has_pairs": pairs_path.exists(),
        "has_features": features_path.exists(),
        "has_importance": importance_path.exists(),
        "has_rem_decay": rem_decay_path.exists(),
        "rem_decay_ref_iso": None,
        "signals_present": [],
    }

    if pairs_path.exists():
        try:
            pairs = load_pairs()
            info["pair_count"] = len(pairs)
            info["session_count"] = len({p.get("session_id") for p in pairs})
        except Exception as exc:  # noqa: BLE001
            info["pairs_error"] = str(exc)

    if importance_path.exists():
        try:
            import numpy as np
            npz = np.load(importance_path, allow_pickle=True)
            if "component_names" in npz.files:
                info["signals_present"] = [str(n) for n in npz["component_names"]]
        except Exception as exc:  # noqa: BLE001
            info["importance_error"] = str(exc)

    if rem_decay_path.exists():
        try:
            import numpy as np
            npz = np.load(rem_decay_path, allow_pickle=True)
            if "meta" in npz.files:
                meta_arr = npz["meta"]
                # meta is stored as a 0-d object array containing a dict
                meta_obj = meta_arr.item() if meta_arr.shape == () else meta_arr.tolist()
                if isinstance(meta_obj, dict):
                    info["rem_decay_ref_iso"] = meta_obj.get("ref_iso")
                    info["rem_decay_half_life_days"] = meta_obj.get("half_life_days")
        except Exception as exc:  # noqa: BLE001
            info["rem_decay_error"] = str(exc)

    return info


# ---------------------------------------------------------------------------
# FastMCP wiring — server is built lazily so importing this module never
# requires the optional SDK to be present.
# ---------------------------------------------------------------------------


def build_server():
    """Construct a FastMCP server with the three substrate tools registered.

    Separate from `run_stdio()` so tests can introspect the server object
    (e.g. list registered tools) without launching the stdio loop.
    """
    FastMCP = _require_mcp()

    server = FastMCP("weighted-compact")

    @server.tool()
    def search_pairs(
        query: Annotated[
            str,
            Field(description=(
                "Search text, cosine-matched against each pair's correction-text "
                "embedding (e5-multilingual-small, multilingual). Plain keywords or "
                "a natural-language phrase both work; no special query syntax."
            )),
        ],
        top_k: Annotated[
            int,
            Field(description=(
                "Maximum number of results, ordered by descending cosine score in "
                "[-1, 1]. Values below 1 are treated as 1. Default 10."
            )),
        ] = 10,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Cosine-search the substrate's correction-text embeddings.

        Returns the top-K most-similar pairs to `query`, each as a dict
        with pair_idx, session_id, premise_preview (≤200 chars),
        correction_preview (≤200 chars), and cosine score in [-1, 1].

        Requires `features.npz` (built by `weighted-compact bootstrap`)
        and the [baselines] extra (sentence-transformers). On the first
        call the e5-multilingual-small model is loaded into memory and
        cached for subsequent calls.

        On missing substrate or import error returns a single dict with
        an `error` key rather than raising — the stdio loop must not die
        on a misconfigured client.
        """
        return _tool_search_pairs(query=query, top_k=top_k)

    @server.tool()
    def compact_session(
        source_pair_idx: Annotated[
            int,
            Field(description=(
                "Index into pairs.jsonl of the pair whose session to compact. This "
                "pair is HIDDEN from the output so it can serve as reconstruction-QA "
                "ground truth. Must be in [0, pair_count-1]; out-of-range returns an "
                "error payload."
            )),
        ],
        k_drop: Annotated[
            float,
            Field(description=(
                "Fraction of the session's pairs to drop, in [0.0, 1.0]. 0.0 keeps "
                "the whole session; 0.9 is aggressive compaction. The kept fraction "
                "(1 - k_drop) is selected by the chosen ranker."
            )),
        ] = 0.5,
        ranker: Annotated[
            str,
            Field(description=(
                "Scoring source for ranking retained pairs. Only 'importance' (the "
                "six-signal mixture) is supported here; query-aware rankers "
                "(cosine, bm25) need a query and live in search_pairs."
            )),
        ] = "importance",
        rem_decay: Annotated[
            bool,
            Field(description=(
                "If true, multiply each score by the nightly REM-decay map (recency "
                "down-weighting). Requires `weighted-compact rem-pass` to have run; "
                "if the map is absent this returns an error payload rather than "
                "silently ignoring the flag."
            )),
        ] = False,
    ) -> dict[str, Any]:
        """Assemble a compacted-markdown view of the source pair's session.

        Hides the source pair (so it can be used as ground truth in
        reconstruction-QA) and returns the remaining session pairs
        ranked by the chosen scoring source, truncated to keep
        `(1 - k_drop)` of the session.

        Args:
            source_pair_idx: index into pairs.jsonl identifying the
                pair whose session should be compacted. The pair itself
                is hidden from the output.
            k_drop: fraction of session pairs to drop (0.0 = keep all,
                0.9 = aggressive compaction).
            ranker: scoring source. Currently only "importance" is
                supported here (query-aware rankers belong in
                search_pairs).
            rem_decay: if True, multiply scores by the nightly REM-decay
                map (requires `weighted-compact rem-pass` to have run).

        Returns a dict with `markdown` (the compacted context, ready to
        paste into a prompt) and `meta` (budget-transparency: pairs_total,
        pairs_kept, input_chars, output_chars, tokens_estimate,
        compaction_ratio, signals_top3, ranker label).

        On invalid input or missing substrate returns a dict with an
        `error` key rather than raising.
        """
        return _tool_compact_session(
            source_pair_idx=source_pair_idx,
            k_drop=k_drop,
            ranker=ranker,
            rem_decay=rem_decay,
        )

    @server.tool()
    def substrate_info() -> dict[str, Any]:
        """Report what's built and what isn't — cheap diagnostic.

        Returns a dict with pair_count, session_count, has_importance,
        has_rem_decay, rem_decay_ref_iso (ISO timestamp of the last
        REM pass), and signals_present (names of the importance mixture
        components). Includes path of the substrate workdir.

        Use this on connect to know which other tools will succeed
        without paying their setup cost first. Always returns a dict
        even when nothing is built.
        """
        return _tool_substrate_info()

    return server


def run_stdio() -> None:
    """Run the MCP server over stdio. Blocks until the client disconnects.

    Raises ImportError with an install instruction if the `mcp` SDK is
    not present.
    """
    server = build_server()
    # FastMCP.run() with no args defaults to stdio transport. Explicit
    # "stdio" is kinder to readers of the code and to future SDK
    # versions whose default may shift.
    server.run("stdio")
