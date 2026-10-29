---
name: claude-code-token-coach
description: >
  Audit a developer's own Claude Code session history, check model and effort
  fit for their work, and grade token, context and cost habits. Use for requests
  to review Claude Code usage, cache efficiency, context growth or spend
  (including "run cc-coach" and "check my claude usage"), and to justify a
  budget or spend-cap increase. Produces local coaching and IT reports plus
  an optional HelpDesk budget packet with a repo check-in audit. Report
  submission is manual; billing and commit lookups send the configured email.
---

# Claude Code Token Coach

This skill does two related jobs from one analysis of a developer's **own past
Claude Code sessions**:

1. **Coaching** — checks model and effort fit for the work, aiming for the best
   successful result per dollar across intelligence, performance and price.
   Retains the deterministic habit scorecard and adds unscored fit guidance.
2. **Budget requests** — when the developer is asking for a higher spend cap, it
   assembles a one-page **budget-request packet** for the IT HelpDesk: spend,
   the efficiency scorecard, a **repo check-in audit** (which repos the budget
   is being spent on), the developer's justification, and remediation
   commitments, ending in an Approve / Approve-with-conditions / Coach-first
   recommendation.

Optimize for successful results per dollar, with acceptable quality and latency.
Token counts alone cannot establish value. The existing habit scorecard remains
the deterministic input to cap decisions; model/effort fit is separate coaching,
not a new approval criterion.

## When to use

- "review my token usage", "score my Claude Code habits", "why does my context
  fill up", "am I leveraging the cache", "how do I cut my Claude Code bill" →
  produce the **coaching report**.
- "I hit my cap / need a budget increase", "justify my Claude Code spend to IT",
  "raise my limit" → produce the coaching report **and** the **budget packet**.
- "run claude coach skill", "run cc-coach", "check my claude usage", "how much have I spent on claude this month" → produce the **coaching report** (budget packet optional)

This is a retrospective analysis of historical behavior, not in-flight prompt
optimization.

## Data source

Claude Code stores every session as JSONL — one JSON object per line — under:

```
~/.claude/projects/<encoded-project-path>/<session-id>.jsonl
```

Key fields the analyzer relies on (all confirmed present):

- `type` discriminates `user` / `assistant` / `system` entries.
- `assistant` entries carry `message.usage` (`input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`) and `message.model`.
- `message.content` blocks: `text`, `thinking`, `tool_use` (`{id,name,input}`),
  and `tool_result` (`{tool_use_id,content,is_error}`) inside later `user` entries.
- `cwd` and `gitBranch` on each entry → which **repo/branch** the work happened in.
  Repo attribution resolves the actual git project root for each `cwd`
  (walking up for the nearest `.git`), not just the raw working-directory
  name — so a workspace folder containing several nested repos, or a monorepo
  with `cwd` varying across sub-packages, is attributed correctly instead of
  collapsing into one folder or fragmenting into several (see
  `resolve_git_root()` in `analyze.py`). When no `.git` is found (e.g. the
  transcript was exported from another machine and the directory doesn't
  exist locally), it falls back to the basename of `cwd`, same as before.
- `system` entries mark compaction boundaries.

When present, transcripts are read locally and are not uploaded by the analyzer.

**Authoritative spend** is fetched automatically: `analyze.py` calls the Athena
cc-coach spend API (`analyze.py:SPEND_API_BASE` — the athenaupdater-api proxy
over the Anthropic cost report) using the developer's configured email, and
attaches the billing figure to both reports and `report.json`
(`authoritative_spend`). If the API is unreachable (off VPN, outage), the
reports fall back to the transcript estimate and say so explicitly — the
estimate is a relative signal, not a billing number.

## Workflow

### Step 0 — Check fit before model advice

Read [references/model-fit.md](references/model-fit.md) for the workload table
and evidence rules. Use the analyzer's `model_fit` workload hints and the user's
stated work to identify task type, complexity, quality needs and latency needs.
These hints are provisional: a short answer or missing thinking block does not
prove a task was easy. If evidence is insufficient, say fit is unknown and keep
advice conditional; ask about the work only if needed for a specific recommendation.
Do not default every developer to Sonnet or reward lower token counts alone.

### Step 1 — Analyze (always)

Locate transcripts (default `~/.claude/projects`; scope to a project/session if
named). The analyzer does all parsing and scoring deterministically — do not
eyeball token math:

Use the platform wrapper — it verifies Python 3 and `reportlab` are present
before running, and prints a clear install instruction if either is missing.

**macOS / Linux (`run.sh`):**
```bash
bash run.sh --days 30 --json-out report.json
# narrower scope options:
bash run.sh --project ~/.claude/projects/-Users-me-myapp
bash run.sh --session path/to/<id>.jsonl
```

**Windows (`run.ps1`):**
```powershell
.\run.ps1 --days 30 --json-out report.json
# narrower scope options:
.\run.ps1 --project ~\.claude\projects\-Users-me-myapp
.\run.ps1 --session path\to\<id>.jsonl
```

Always pass `--days 30` for the standard report — it covers **every project**
active in the window. (With no scope flags the analyzer also defaults to all
projects / last 30 days; it must never analyze a subset of projects silently.)

All arguments are forwarded to `analyze.py` unchanged. If `python3` is not on
`PATH`, the wrapper exits immediately with OS-specific install instructions.
If `reportlab` is missing, PDF is skipped gracefully — the `.md` files and JSON
are still produced.

**Every run attempts to write four report files** to the working directory (or
`--out-dir` if given), and prints each path to stderr:

| File | Audience | Contents |
| --- | --- | --- |
| `User.md` / `User.pdf` | the developer | full coaching report — token totals, cost, repos, scorecard, per-practice findings |
| `IT.md` / `IT.pdf` | manager / IT HelpDesk | spend, repo activity, efficiency verdict — no session details, paths, or prompt contents |

`report.json` is the machine feed for the budget packet (step 4).

There is **no** `report.md` or `report.pdf` — those names are obsolete. The four
files above are the only reports. Do not invent or link any other filename.

Each run also updates `history.json` at a **fixed per-user location**,
`~/.cc-coach/history.json` — **not** alongside the four reports, and not
affected by `--out-dir` or the current working directory — capped at the most
recent 12 runs, so the *next* run can show a score trend. The fixed location
is deliberate: the skill is distributed as several separate copies (plugin
cache, a checked-out repo, `~/.claude/skills/`) and can be invoked from any
working directory, and the whole point of a trend is one continuous history
regardless of which copy or directory a given run happens from — a
per-directory default would silently fragment it. It is bookkeeping, not a
report — never list it in step 2a, never paste it, and never attach it to a
HelpDesk ticket.

### Step 2 — Present the reports (always)

After the script completes, do the following in order. Use the **exact** paths
the script printed to stderr (`User report → …`, `IT report → …`,
`PDF written → …`) — never guess or alter filenames or casing.

**2a — Notify the user of all four generated files.**
List every file that was written, linked as markdown so the user can click to
open them. List all four when generated — both the developer report and the IT report:

> Reports saved:
> - [User.md](User.md) — your full coaching report
> - [User.pdf](User.pdf) — PDF version, ready to share
> - [IT.md](IT.md) — manager / IT HelpDesk view (spend + verdict, no session details)
> - [IT.pdf](IT.pdf) — PDF version of the IT report

If a PDF is missing because `reportlab` is not installed, say so and link only
the `.md` files — never link a file the script did not write.

**2b — Give a short coaching summary in chat.**
Show the grade and trend if available, authoritative spend with its billing
period (or a clearly labeled transcript estimate), the workload fit finding,
and at most three actions. Prioritize known older-version spend, then model and
effort fit, and read cache/context together. Unknown task type or effort must
stay unknown. A strong cache grade is not evidence of overall efficiency when
context is oversized or auto-compacting. Link the full report for token, model,
repo and practice tables; paste the full report only if the developer requests it.
Do not paste `IT.md` by default.

**2c — Surface the ready-to-attach IT report (always close with this).**
`IT.pdf` is already generated — it IS the document IT needs to approve a cap
increase, so there is nothing more to assemble for the common case. Close every
run with a clear, actionable call-to-action (a real instruction, **not** a vague
either/or question):

> 📎 **Requesting a budget / cap increase?** Your IT report is ready.
> **Open a ticket with your IT HelpDesk and attach [IT.pdf](IT.pdf)**, including
> your current cap, requested cap, and a one-line justification in the ticket.
> That attachment is what IT uses to approve the increase — no other document is
> required.

Hard rules for the closing message:
- **Never** ask "Want me to assemble the IT budget-request packet, or paste the
  full coaching report?" — provide the brief summary (2b) and surface the
  `IT.pdf` instruction; the complete reports are already saved.
- The action is **open a HelpDesk ticket and attach `IT.pdf`** — do **not** tell
  the user to email it. Mention `IT.pdf` by its exact filename and link it.
- The richer `budget-request-packet.md` (Steps 3–4) is **optional/advanced** —
  offer it only if the developer explicitly wants the fuller one-pager. For a
  normal cap-increase request, attaching `IT.pdf` to a HelpDesk ticket is
  sufficient.

### Step 3 — (Optional) Gather inputs for the fuller budget packet

Only if the developer explicitly asks for more than `IT.pdf`. Gather inputs:

Ask the developer for:

- **current cap** and **requested cap**,
- a short **justification** (why more budget is needed: workload, role, project).

Spend is resolved automatically: `--actual-spend` (if the developer supplies a
figure) > the `authoritative_spend` already embedded in `report.json` by
analyze.py > the transcript estimate (clearly labelled). Do not ask the
developer for their spend unless all automatic sources failed.

### Step 4 — Build the budget packet

```bash
python3 scripts/build_packet.py --report report.json \
  --dev "<name>" --period "<e.g. May 2026>" \
  --current-cap <n> --requested-cap <n> --actual-spend <n> \
  --justification "<text>" --helpdesk "<target>" \
  --out-md budget-request-packet.md --out-ticket helpdesk-ticket.txt
```

This emits `budget-request-packet.md` (the one-pager: spend, scorecard, repo
audit, justification, auto-derived remediation commitments, recommendation, and
an **approval-routing** line) and `helpdesk-ticket.txt` (a pre-filled ticket
body). Remediation commitments are generated from the developer's weakest scored
practices.

The recommendation has two parts: an **efficiency verdict** from the grade
(Approve / Approve-with-conditions / Coach-first) and an **approval route** from
the size of the ask — increases up to the self-approve increment are
team/manager-approvable; larger ones escalate to the named approver. Both are
tunable in `build_packet.py:APPROVAL_POLICY` (current org policy: cap 150, +150
self-approvable, beyond that → Joe).

Generation is recorded to an audit log (`log.json`, default; `--log-out` to
change, `--no-log` to skip). Each entry holds the spend figures, spend source
(authoritative vs. estimate), grade, recommendation, approval route, and a
**SHA-256 of the packet** — never code, prompt contents, or secrets.

### Step 5 — Submission is manual, by the developer

**The skill never submits reports.** It only generates the reports; routing them
to the HelpDesk is a manual step the developer performs themselves:

- For a standard cap increase: the developer opens a ticket with the IT
  HelpDesk and attaches `IT.pdf` (the 2c call-to-action already tells them
  this), including current cap, requested cap, and a one-line justification.
- If the fuller packet was built (steps 3–4): they attach
  `budget-request-packet.md` and/or paste `helpdesk-ticket.txt` into the
  ticket themselves, after reviewing.

Do not offer to send, email, or submit anything on the developer's behalf, and
do not describe any automated submission channel — none exists.

## What is and isn't trackable

Be honest about this — it's part of the value.

**Scored (developer-controlled habits):** cache hit rate, targeted vs.
whole-file reads, oversized tool outputs, context discipline, model
right-sizing + estimated cost.

**Observed but not scored (Claude's in-the-moment behavior):** tool error rate,
native search vs. `cat`/`grep`, redundant re-reads, parallel batching, subagent
use. The developer
can't control these per-call, so they never affect the grade — but when a
pattern is frequent the report suggests the exact CLAUDE.md steering rule to add.
This separation is deliberate: a budget decision must not penalize a developer
for something they couldn't control.

**Repo audit:** captures git activity (`cwd`, `gitBranch`, `git commit`/`push`)
run **through Claude Code only**. Commits made outside Claude Code won't appear.
For authoritative check-in history, GitHub/GitLab is the source of truth and can
be layered in later.

**Limited evidence:** prompt text can suggest workload type, but transcripts
cannot prove task difficulty, success, rework, or result per dollar. Effort is
reported only when explicitly logged; never infer it from answer length or
thinking blocks. The existing model-efficiency score is a structural heuristic,
not proof a particular turn needed a different model. Model-version and effort
advice in `model_fit` is unscored and must not alter cap recommendations.

See `references/best-practices.md` for the full catalog, each metric definition,
the thresholds, and the weighting. Read it before customizing thresholds or
explaining the methodology.

## Scoring model

Each scored practice gets 0–100 and a letter (A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60,
F < 60); the overall grade is the weighted average of scored practices only.
Observations never affect the grade. Weights live in `analyze.py:WEIGHTS`,
thresholds in `analyze.py:THRESHOLDS`, version prices in `model_fit.py:RATES` (unknown-version fallbacks in
`analyze.py:PRICING`) — all meant
to be tuned per team. The packet's recommendation is derived from the overall
grade tempered by the size of the requested increase (`build_packet.py:recommend`).

The trend line in `User.md`/`report.json` compares raw scores across runs via
`history.json`. A change to `WEIGHTS`/`THRESHOLDS`/a scoring formula changes
what a given score *means* — e.g. the 2026-07 removal of `tool_error_rate`
from scoring (see the `WEIGHTS` comment in `analyze.py`) shifted every
practice's weight. A trend delta spanning such a change reflects the
methodology change, not the developer's habits; see
`references/best-practices.md` for the full caveat.

## Governance & privacy

- **Network disclosure:** on each normal run, the analyzer sends the configured
  developer email and billing month/year to the Athena spend API and the
  AI-commits API (possibly querying the prior month too). The background spend
  hook also sends email when its scheduled check runs. Source code, prompts and
  transcripts are not uploaded. Report generation and parsing are local.
- **The skill never submits reports.** The developer
  reviews the output and attaches `IT.pdf` (or the packet) to a HelpDesk
  ticket themselves. Reports are not submitted automatically; the API lookups above still occur.
- **Transparency over monitoring** — the developer sees everything that will
  reach IT before they submit it. The repo audit carries repo names, branches,
  and counts only — **never code contents**.
- **Estimated ≠ authoritative spend** — the transcript dollar figure is a
  relative efficiency signal; reconcile against billing before a final cap decision.

## Outputs

- `User.md` / `User.pdf` — developer coaching report (always).
- `IT.md` / `IT.pdf` — manager / IT HelpDesk report: spend, repo activity,
  efficiency verdict; no session details, paths, or prompt contents (always).
- `report.json` — machine feed for the budget packet (always).
- `budget-request-packet.md` — one-page IT/HelpDesk packet (optional, budget requests).
- `helpdesk-ticket.txt` — pre-filled ticket body the developer can paste into
  their HelpDesk ticket (optional, budget requests).
- `log.json` — append-only audit log of packet generation. Metrics + packet
  hash only; no code or secrets.
- `history.json` — run-history (scores only, capped at the most recent N
  runs, default 12) powering the trend line (always, unless `--no-history`),
  at the fixed per-user path `~/.cc-coach/history.json` regardless of
  `--out-dir`/cwd/which copy of the skill ran. Same privacy guarantee as the
  reports: no code, prompts, paths, or session IDs. `--no-history` skips it
  entirely; `--history-limit` changes the cap; `--history-out` overrides the
  path for a single run (e.g. testing) without touching the real history.

All outputs stay on the developer's machine — submission to the HelpDesk is
always a manual step by the developer (see step 5).

## Testing

`scripts/make_fixture.py <dir>` writes synthetic two-repo sessions with git
check-ins so you can exercise both the coaching and budget paths without real
transcripts. See `samples/` for historical example outputs.

Run the offline model-fit regression checks from the skill directory:
`python3 -m unittest discover -s scripts -p 'test_*.py'`.
They cover version prices, the Haiku prompt-size boundary, unknown effort,
subagent aggregation, unscored fit findings and concise output with full reports.
No live billing or commit API calls are made by these tests.
