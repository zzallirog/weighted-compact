# Support

For usage questions, run `weighted-compact compat --json` and check
`docs/troubleshoot.md` first — most configuration issues are diagnosed
instantly that way. If neither resolves your question, use the table below
to pick the right channel.

| Channel | Best for | Response SLA (best-effort) |
|---|---|---|
| [GitHub Discussions](https://github.com/zzallirog/weighted-compact/discussions) | Architectural / "should I do X" questions | When active |
| [GitHub Issues](https://github.com/zzallirog/weighted-compact/issues) | Concrete bugs, feature proposals against the pre-set architecture | 1–2 days for triage |
| `weighted-compact compat --json` | First-line diagnostic before opening anything | Instant |
| [`docs/troubleshoot.md`](docs/troubleshoot.md) | Symptom → fix lookup | Instant |

weighted-compact follows an architecture-pre-set contribution model — the
locked invariants (vectors-first, CAPTCHA labeling, no-harness-dep) are
not up for debate in individual PRs; see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
for how to propose architectural changes.
