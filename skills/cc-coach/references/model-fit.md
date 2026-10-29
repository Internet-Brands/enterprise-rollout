# Model and effort fit

Aim for successful results per dollar, balancing intelligence, performance
(latency and completion time), and price. Choose for the developer's work;
a low token count or small model is not a success metric by itself.

## Fit check

Identify the workload from the user's stated task and analyzer workload hints.
Confirm complexity, quality needs, latency needs and outcome before suggesting
a change. Hints use prompt keywords and can be wrong (including quoted text);
they do not establish task boundaries or difficulty. Subagent workloads remain
unknown. Missing effort remains unknown; visible thinking and output length
cannot establish the configured effort.

These are coaching starting points, not benchmark conclusions:

| Type of work | Candidate model | Starting effort |
|---|---|---|
| Mechanical edits, extraction, formatting | Haiku 5.5 or Sonnet 5.5 | low |
| Well-specified implementation and tests | Sonnet 5.5 or Opus 5.5 | medium |
| Architecture, difficult debugging, broad refactors | Opus 5.5 | high |
| Long-horizon reasoning with measured quality gaps | Opus 5.5; Fable 5.1 if needed | high; xhigh/max only after evaluation |
| Insufficient evidence | Confirm the work | unknown |

For routine work, try lowering effort on a capable model before switching to a
smaller one. Compare quality, retries, end-to-end latency and total task spend.
A strong model at lower effort can have a similar task cost to a smaller model;
there is no guaranteed price equivalence or fixed effort savings percentage.
Effort changes token use, not list price per token. Never lower effort for a
hard task solely to improve the token score.

## Older-version spend

The analyzer recognizes known versioned IDs, including dated/platform forms,
and reports spend on versions older than the maintained current tier. Review
same-tier upgrades first. Unknown versions and aliases are not assumed old.
Same-token savings compare list prices with identical usage; tokenization,
reasoning, cache behavior, retries and discounts can change actual task cost.
Do not promise a no-tradeoff upgrade: confirm availability and compatibility,
then check representative tasks. No model settings change automatically.

Version prices and current tier IDs live in `scripts/model_fit.py`; unknown
version fallback rates remain in `analyze.py:PRICING`. Estimates account for
logged one-hour cache writes and Haiku 5.5's prompt-size price boundary. They
are API list-rate scenarios, not billing; billing remains authoritative.

## Cache and context together

Read cache share alongside peak single-turn input, auto-compacted sessions,
and the context-discipline score. One long session may achieve excellent cache
reuse while repeatedly billing a large prefix. A high cache score alone does
not establish efficiency. Use `/clear` between unrelated tasks, or a focused
`/compact` when continuing related work. Intentional large tasks need context.

## Scope and implementation

- Skill instructions take effect when installed: fit-first advice, short chat
  summaries, truthful privacy disclosure, secure credential setup guidance.
- Analyzer changes in this release: version-aware estimates, older-version
  spend, prompt-derived workload hints, explicitly logged effort (otherwise
  unknown), joint cache/context interpretation in `User.md` and `report.json`,
  and concise stdout. Full reports and repo evidence remain saved.
- The historical model score still flags short Opus responses without tools
  or visible thinking. It cannot establish fit. These new checks are unscored;
  weights, scoring formulas, grade thresholds, caps and approval policy are
  unchanged. Do not use these observations to override the budget verdict.
- Task success, rework and end-to-end latency are not measured. Result per
  dollar is the coaching objective, not a claimed analyzer measurement.

Verified 2026-10-29. Recheck these primary sources when updating the model table,
prices or effort guidance:

- [Anthropic model lineup](https://platform.claude.com/docs/en/models/overview)
- [Effort behavior and model-specific guidance](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Version prices and cache multipliers](https://platform.claude.com/docs/en/about-claude/pricing)
