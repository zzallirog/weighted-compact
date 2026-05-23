## What & why

<!-- One paragraph describing the change and linking the relevant issue (e.g. "Closes #N"). Explain the motivation, not just the mechanics. -->

## Architectural compliance checklist

- [ ] No network listener / cloud sync / telemetry / auto-injection added
- [ ] No substrate writes from external clients (read-only MCP / IDE / API)
- [ ] No new always-on daemon (one-shot CLI verbs preferred)
- [ ] `scripts/leak-scan.sh` clean (substrate filenames + `/home/*` paths absent from diff)
- [ ] If touching `.npz` schema, `SCHEMA_VER` bumped in the relevant module

## Test plan

<!-- Bulleted checklist of what you tested manually or in CI. -->

- [ ] <!-- e.g. `weighted-compact compat` returns no errors on a fresh venv -->
- [ ] <!-- e.g. labeler loads at :18890/, pairs visible, label saves -->
- [ ] <!-- e.g. `weighted-compact qa-gate` completes without traceback -->

```bash
# Run the test suite (synthetic fixtures only, no real data required):
pytest tests/ -x -q
```

## Notes for the maintainer

<!-- Optional. Anything the reviewer should read before looking at the diff: surprising edge-cases, decisions you considered and rejected, follow-up issues you intend to file. Delete this section if empty. -->
