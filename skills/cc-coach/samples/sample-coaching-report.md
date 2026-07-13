# Claude Code Token-Optimization Report

_Generated 2026-06-11 02:35_

**Scope:** 2 session(s) · 2026-06-01 → 2026-06-01, 14 assistant turns, 2 user prompts

## Overall grade: C  (74/100)

### Token totals

| Bucket | Tokens |
|---|--:|
| Fresh input | 4,070 |
| Cache creation | 10,700 |
| Cache read | 311,300 |
| Output | 1,035 |
| **Total** | **327,105** |

### Estimated cost & model mix

Estimated spend: **$0.25** (at current API rates; edit `PRICING` in analyze.py if you're on a plan or different models).

| Model tier | Turns | Est. cost |
|---|--:|--:|
| opus | 10 | $0.22 |
| sonnet | 4 | $0.03 |

### Repos worked in (from Claude Code sessions)

Repos touched in the analyzed sessions, with check-ins made *through* Claude Code and token/cost attributed per repo. (Captures git activity run through Claude Code only; commits made outside it won't appear.)

| Repo | Branch(es) | Commits | Pushes | Turns | Est. cost |
|---|---|--:|--:|--:|--:|
| app | main | 1 | 1 | 10 | $0.22 |
| api | feature/ratelimit | 1 | 0 | 4 | $0.03 |

### Scorecard

These reflect habits you directly control (session hygiene, model choice, how you phrase asks).

| Practice | Grade | Score | Wt | Signal |
|---|:--:|--:|--:|---|
| Cache Efficiency | A | 100 | 25 | 95.5% cache-read share |
| Targeted Reads | F | 50 | 18 | 50% of reads were small/bounded |
| Output Size Discipline | D | 62 | 17 | 7.7% of tool outputs were oversized |
| Context Discipline | B | 80 | 15 | peak session input ~267,010 tok, 1 compaction(s) |
| Model Efficiency | B | 80 | 13 | 2/10 Opus turns looked trivial (~$0.02 saveable) |
| Tool Error Rate | D | 62 | 12 | 7.7% tool-call error rate |

### Findings & recommendations

**Cache Efficiency — A (100/100)**  
cache_read=311,300 creation=10,700 fresh_input=4,070  
→ Looking good — keep it up.

**Targeted Reads — F (50/100)**  
reads=4 bounded(offset/limit)=2 large(>2000tok)=2  
Worst offenders:
  - `/app/auth.py` — ~3,000 tok
  - `/app/auth.py` — ~3,000 tok

→ **Do this:** These whole-file reads cost ~6,000 tokens (and re-cost on every later turn). For each, Grep for the symbol you need, then Read with offset/limit around the hit.

**Output Size Discipline — D (62/100)**  
oversized(>5000tok)=1 of 13 results  
Worst offenders:
  - `cat build.log` — ~10,000 tok

→ **Do this:** These outputs added ~10,000 tokens. Re-run them as `<cmd> | tail -50` or redirect to a file and Read a slice; for tests use `-q`/`--no-header` or filter to failures.

**Context Discipline — B (80/100)**  
max_session_input=267,010 compactions=1  
→ Looking good — keep it up.

**Model Efficiency — B (80/100)**  
est. cost $0.25 · opus:10turns/$0.22, sonnet:4turns/$0.03  
→ Looking good — keep it up.

**Tool Error Rate — D (62/100)**  
errors=1 of 13 results  
Worst offenders:
  - Bash: `pytest`

→ **Do this:** Each failed call burned a round-trip. Confirm the path/command exists before calling; for Edit, copy the exact `old_string` from a fresh Read.

### Agent behavior observations (not scored)

These are Claude's in-the-moment choices, not your habits, so they don't affect your grade. If a pattern is frequent, the fix is a steering rule in CLAUDE.md — suggested lines below.

**Redundant Reads** — 1 redundant re-reads (25% of reads)  
Frequent examples:
  - `/app/auth.py`

→ **Add to CLAUDE.md:** "Do not re-read files already in context unless they have changed on disk."

**Native Search** — 1 Bash search/read cmds (20% of Bash calls)  
Frequent examples:
  - `cat build.log`

→ **Add to CLAUDE.md:** "Prefer the Grep/Glob/Read tools over shell `cat`/`grep`/`find`/`ls` for searching and reading files."

**Parallel Batching** — 18% of tool turns batched 2+ calls  

→ **Add to CLAUDE.md:** "When tool calls are independent, issue them together in a single message."

**Subagent Offloading** — 0 subagent (Task) delegations  

→ **Add to CLAUDE.md:** "For broad codebase exploration or multi-file searches, delegate to a subagent and return only conclusions."

### Top priority

Focus first on **Targeted Reads** (50/100, weight 18).  
These whole-file reads cost ~6,000 tokens (and re-cost on every later turn). For each, Grep for the symbol you need, then Read with offset/limit around the hit.

Start with: /app/auth.py — ~3,000 tok; /app/auth.py — ~3,000 tok

---

<sub>Source files analyzed:</sub>

<sub>- /tmp/ccfix/-Users-me-work/11111111-2222-3333-4444-555555555555.jsonl</sub>
<sub>- /tmp/ccfix/-Users-me-work/99999999-8888-7777-6666-555555555555.jsonl</sub>