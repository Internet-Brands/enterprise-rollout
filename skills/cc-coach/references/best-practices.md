# Token-optimization best practices: catalog, signals, and rubric

This is the methodology behind `scripts/analyze.py`. Practices are split into
two tiers, and the distinction matters:

- **Scored practices** — habits the *developer* directly controls: session
  hygiene (`/clear`, `/compact`), model choice (`/model`), and how they phrase
  asks. These produce the grade.
- **Agent behavior observations** — Claude's own in-the-moment choices (which
  tools it picks, whether it batches calls, re-reads files, spawns subagents).
  The developer can't control these per-call, so grading them would be
  misleading. They are reported unscored, and when a pattern is frequent the
  report suggests the one real lever: a steering rule in CLAUDE.md.

Weights sum to 100 across scored practices and live in `analyze.py:WEIGHTS`.
Thresholds live in `analyze.py:THRESHOLDS`; version prices in
`model_fit.py:RATES`, with unknown-version fallbacks in `analyze.py:PRICING`.
All are meant to be tuned per team.

## Contents

Scored: 1. Cache efficiency (28) · 2. Targeted reads (20) · 3. Output size
discipline (19) · 4. Context discipline (17) · 5. Model efficiency (16)

Observations (unscored): 6. Tool error rate · 7. Native search · 8. Redundant
reads · 9. Parallel batching · 10. Subagent offloading

11. Partially / not trackable (qualitative notes)

---

# Scored practices

## 1. Cache efficiency — weight 28

**Why.** Prompt caching reduces input cost. Cache-read multipliers vary by
version; a five-minute cache write costs ~25% more than fresh input. If your stable prefix
(system prompt, CLAUDE.md, tool defs, earlier turns) stays put, most input
tokens come back as cheap cache reads. Churning the prefix — swapping MCP
servers mid-session, editing CLAUDE.md mid-task, frequent restarts — forces
re-creation at full freight.

**User lever.** Keep CLAUDE.md and the tool/MCP set stable within a session;
finish a task before reconfiguring.

**Signal.** Across all `assistant` turns, cache-read share =
`cache_read / (cache_read + cache_creation + input)`.

**Score.** `min(100, share / 0.90 * 100)` — 90%+ read share earns full marks.

**Interpret jointly.** A long session can score well here while carrying an
oversized cached prefix on every turn. Read context discipline, peak window and
auto-compaction alongside cache share. The analyzer adds an unscored joint
interpretation; neither scoring formula changes.

## 2. Targeted reads — weight 20

**Why.** Reading a whole large file pulls every line into context (and into the
cache write). The developer steers this: "look at how `login()` validates
tokens" produces a scoped read; "read auth.py and tell me what you think"
produces a whole-file dump.

**User lever.** Phrase asks around symbols/behaviors, not whole files; say
"just the relevant part" when pointing Claude at big files.

**Signal.** `Read` results above `large_read_tokens` (default 2000, ~4
chars/token) count as large; `offset`/`limit` reads are bounded.

**Score.** `(1 − large_reads / reads) * 100`.

## 3. Output size discipline — weight 19

**Why.** Tool outputs land in context verbatim and get re-billed every later
turn. One unfiltered test run or build log can cost more than the work itself.
The developer steers this: "run the tests and show failures only" vs "run the
tests".

**User lever.** Ask for filtered output; put output-capping rules in CLAUDE.md
(e.g. "pipe long command output through tail -50").

**Signal.** `tool_result` blocks above `oversized_output_tokens` (default 5000).

**Score.** `100 − (oversized/total) * 500`, floored at 0.

## 4. Context discipline — weight 17

**Why.** Letting one session accumulate unrelated work bloats every subsequent
turn and eventually triggers auto-compaction, which is lossy and itself
token-heavy. This is the most directly user-controlled practice there is:
`/clear` between unrelated tasks resets context to near zero.

**User lever.** `/clear` between tasks; `/compact <focus note>` before being
forced into auto-compaction.

**Signal.** Share of sessions that hit **auto**-compaction (from
`compactMetadata.trigger` — a manual `/compact` is deliberate hygiene and is
shown but never penalized), plus the peak **single-turn context window**
(`input + cache_read + cache_creation` on one turn — not a cumulative sum,
which would grow with session length rather than context size).

**Score.** Start at 100; −(auto-compaction session rate × 30, cap −30);
−20 if the peak single-turn window exceeds `big_session_tokens`
(default 500,000).

## 5. Model efficiency / right-sizing — weight 16

**Why.** Model and effort should fit the work. The objective is successful
results per dollar across quality, latency and price, not minimum token count.
See [model-fit.md](model-fit.md) before giving model advice.

**User lever.** Choose a current model and appropriate effort based on workload.
For routine tasks, compare a stronger model at lower effort with a smaller model.

**Legacy scoring signal (unchanged).** An Opus turn with no tools, no visible
thinking, and fewer than `simple_turn_output_tokens` (400) output tokens is
flagged for review. This cannot prove the task was easy; a short answer can
require difficult reasoning. The candidate price comparison uses Sonnet 5.5
with identical token usage; it is not measured savings or an automatic switch.

**Score.** `100 − (flagged/opus_turns) * 100`; no Opus usage → 100 under this
heuristic. That score does not establish good fit or economical outcomes.

**Unscored fit assessment.** `model_fit` in `report.json` and `User.md` includes
prompt-derived workload hints, explicitly logged effort (otherwise unknown),
older-version spend, and a cache/context interpretation. No new observations
change grades or budget verdicts. Task success, rework and end-to-end latency
are not measured; do not claim a measured result-per-dollar ranking.

**Pricing maintenance.** `model_fit.py:RATES` stores version-specific rates,
`CURRENT` stores maintained tier versions, and `analyze.py:PRICING` provides
historical tier fallbacks when exact pricing is unknown. Current cache-read
multipliers and logged cache-write durations are accounted for. Review the
linked official pricing source in [model-fit.md](model-fit.md) before updating.
Dollar figures remain notional API-equivalent estimates, not billing.

---

# Agent behavior observations (unscored)

These measure Claude's autonomous choices. They appear in a separate report
section with no grade. When frequent (internal score < 80), the report shows
the worst offenders and the suggested CLAUDE.md steering rule — that's the
developer's only real lever here.

## 6. Tool error rate

**Why it matters.** Every failed tool call costs a full round-trip: the call,
the error, and the retry all re-send context.

**Why unscored (changed 2026-07).** Tool calls are issued by Claude, not the
developer — per this doc's own rule, that puts them in this tier. The
developer's indirect influence (vague asks, stale context) is already scored
via context discipline and cache efficiency; scoring the downstream symptom
double-counted it. The reported figure also excludes noise: user permission
denials, environmental failures (network/DNS/TLS/auth/VPN/5xx), Claude's own
path-guesses and unread-file edits, and expected-nonzero Bash (tsc/eslint).

**Signal.** Share of `tool_result` blocks with `is_error: true` after the
noise filter.

**Suggested CLAUDE.md line.** "Re-read a file before editing it if it may have
changed, and verify paths with Glob/Grep before acting."

## 7. Native search over Bash

**Why it matters.** `cat`/`grep`/`find` via Bash return raw, unbounded output;
native Grep/Glob/Read are scoped and cache-friendlier.

**Signal.** Bash commands matching
`\b(cat|grep|find|ls|head|tail|sed|awk|rg)\b` as a share of Bash calls.

**Suggested CLAUDE.md line.** "Prefer the Grep/Glob/Read tools over shell
`cat`/`grep`/`find`/`ls` for searching and reading files."

## 8. Redundant reads

**Why it matters.** Re-reading a file already in context re-sends it for no new
information.

**Signal.** A second `Read` of the same path with no intervening
`Edit`/`Write`/`NotebookEdit` to that path.

**Suggested CLAUDE.md line.** "Do not re-read files already in context unless
they have changed on disk."

## 9. Parallel batching

**Why it matters.** Independent tool calls issued in one turn share a single
round-trip; serializing them re-bills the context once per call.

**Signal.** Share of tool-bearing assistant messages with 2+ `tool_use` blocks.

**Suggested CLAUDE.md line.** "When tool calls are independent, issue them
together in a single message."

## 10. Subagent offloading

**Why it matters.** A subagent's noisy exploration stays in its own context;
only the conclusion returns.

**Signal.** Count of `Task` tool calls.

**Suggested CLAUDE.md line.** "For broad codebase exploration or multi-file
searches, delegate to a subagent and return only conclusions."

---

## 11. Partially / not trackable (qualitative notes only)

State these to the user as caveats; do not fabricate scores.

- **Prompt conciseness / turns-per-task.** No ground-truth task boundaries in
  the transcript, so verbosity can't be scored fairly.
- **CLAUDE.md bloat.** Lean CLAUDE.md (<~200 lines) matters but the file isn't
  reliably present in transcripts — suggest the user check its size directly.
- **MCP tool-definition overhead.** Many loaded MCP tools inflate the cached
  prefix, but schemas aren't always logged. Note as a thing to review.
- **Whether a specific Opus turn truly needed Opus.** The model-efficiency
  score is a structural heuristic, not a verdict.

---

## Repo attribution (repo check-in audit)

The repo table backing both the coaching report and the IT budget packet's
repo check-in audit is keyed off the actual git repository, not the raw `cwd`
string in the transcript. For each `cwd` seen, `analyze.py`'s
`resolve_git_root()` walks upward from `cwd` looking for a `.git` entry (a
directory for a normal repo, or a file for a submodule/worktree) and returns
the nearest ancestor that has one — that root is the bucket key, and its
basename is the display name shown in the tables.

- A workspace folder that contains several independent nested repos (e.g.
  `~/workspace/service-a`, `~/workspace/service-b`, each its own `.git`) is
  attributed as separate rows, keyed by each repo's own root — the shared
  parent folder is never used as a bucket by itself.
- A monorepo where `cwd` varies across sub-packages (`frontend/`, `backend/`,
  ...) collapses into a single row, keyed by the monorepo's root.
- If no `.git` is found within a bounded walk — including the common case of
  analyzing transcripts on a different machine than the one they were
  recorded on, where the referenced directories don't exist locally — the row
  falls back to the basename of `cwd`, same as the analyzer's historical
  behavior. The repo is still surfaced, never silently dropped.
- Lookups are memoized per unique `cwd` for the run, so this costs at most one
  filesystem walk per distinct working directory, not per transcript line.

---

## Tuning guide

- Weights: `analyze.py:WEIGHTS` (scored set; keep the sum at 100). Moving a
  practice between scored and observed = move its key between `WEIGHTS` and
  `OBSERVATIONS`.
- Thresholds: `analyze.py:THRESHOLDS`. Raising `large_read_tokens` makes
  targeted-reads more lenient; the `* N` multipliers set how fast a score
  drops to F.
- Prices: `model_fit.py:RATES`; unknown-version fallback: `analyze.py:PRICING`.

---

## History & trend tracking (`history.json`)

Each `analyze.py` run appends one entry — timestamp, analysis period, overall
score/grade, and the five scored practices' scores — to `history.json`,
capped at the most recent 12 runs by default (`--history-limit` to change,
`--no-history` to skip entirely). It is a plain JSON array, written via
load-modify-write, same pattern as `audit.py`'s `log.json` (append-only in
spirit, not JSONL) — see `write_history_entries()` in `analyze.py`. It never
contains code, prompt contents, file paths, or session-identifying detail —
scores and metadata only, the same privacy bar as `report.json`/`log.json`.

**Location is fixed, not derived from `--out-dir`/cwd.** The default path is
`DEFAULT_HISTORY_PATH` in `analyze.py` (`~/.cc-coach/history.json`), resolved
once per run in `main()` and never joined with `out_dir`. This is intentional:
the reports (`User.md`/`IT.md`/`report.json`) are per-run artifacts and
correctly follow `--out-dir`/cwd, but `history.json` is meant to be the one
continuous record across every invocation — regardless of which directory you
ran from, or which of the skill's several distributed copies (managed plugin
cache, a checked-out repo, `~/.claude/skills/`) executed it. Defaulting it to
`out_dir` (as an earlier version of this feature did) silently fragments the
trend into one disconnected file per directory/copy — exactly the kind of bug
that looks like "it's not tracking" rather than an obvious error. `--history-out`
exists precisely to opt out of the shared file for a single, isolated test run.

The next run's trend line is a plain per-key delta against the most recent
prior entry — see `build_trend()` in `analyze.py`. No prior entry (first run,
missing file, or a file that failed to parse as a JSON array) yields no trend
at all, never a false zero baseline. A corrupted `history.json` is logged as a
warning and overwritten with a fresh single-entry array rather than crashing
the run.

**Risk: methodology changes look like habit changes.** `history.json` carries
no ruleset-version field, so a trend delta spanning a change to
`WEIGHTS`/`THRESHOLDS`/a scoring formula (e.g. the 2026-07 removal of
`tool_error_rate` from scoring — see the `WEIGHTS` comment above) is
indistinguishable, from the stored entries alone, from a real change in the
developer's habits — there is no automatic detector for this. When you change
the scoring rules, note the date and the change here, the same way the
`tool_error_rate` removal is already documented, so anyone reading a
surprising trend swing can check whether it lines up with a methodology
change before reading it as a behavior signal.

---

# Budget-request context (Claude Code Token Coach)

When this analysis backs a budget/cap-increase request, two rules keep it fair
and defensible:

1. **Only scored practices gate the decision.** The unscored observations above
   measure Claude's own choices, not the developer's habits — they inform
   coaching but must not count against a budget request.
2. **The transcript cost is an estimate.** `analyze.py` computes notional
   API-equivalent cost from token usage × version-specific or fallback prices. For the actual cap decision,
   use authoritative spend from billing or the analytics dashboard
   (`claude.ai/analytics/claude-code` or `platform.claude.com/claude-code`) and
   pass it to `build_packet.py --actual-spend`. The estimate remains a valid
   *relative* efficiency signal.

The packet's recommendation (`build_packet.py:recommend`) maps the overall grade
to Approve (A/B), Approve-with-conditions (C, or a large ask), or Coach-first
(D/F), and is meant to be tuned to your org's risk tolerance.


## Timestamp windows (1.0.13)

A bounded report includes only entries timestamped within the requested rolling
UTC window (inclusive boundaries). Main and subagent transcripts use the same
bounds. Discovery considers all candidate files regardless of modification date,
so restored transcripts are not silently dropped. Missing/invalid dates are
excluded and counted; offset-free timestamps are interpreted as UTC. Sessions
with no included entries do not affect counts or scores. Earlier repo metadata
can provide attribution, but old tokens, tools, commits, compactions and model
usage are not counted. Tool/read/task observations begin within the window.

The no-flag default is 30 days across all projects. Explicit project/session
selection without `--days` retains full-history behavior and is labeled as such.
`analysis_window` in JSON records the requested bounds and timestamp policy.
Billing remains a separately labeled calendar-month figure, not a reconciled
rolling-window bill. No rubric weights, score formulas or approval rules change.

Before 1.0.13, `--days` selected files by mtime and counted their entire contents;
explicit `--session` bypassed that filter. Trend comparisons spanning this fix
can reflect corrected scope rather than improved or worsened habits. New history
entries record `period.basis = entry_timestamps`; old entries remain intact.
