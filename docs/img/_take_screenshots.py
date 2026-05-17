#!/usr/bin/env python3
"""Headless screenshot capture for v0.1.0-alpha.1 README.

Runs against a live labeler at http://localhost:18890/ with a populated
fidelity cache. Each function captures one screen from the SHOT-LIST.

Usage:
    /tmp/wc-shots-venv/bin/python _take_screenshots.py [shot_name...]
    /tmp/wc-shots-venv/bin/python _take_screenshots.py all
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parent
URL = "http://localhost:18890/?lang=en"
VIEWPORT = {"width": 1920, "height": 1080}


def goto_deltas(page: Page) -> None:
    page.goto(URL, wait_until="networkidle")
    page.click("#tab-deltas-btn")
    page.wait_for_selector("#deltas-tab", state="visible")
    page.wait_for_timeout(800)  # let rows render


def shot_mode_bar(page: Page) -> None:
    """1. Mode bar — top of Deltas tab with 3 modes + cache status."""
    goto_deltas(page)
    page.wait_for_selector(".d-mode-bar", state="visible")
    bar = page.query_selector(".d-mode-bar")
    bar.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    bar.screenshot(path=str(OUT / "mode-bar.png"))


def shot_drift_full(page: Page) -> None:
    """2. Drift Inspector — table on left, Selected Pair populated on right."""
    goto_deltas(page)
    # Click first row to populate cubes
    page.wait_for_selector(".d-row[data-pair]", state="visible")
    page.click(".d-row[data-pair]:nth-of-type(2)")
    page.wait_for_selector("#d-cube-pair .d-pair-content", state="visible")
    page.wait_for_timeout(1000)
    page.screenshot(path=str(OUT / "drift-inspector-full.png"), full_page=False)


def _click_first_row_and_load_iters(page: Page) -> None:
    """Helper: select first row, wait for selection, fire iters 2-4 + finale."""
    page.wait_for_selector(".d-row[data-pair]")
    rows = page.query_selector_all(".d-row[data-pair]")
    if not rows:
        raise RuntimeError("no rows to click")
    rows[0].click()
    page.wait_for_selector("#d-cube-pair .d-pair-content", timeout=10000)
    # Wait for iter buttons to be enabled (renderNarrEmptyOrAuto runs async)
    page.wait_for_function(
        "() => { const b = document.querySelector('#d-narrative-iters .iter-btn[data-iter=\"2\"]'); return b && !b.disabled; }",
        timeout=10000,
    )
    # qwen2.5:7b cold start can take 20-30s before first token; later iters
    # are cached-model fast. Generous timeouts.
    for n in (2, 3, 4):
        page.wait_for_function(
            f"() => {{ const b = document.querySelector('#d-narrative-iters .iter-btn[data-iter=\"{n}\"]'); return b && !b.disabled; }}",
            timeout=10000,
        )
        page.click(f'#d-narrative-iters .iter-btn[data-iter="{n}"]')
        page.wait_for_function(
            f"() => window.deltasState && window.deltasState.narrCache[{n}] != null",
            timeout=180000,  # 3 min — first iter may include cold-start
        )
    page.wait_for_function(
        "() => window.deltasState && window.deltasState.narrCache.finale != null",
        timeout=90000,
    )
    page.wait_for_timeout(700)


def shot_iter_strip_finale(page: Page) -> None:
    """3. Drift Narrative cube with iter 1-4 cached + finale recommend."""
    goto_deltas(page)
    _click_first_row_and_load_iters(page)
    narrative = page.query_selector("#d-cube-narrative")
    if narrative:
        narrative.screenshot(path=str(OUT / "drift-narrative-final.png"))
    pair = page.query_selector("#d-cube-pair")
    if pair:
        pair.screenshot(path=str(OUT / "selected-pair-with-finale.png"))


def _screenshot_table_top(page: Page, filename: str, rows_visible: int = 20) -> None:
    """Crop the table to top N rows + header (avoid 5000px-tall full scrolls)."""
    table = page.query_selector(".d-table-col .d-table")
    if not table:
        return
    box = table.bounding_box()
    # header (~38px) + N rows × ~36px = 38 + 36*N
    crop_h = min(38 + 36 * rows_visible, int(box["height"]))
    page.screenshot(path=str(OUT / filename), clip={
        "x": box["x"], "y": box["y"],
        "width": box["width"], "height": crop_h,
    })


def shot_conflict_table(page: Page) -> None:
    """4. Conflict mode table — rows with re-tier arrows."""
    goto_deltas(page)
    page.click('.d-mode-btn[data-mode="conflict"]')
    page.wait_for_selector(".d-row[data-pair]", timeout=15000)
    page.wait_for_timeout(800)
    _screenshot_table_top(page, "conflict-mode-table.png", rows_visible=18)


def shot_fidelity_table(page: Page) -> None:
    """5. Fidelity mode — sorted by raw fidelity asc, worst first."""
    goto_deltas(page)
    page.click('.d-mode-btn[data-mode="fidelity"]')
    page.wait_for_selector(".d-row[data-pair]", timeout=15000)
    page.wait_for_timeout(800)
    _screenshot_table_top(page, "fidelity-mode-table.png", rows_visible=18)


def shot_selected_pair_fidelity(page: Page) -> None:
    """6. Selected Pair card in fidelity mode — judges + recommend + actions."""
    goto_deltas(page)
    page.click('.d-mode-btn[data-mode="conflict"]')
    page.wait_for_selector(".d-row[data-pair]", timeout=15000)
    # Pick first evaluated row (not 'not evaluated' placeholder)
    rows = page.query_selector_all(".d-row[data-pair]")
    for row in rows:
        text = row.inner_text()
        if "not evaluated" not in text.lower():
            row.click()
            break
    page.wait_for_selector("#d-cube-pair .d-pair-content", timeout=10000)
    page.wait_for_timeout(800)
    pair = page.query_selector("#d-cube-pair")
    if pair:
        pair.screenshot(path=str(OUT / "selected-pair-fidelity.png"))


def shot_drag_select_popup(page: Page) -> None:
    """7. Drag-select popup in Selected Pair correction block."""
    goto_deltas(page)
    page.wait_for_selector(".d-row[data-pair]")
    page.click(".d-row[data-pair]:nth-of-type(2)")
    page.wait_for_selector("#d-cube-pair .mini-block.annotatable[data-side='correction']", timeout=10000)
    # Locate correction block and simulate drag-select via JS
    target = page.query_selector("#d-cube-pair .mini-block.annotatable[data-side='correction']")
    box = target.bounding_box()
    # Drag from offset (60, 20) to (260, 20) inside the block
    sx, sy = box["x"] + 60, box["y"] + 30
    ex, ey = box["x"] + min(box["width"] - 40, 360), box["y"] + 30
    page.mouse.move(sx, sy)
    page.mouse.down()
    # multi-step move to ensure selection materialises
    steps = 12
    for i in range(1, steps + 1):
        page.mouse.move(sx + (ex - sx) * i / steps, sy + (ey - sy) * i / steps)
        page.wait_for_timeout(20)
    page.mouse.up()
    page.wait_for_selector("#ann-popup", state="visible", timeout=3000)
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "drag-select-popup.png"), clip={
        "x": max(box["x"] - 20, 0),
        "y": max(box["y"] - 20, 0),
        "width": min(900, VIEWPORT["width"] - max(box["x"] - 20, 0)),
        "height": min(360, VIEWPORT["height"] - max(box["y"] - 20, 0)),
    })


def shot_tier_action_row(page: Page) -> None:
    """8. Tier-action row close-up (4 full-width buttons + suggested halo)."""
    goto_deltas(page)
    _click_first_row_and_load_iters(page)
    recommend = page.query_selector("#d-cube-pair .d-recommend-line")
    actions = page.query_selector("#d-cube-pair .d-tier-actions")
    if recommend and actions:
        rb = recommend.bounding_box()
        ab = actions.bounding_box()
        page.screenshot(path=str(OUT / "tier-action-row.png"), clip={
            "x": rb["x"] - 10,
            "y": rb["y"] - 10,
            "width": max(rb["width"], ab["width"]) + 20,
            "height": (ab["y"] + ab["height"]) - rb["y"] + 20,
        })


SHOTS = {
    "mode-bar": shot_mode_bar,
    "drift-full": shot_drift_full,
    "iter-finale": shot_iter_strip_finale,
    "conflict": shot_conflict_table,
    "fidelity": shot_fidelity_table,
    "pair-fid": shot_selected_pair_fidelity,
    "drag-popup": shot_drag_select_popup,
    "tier-row": shot_tier_action_row,
}


# ── Variation batches ──────────────────────────────────────────────────────
# For multi-example sweeps. Call with `--batch <name>` to produce a labelled
# subdir of shots, useful when comparing different pairs / metrics / modes.

def shot_pair_in_mode(page: Page, pair_idx: int, mode: str, suffix: str,
                       fire_iters: bool = False) -> None:
    """Generic: select a specific pair_idx in a specific mode, optionally
    fire iters 2-4 + finale, screenshot Selected Pair cube."""
    page.goto(URL, wait_until="networkidle")
    page.click("#tab-deltas-btn")
    page.wait_for_selector("#deltas-tab", state="visible")
    if mode != "drift":
        page.click(f'.d-mode-btn[data-mode="{mode}"]')
    page.wait_for_selector(".d-row[data-pair]", timeout=15000)
    # Find row by pair_idx (may not be in viewport — JS click via data attr)
    row = page.query_selector(f'.d-row[data-pair="{pair_idx}"]')
    if not row:
        raise RuntimeError(f"pair {pair_idx} not in {mode} mode rows")
    row.scroll_into_view_if_needed()
    row.click()
    page.wait_for_selector("#d-cube-pair .d-pair-content", timeout=10000)
    page.wait_for_timeout(600)
    if fire_iters:
        for n in (2, 3, 4):
            page.click(f'#d-narrative-iters .iter-btn[data-iter="{n}"]')
            page.wait_for_function(
                f"() => window.deltasState && window.deltasState.narrCache[{n}] != null",
                timeout=60000,
            )
        page.wait_for_function(
            "() => window.deltasState && window.deltasState.narrCache.finale != null",
            timeout=30000,
        )
        page.wait_for_timeout(500)
    pair = page.query_selector("#d-cube-pair")
    if pair:
        pair.screenshot(path=str(OUT / f"variation-{suffix}.png"))


def run_batch(batch_name: str, pairs: list, modes: list, fire_iters: bool) -> None:
    """Sweep: cross product of pairs × modes → one variation-{batch}-{pid}-{mode}.png each."""
    print(f"batch '{batch_name}': {len(pairs)} pair(s) × {len(modes)} mode(s) "
          f"× iters={fire_iters} = {len(pairs)*len(modes)} shots")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = context.new_page()
        for pid in pairs:
            for mode in modes:
                suffix = f"{batch_name}-p{pid}-{mode}"
                t0 = time.time()
                try:
                    shot_pair_in_mode(page, pid, mode, suffix, fire_iters)
                    print(f"  ✓ {suffix} ({time.time()-t0:.1f}s)")
                except Exception as e:
                    print(f"  × {suffix} ({time.time()-t0:.1f}s): {e}", file=sys.stderr)
        browser.close()


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--batch":
        # Format: --batch <name> --pairs <pid,pid,...> --modes <m,m,...> [--iters]
        batch_name = args[1]
        pairs_arg = args[args.index("--pairs") + 1] if "--pairs" in args else "237,184,21"
        modes_arg = args[args.index("--modes") + 1] if "--modes" in args else "drift,conflict,fidelity"
        fire_iters = "--iters" in args
        pairs = [int(x) for x in pairs_arg.split(",")]
        modes = [m.strip() for m in modes_arg.split(",")]
        run_batch(batch_name, pairs, modes, fire_iters)
    else:
        requested = args or ["all"]
        targets = list(SHOTS.keys()) if "all" in requested else requested
        print(f"capturing {len(targets)} shot(s): {targets}")
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            page = context.new_page()
            for name in targets:
                fn = SHOTS.get(name)
                if not fn:
                    print(f"  unknown shot: {name}", file=sys.stderr)
                    continue
                t0 = time.time()
                try:
                    fn(page)
                    dt = time.time() - t0
                    print(f"  ✓ {name} ({dt:.1f}s)")
                except Exception as e:
                    dt = time.time() - t0
                    print(f"  × {name} ({dt:.1f}s): {e}", file=sys.stderr)
            browser.close()
    print("\noutput:")
    for f in sorted(OUT.glob("*.png")):
        print(f"  {f.name} ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
