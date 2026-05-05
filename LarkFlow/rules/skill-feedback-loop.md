# Skill Feedback Loop

> **One-page contract** describing how Phase 4 Reviewer findings turn into
> durable `skills/*.md` entries, so the same mistake never needs to be caught twice.

## Why this loop exists

Phase 4 Reviewer catches real violations every run. Without a closed loop, each
catch is a one-shot fix buried in a demand's git history — the next demand
re-introduces the same bug, and the Reviewer re-finds it. We fix this by
promoting recurring findings to the knowledge base under `skills/` and the
routing table under `rules/skill-routing.yaml`.

## The 4 steps

### 1 — Reviewer emits a structured block
Phase 4 Reviewer must wrap every finding that points to a **missing or unclear
skill rule** (not a one-off typo) in the tag below. The block is the only
machine-readable output; freeform prose around it is fine.

```xml
<skill-feedback>
  <category>database|redis|http|auth|logging|...|biz/...</category>
  <severity>critical|high|medium</severity>
  <summary>One-line rule that would have prevented this bug.</summary>
  <evidence>
    path/to/file.go:42 — actual code snippet or a short quote
  </evidence>
  <suggested-skill>skills/xxx.md</suggested-skill>
  <gap-type>routing|content</gap-type>
  <injected-skills>skills/a.md, skills/b.md</injected-skills>
</skill-feedback>
```

Field semantics:
- `gap-type` = `routing` — `suggested-skill` was **not** in the `<skill-routing>` block the engine injected into Phase 2. Fix path: extend `tech_tags` enum in `agents/phase1_design.md` or the keyword fallback in `rules/skill-routing.yaml`.
- `gap-type` = `content` — `suggested-skill` **was** injected but the rule is missing / unclear in that file. Fix path: edit the `.md`.
- `injected-skills` — comma-separated paths from the `<skill-routing>` block in this review's system prompt, so the digest can double-check the agent's classification.

Multiple blocks per review are expected; emit one per distinct rule. The engine auto-harvests blocks after every Phase 4 run into `tmp/<demand_id>/skill_feedback.jsonl` (per-demand audit) and `telemetry/skill_feedback.jsonl` (append-only global log).

### 2 — Human / lead triages (weekly, ~15 min)
Run the digest instead of grepping logs:

```
python LarkFlow/scripts/skill_feedback_digest.py --since 7d --out LarkFlow/docs/SKILL_BACKLOG.md
```

The digest buckets findings into **routing gaps** (fix the routing) vs **content gaps** (edit the skill md) and counts recurrences. For each bucket decide:

- **Promote** — same category has appeared ≥2 times, or severity is `critical`.
- **Hold** — one-off; keep in the backlog for now.
- **Drop** — false positive from Reviewer.

Only Promote items move to step 3.

### 3 — Open a `skills/` PR
For each promoted block:

1. If the `suggested-skill` file exists — add a new 🔴/🟡 section to it,
   preserving the existing structure (`## <severity>: <rule>` + ❌/✅ Go code).
2. If it does not exist — create a new `skills/<layer>/<topic>.md` (choose the
   `<layer>` by concern: `lang/` for language rules, `transport/` for API
   protocols, `infra/` for external dependencies, `governance/` for cross-cutting
   security/observability/resilience, `domain/` for business knowledge) using
   `infra/database.md` as the template.
3. Update `rules/skill-routing.yaml`: ensure the new skill is reachable via the
   right `keywords`; add the keyword if missing. Mirror the change in
   `rules/skill-routing.md`.
4. If a regression test would help, add a fixture under
   `tests/prompts/fixtures/` that asserts the rule via
   `expect_phase2_required_patterns` / `forbidden_patterns`.

PR title: `skills: promote <category> rule — <summary>` so it's greppable.

### 4 — Close the loop back to Phase 4
When a block is promoted, link the PR in the original review thread. The next
Phase 4 run on a similar demand now reads the new skill via the routing table
and catches the bug *before* human review — the loop is closed.

## What does NOT go into skills/

- Single-line typo fixes, rename suggestions, doc-only changes.
- Project-specific wiring (e.g., "call `internal/foo.Bar()` here") — that is
  design, not a reusable skill.
- Style preferences without a concrete bug class behind them.

## Automation (future, not required now)

A later iteration can:

- Parse `<skill-feedback>` blocks automatically and open a draft PR.
- Track `category` frequencies to auto-surface "promote candidates" in a weekly
  digest.

For now, steps 2–3 are deliberately manual so a human judges quality before
the knowledge base grows.
