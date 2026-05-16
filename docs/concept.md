# Concept

## What this is

A personal compaction substrate that learns from one person's Claude Code
sessions to decide what to keep, what to drop, and what to flag for
re-examination — instead of asking an LLM to summarize on the fly.

The core observation: when you tell Claude Code "let's compact this session
and keep going," the standard mechanism asks the model to produce a summary.
That summary is a single forward pass over your conversation, with no memory
of which parts mattered to *you*. It is a guess.

A better approach is to **build a substrate** — a per-turn vector
representation plus a per-pair importance score — and rebuild the working
context by selecting from the substrate. The selection criteria can be
trained on your own labels, your own correction signals, your own
disagreement patterns.

This is a workbench for that approach. It is not a finished product. The
substrate works; the classifier is one component of several that contribute
to the importance score, and the substrate is honest about that.

## What this is not

- **Not an agent-memory framework.** Agent-memory frameworks aim to give
  long-running agents recall over multiple conversations. weighted-compact
  operates within one session that is hitting a context limit. Different
  problem, different shape.

- **Not zero-configuration.** You have to install it, run a bootstrap,
  label twenty pairs, and look at the dashboard. If you want a tool that
  hides everything behind one button, this is not it. See
  [TencentDB-Agent-Memory](https://github.com/Tencent/TencentDB-Agent-Memory)
  for an excellent example of the zero-config approach.

- **Not multi-tenant.** Every install grows its own substrate from its own
  sessions. There is no shared model, no cloud sync, no federation. See
  [`invariants.md`](invariants.md) for why.

- **Not opinionated about your workflow.** It reads `~/.claude/projects/`
  if you use Claude Code, but the pair-extraction logic is generic; any
  conversation transcript in compatible JSONL can be ingested with a
  one-line shim.

## Why "weighted" and "compact"

- **Compact** — the goal is to fit a long session into the working context
  budget. The output is a compacted context, not a summary.
- **Weighted** — every span carries a continuous importance score derived
  from six independent signals, not a binary keep/drop verdict. The
  budget allocation is a weighted top-K, not a threshold cut.

The classifier exists to refine the weighting, not to gate it. If the
classifier fails or is missing, the substrate still produces a usable
weighting via density + misstep + recency. The pipeline degrades; it does
not break.

## Why human-in-the-loop

Three reasons.

1. **Stability with yourself over time.** What you considered worth keeping
   six months ago should still match what you consider worth keeping today,
   unless your priorities have genuinely shifted. The anti-drift sidebar
   shows you the five cosine-nearest prior labels so you can stay
   consistent. This is a feature, not a UX accident.

2. **Goodhart awareness.** If a single signal becomes the optimization
   target, the signal stops being a signal. The mixture is intentionally
   multi-source so no metric can be gamed without the others noticing.

3. **You should participate in compressing yourself.** When auto-compact
   happens to a Claude Code session, you have no agency in the decision.
   This tool is the opposite framing — you participate in designing the
   mechanism that compresses you. That is the whole point.
