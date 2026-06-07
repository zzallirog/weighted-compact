"""Public registry for pluggable rankers.

Black box:
  input  — a ranker function (pair_idx → score) or a callable factory
           returning one; plus name + metadata.
  output — registration is a side effect; the ranker becomes available to
           ``weighted-compact qa-gate --ranker <name>`` and to MCP clients.
  entry  — ``@register("name", description=..., requires=...)`` decorator,
           or ``RANKER_REGISTRY.add(name, fn, ...)`` for non-decorator use.

This is the supported plugin surface. The six-signal mixture in
:mod:`weighted_compact.importance` is one ranker among many — it just
happens to ship by default. External packages register their own via
this module.

Example
-------
A third-party package that wants to add a new ranker::

    # my_extras/length_ranker.py
    from weighted_compact.ranker import register

    @register(
        name="length",
        description="Score pairs by correction/premise length ratio.",
        query_aware=False,
        since_version="0.2.0",
    )
    def load_length_ranker():
        from weighted_compact.recon_qa.context import load_pairs
        pairs = load_pairs()
        return {
            p['pair_idx']: len(p.get('correction_text', '')) /
                            max(1, len(p.get('premise_text', '')))
            for p in pairs
        }

After ``pip install -e .`` of the extras package and an explicit import
(e.g. via an entry-point or a one-line ``import my_extras.length_ranker``
in user code) the ranker becomes selectable as
``weighted-compact qa-gate --ranker length``.

Stability
---------
``RANKER_REGISTRY``, ``RankerSpec``, ``register``, ``list_rankers`` and
``get_ranker`` are part of the stability promise documented in
:doc:`/docs/stability` — they will not change shape through v1.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class RankerSpec:
    """Metadata + loader for one registered ranker.

    Attributes
    ----------
    name : str
        Unique key used on the CLI (``--ranker <name>``) and in MCP.
    loader : Callable[[], Any]
        Zero-arg callable returning either:

        - ``dict[int, float]`` — static, pre-computed pair_idx → score
        - ``Callable[[str], dict[int, float]]`` — query-aware ranker
        - any object with ``.is_compact_bypass = True`` and
          ``.summarize_excluding(source_pair_idx, pairs, query=...)`` —
          /compact-style summarizer that bypasses pair selection entirely

        The shape is decided by the loader, not declared here, because
        the existing six-signal mixture and the baseline rankers
        already use all three shapes.
    description : str
        One-line human description shown by ``weighted-compact rankers``.
    requires_extras : tuple[str, ...]
        Optional pip extras the user must install for this ranker to
        load (e.g. ``("baselines",)`` or ``("baselines-cloud",)``).
        Informational — not enforced at registration time, since the
        loader itself raises ImportError on first use anyway.
    query_aware : bool
        ``True`` if the ranker recomputes scores per question (cosine,
        BM25), ``False`` if it is a fixed pair_idx → score map.
    since_version : str
        Package version in which this ranker first appeared.
    """

    name: str
    loader: Callable[[], Any]
    description: str = ""
    requires_extras: tuple[str, ...] = field(default_factory=tuple)
    query_aware: bool = False
    since_version: str = "0.2.0"


class _Registry(dict):
    """Dict subclass with a friendly ``add`` method for non-decorator use.

    ``RANKER_REGISTRY`` is published as a plain dict-like object so that
    third-party code can introspect it directly (``"name" in registry``,
    ``registry.keys()``) without having to learn a custom API. The only
    extension is :meth:`add`, which constructs the :class:`RankerSpec` for
    callers who don't want to use the ``@register`` decorator.
    """

    def add(
        self,
        name: str,
        loader: Callable[[], Any],
        *,
        description: str = "",
        requires_extras: Iterable[str] = (),
        query_aware: bool = False,
        since_version: str = "0.2.0",
    ) -> RankerSpec:
        """Register a ranker imperatively.

        Re-registering the same name overwrites silently — this is by
        design so a third-party package can ship an upgraded version of
        a built-in ranker without import-order gymnastics.
        """
        spec = RankerSpec(
            name=name,
            loader=loader,
            description=description,
            requires_extras=tuple(requires_extras),
            query_aware=query_aware,
            since_version=since_version,
        )
        self[name] = spec
        return spec


RANKER_REGISTRY: _Registry = _Registry()
"""Module-level registry of every known ranker (name → :class:`RankerSpec`)."""


def register(
    name: str,
    *,
    description: str = "",
    requires_extras: Iterable[str] = (),
    query_aware: bool = False,
    since_version: str = "0.2.0",
) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    """Decorator: wrap a loader function and put it in :data:`RANKER_REGISTRY`.

    The decorated function is returned unchanged so it can still be
    called directly by tests or internal code.

    Example
    -------
    ::

        @register("length", description="Score by length ratio")
        def load_length_ranker():
            ...
            return {pair_idx: score, ...}
    """

    def _decorate(fn: Callable[[], Any]) -> Callable[[], Any]:
        RANKER_REGISTRY.add(
            name,
            fn,
            description=description,
            requires_extras=requires_extras,
            query_aware=query_aware,
            since_version=since_version,
        )
        return fn

    return _decorate


def list_rankers() -> list[RankerSpec]:
    """Return every registered ranker sorted by name.

    Used by the ``weighted-compact rankers`` CLI verb and by MCP clients
    that want to discover what's installed.
    """
    return sorted(RANKER_REGISTRY.values(), key=lambda s: s.name)


def get_ranker(name: str) -> RankerSpec:
    """Look up a :class:`RankerSpec` by name.

    Raises
    ------
    KeyError
        If ``name`` is not registered. The error message lists the
        registered names so callers don't have to chain a second lookup.
    """
    try:
        return RANKER_REGISTRY[name]
    except KeyError:
        known = sorted(RANKER_REGISTRY)
        raise KeyError(
            f"unknown ranker {name!r}; registered: {known}"
        ) from None


__all__ = [
    "RANKER_REGISTRY",
    "RankerSpec",
    "register",
    "list_rankers",
    "get_ranker",
]
