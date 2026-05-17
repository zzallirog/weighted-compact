# Screenshot shot list for v0.1.0-alpha.1 README

Capture 9 screens at `http://127.0.0.1:18890/` after the fidelity
cache build completes (`/api/deltas/fidelity/status` should report
~100+ evaluated pairs). All shots taken at 1920×1080 logical
viewport, dark theme (default).

Save to `docs/img/` with the filenames listed below.

---

## Existing — keep as is

- **`labeler-help-open.png`** · already in repo, used by `§02`
- **`reconstruction-tab.png`** · already in repo, used by `§04`

---

## New shots needed

### 1. `mode-bar.png` · used by `§07 / §09`

**Route:** Tab → **Дельты** at top.
**Crop:** top of Deltas tab, capture the 3-mode bar
(`drift / conflict / fidelity`) + cache status pill + build button.
**State:** mode = `drift` (default), some snapshots visible in the
instrument-bar strip below.
Show all three mode tiles with their italic hints.

### 2. `drift-inspector-full.png` · used by `§07`

**Route:** Deltas tab, mode = `drift`.
**State:** at least 5 rows visible in the table on the left, one row
selected (highlighted), Selected Pair cube on the right with the new
recommendation block visible (color-tinted), the 4-tier mode strip
below it, and the manual-row at the bottom.
**Crop:** full Deltas tab including instrument bar.

### 3. `iter-strip-finale.png` · used by `§07`

**Route:** Deltas tab → click a pair → wait for iters 1–4 to load
(takes ~60s total) → ∑ finale fires automatically.
**Crop:** Drift Narrative cube only, the 5-cell iter strip should be
fully populated (4 tier chips + finale chip with confidence/drift
numbers).

### 4. `conflict-mode-table.png` · used by `§08`

**Route:** Deltas tab → mode bar → click **conflict**.
**State:** at least 10 rows visible, with re-tier arrows
(`→ skip`, `→ keep`) on multiple rows, mix of `KEEP`/`MAYBE`/`SKIP`
tier chips visible.
**Crop:** left table only, including header row, no need to capture
sidebar.

### 5. `fidelity-mode-table.png` · used by `§08`

**Route:** Deltas tab → mode bar → click **fidelity**.
**State:** rows sorted by raw fidelity asc, fidelity bars (red →
yellow → green gradient) clearly visible across the rows. Capture
worst (red) rows at the top.
**Crop:** left table only.

### 6. `selected-pair-fidelity.png` · used by `§08`

**Route:** any mode → click a pair that has been evaluated (has a
fidelity score in conflict or fidelity mode).
**Crop:** Selected Pair cube only. Should show:
- badge `#NNN · fid 0.XX · c 0.XX`
- recommendation block with suggested tier + apply button
- 4-tier mode strip
- premise + correction blocks
- judges block inline (Q / truth / recon, color-coded by yes/no)
- manual-row at the bottom

### 7. `drag-select-popup.png` · used by `§02` or `§09`

**Route:** Deltas tab → click a pair → drag-select inside the
correction block in Selected Pair.
**State:** popup visible over the selected text with KEEP/MAYBE/SKIP/
THINK + cancel buttons.
**Crop:** include the highlighted text under the popup + the popup
itself.

### 8. `four-tier-strip.png` · used by `§08`

**Route:** any mode → click a pair → look at the 4-tier mode strip
below the recommendation block.
**Crop:** tight crop of just the 4 cells. Should show one cell
highlighted (the recommended tier).

### 9. `three-views-collage.png` · used by `§09` (optional, hero)

**Route:** make 3 separate screenshots and combine in any image
editor:
- Quiz tab open showing a labeled pair with span annotations
- Drift Inspector with a row selected and iter strip filled
- Fidelity mode showing the conflict/retag arrows

**Crop:** 3 panels stacked vertically with a thin divider line
between them. Width 1200px each. This is the closing illustration
under §09 — optional, can be skipped if too much work.

---

## After screenshots are added

Run these to verify references resolve:

```bash
# from repo root
grep -nE "docs/img/" README.md
ls -la docs/img/
```

Then `git add docs/img/*.png README.md CHANGELOG.md pyproject.toml`
and commit on this branch (`docs/three-views-and-fidelity`).
