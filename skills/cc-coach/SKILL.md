---
name: claude-code-token-coach
description: >
  Audit a developer's own Claude Code session history, grade how well they
  follow token-optimization best practices, and — when they are requesting a
  budget/cap increase — assemble a budget-request packet for the IT HelpDesk.
  Use this skill whenever the user wants to review, audit, improve, or
  understand their Claude Code token/context/cost usage ("how am I doing on
  tokens", "review my Claude Code usage", "am I using the cache well", "why is
  my context filling up"), AND whenever a developer needs to request more Claude
  Code budget or a higher spend cap ("request a budget increase", "I hit my
  Claude Code cap", "justify my Claude Code spend to IT", "raise my limit").
  Produces a coaching report for the developer and, on request, an IT/HelpDesk
  budget packet plus a repo check-in audit. Trigger even if the user doesn't say
  the word "skill". " Run cc-coach skill" or "run claude coach skill" or
  "check my claude usage" or "how much have I spent on claude"
---

# Claude Code Token Coach

This skill does two related jobs from one analysis of a developer's **own past
Claude Code sessions**:

1. **Coaching** — grades how well the developer follows token-optimization best
   practices and returns actionable, per-practice feedback (the original
   token-optimizer behavior).
2. **Budget requests** — when the developer is asking for a higher spend cap, it
   assembles a one-page **budget-request packet** for the IT HelpDesk: spend,
   the efficiency scorecard, a **repo check-in audit** (which repos the budget
   is being spent on), the developer's justification, and remediation
   commitments, ending in an Approve / Approve-with-conditions / Coach-first
   recommendation.

The point is not to scold about raw token counts — counts depend on task size.
It surfaces *habits* that waste tokens regardless of task, and gives IT a
defensible, deterministic basis for a cap decision.

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
- `system` entries mark compaction boundaries.

This local source is always available and stays on the developer's machine.

**Authoritative spend** is fetched automatically: `analyze.py` calls the Athena
cc-coach spend API (`analyze.py:SPEND_API_BASE` — the athenaupdater-api proxy
over the Anthropic cost report) using the developer's configured email, and
attaches the billing figure to both reports and `report.json`
(`authoritative_spend`). If the API is unreachable (off VPN, outage), the
reports fall back to the transcript estimate and say so explicitly — the
estimate is a relative signal, not a billing number.

## Workflow

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

**Every run writes exactly four report files** to the working directory (or
`--out-dir` if given), and prints each path to stderr:

| File | Audience | Contents |
| --- | --- | --- |
| `User.md` / `User.pdf` | the developer | full coaching report — token totals, cost, repos, scorecard, per-practice findings |
| `IT.md` / `IT.pdf` | manager / IT HelpDesk | spend, repo activity, efficiency verdict — no session details, paths, or prompt contents |

`report.json` is the machine feed for the budget packet (step 4).

There is **no** `report.md` or `report.pdf` — those names are obsolete. The four
files above are the only reports. Do not invent or link any other filename.

### Step 2 — Present the reports (always)

After the script completes, do the following in order. Use the **exact** paths
the script printed to stderr (`User report → …`, `IT report → …`,
`PDF written → …`) — never guess or alter filenames or casing.

**2a — Notify the user of all four generated files.**
List every file that was written, linked as markdown so the user can click to
open them. Always list all four — both the developer report and the IT report:

> Reports saved:
> - [User.md](User.md) — your full coaching report
> - [User.pdf](User.pdf) — PDF version, ready to share
> - [IT.md](IT.md) — manager / IT HelpDesk view (spend + verdict, no session details)
> - [IT.pdf](IT.pdf) — PDF version of the IT report

If a PDF is missing because `reportlab` is not installed, say so and link only
the `.md` files — never link a file the script did not write.

**2b — Paste the full developer report (`User.md`) verbatim.**
Do NOT summarize, condense, or reformat. Paste the entire contents of `User.md`
into the response so the user sees every section:
- Token totals table (Fresh input / Cache creation / Cache read / Output)
- Estimated cost & model mix table
- **Repos worked in table** (with GL Commits, AI Commits, Turns, Est. cost columns)
- Scorecard table
- Per-practice findings with worst offenders
- Agent behavior observations
- Top priority

Omitting any table or section — especially the Repos / AI commits table — is a
bug. The repo table is the primary evidence for the budget case and must always
be shown in full.

Do **not** paste `IT.md` into the chat by default — it is the manager-facing
artifact, delivered as a file. Just point the user to it via the link in 2a and
the send instruction in 2c.

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
  full coaching report?" — you always paste the coaching report (2b) **and**
  always surface this `IT.pdf` instruction. Both happen; it is not a choice.
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

### Step 5 — Route to HelpDesk **only after explicit confirmation**

**This is a hard gate. Never auto-send.** Show the developer the full packet and
ticket, then ask them to confirm before anything leaves.

```bash
# Preview what would be sent (no email dispatched):
python3 scripts/send_report.py --packet budget-request-packet.md \
    --ticket helpdesk-ticket.txt --dev "<name>" --period "<period>"

# Send only after the developer says yes:
python3 scripts/send_report.py --packet budget-request-packet.md \
    --ticket helpdesk-ticket.txt --dev "<name>" --period "<period>" --confirm
```

The script auto-selects the first enabled connector whose credentials are present
(priority: **gmail** → **email**). If neither is ready it exits with instructions.

**Gmail connector setup** (one-time):
1. Go to https://myaccount.google.com/apppasswords and generate a 16-char App Password.
2. Set `enabled: true` under `gmail` in `connectors.json`.
3. Export two env vars (add to `~/.zshrc` / `~/.bashrc` so they persist):
   ```bash
   export GMAIL_FROM="you@gmail.com"
   export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
   ```
4. Run the dry-run above to verify before the first real send.

**No connector** — hand the developer `budget-request-packet.md` and
`helpdesk-ticket.txt` to submit themselves.

The developer must see exactly what will be sent — including the repo audit —
before it goes anywhere.

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

**Not trackable from transcripts:** whether a task was framed well, or whether a
*specific* Opus turn truly needed Opus (model-efficiency is a deliberately
conservative heuristic — present as "consider", not a verdict).

See `references/best-practices.md` for the full catalog, each metric definition,
the thresholds, and the weighting. Read it before customizing thresholds or
explaining the methodology.

## Scoring model

Each scored practice gets 0–100 and a letter (A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60,
F < 60); the overall grade is the weighted average of scored practices only.
Observations never affect the grade. Weights live in `analyze.py:WEIGHTS`,
thresholds in `analyze.py:THRESHOLDS`, prices in `analyze.py:PRICING` — all meant
to be tuned per team. The packet's recommendation is derived from the overall
grade tempered by the size of the requested increase (`build_packet.py:recommend`).

## Governance & privacy

- **Sending to HelpDesk is a permissioned action** — generate, let the developer
  review, confirm, then send. No standing auto-forward.
- **Transparency over monitoring** — the developer sees the full packet,
  including the repo audit, before it's routed. The repo audit carries repo
  names, branches, and counts only — **never code contents**.
- **Estimated ≠ authoritative spend** — the transcript dollar figure is a
  relative efficiency signal; reconcile against billing before a final cap decision.

## Outputs

- `User.md` / `User.pdf` — developer coaching report (always).
- `IT.md` / `IT.pdf` — manager / IT HelpDesk report: spend, repo activity,
  efficiency verdict; no session details, paths, or prompt contents (always).
- `report.json` — machine feed for the budget packet (always).
- `budget-request-packet.md` — one-page IT/HelpDesk packet (budget requests).
- `helpdesk-ticket.txt` — pre-filled ticket body (budget requests).
- `log.json` — append-only audit log of packet generation (and, once a connector
  is wired, submission). Metrics + packet hash only; no code or secrets.

## Deferred (manual fallback in place)

These are intentionally not yet automated; the skill works without them:

- **HelpDesk routing connectors** (YouTrack / email) — until wired, the developer
  attaches `budget-request-packet.md` / pastes `helpdesk-ticket.txt` themselves
  after reviewing. The confirmation gate (never auto-send) still applies.

## Testing

`scripts/make_fixture.py <dir>` writes synthetic two-repo sessions with git
check-ins so you can exercise both the coaching and budget paths without real
transcripts. See `samples/` for example outputs.
