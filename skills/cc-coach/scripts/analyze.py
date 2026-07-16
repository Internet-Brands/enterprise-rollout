#!/usr/bin/env python3
"""
Claude Code token-optimization analyzer.

Parses Claude Code session transcripts (JSONL) and scores the developer's
session(s) against a set of trackable token-optimization best practices.

Emits a machine-readable JSON blob plus a human-readable Markdown report.

Data source (confirmed):
  ~/.claude/projects/<encoded-project-path>/<session-id>.jsonl
  - type=="assistant" entries carry message.usage with:
        input_tokens, output_tokens,
        cache_creation_input_tokens, cache_read_input_tokens
  - message.content holds blocks: text | thinking | tool_use | tool_result
  - tool_use:   {id, name, input}
  - tool_result (inside a later type=="user" entry): {tool_use_id, content, is_error}
  - system entries mark compaction boundaries / summaries

Usage:
  python analyze.py                       # auto-discover newest project's sessions
  python analyze.py --project PATH        # a ~/.claude/projects/<dir> folder
  python analyze.py --session FILE.jsonl  # a single transcript
  python analyze.py --days 7              # only sessions active in last N days
  python analyze.py --root ~/.claude/projects
  python analyze.py --json-out report.json --md-out report.md
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

# ----------------------------------------------------------------------------
# Tunable thresholds (single source of truth for the rubric).
# ----------------------------------------------------------------------------
CHARS_PER_TOKEN = 4  # rough estimator for content we must size ourselves

THRESHOLDS = {
    "large_read_tokens": 2000,        # a Read result above this is "large"
    "oversized_output_tokens": 5000,  # a tool_result above this floods context
    "big_session_tokens": 500_000,    # peak SINGLE-TURN context window above this is noteworthy
                                      # (raised from 1M: cache-read dominates input,
                                      # so any real session blows past 1M immediately)
    "compaction_rate_warn": 0.33,     # >1 compaction per 3 sessions = pattern worth noting
    "bash_search_cmds": r"\b(cat|grep|find|ls|head|tail|sed|awk|rg)\b",
    "simple_turn_output_tokens": 400, # an Opus turn below this w/ no tools/thinking
                                      # is "likely could have run on a cheaper model"
}

# Per-million-token prices (USD), by model tier. CHECK/EDIT THESE — they change.
# As of May 2026: Opus 4.7/4.8 = 5/25, Sonnet 4.6 = 3/15, Haiku 4.5 = 1/5,
# Fable 5 = 10/50 (2× Opus). Cache read = 10% of input; cache write = 125% of input.
# NOTE: legacy Opus 4 / 4.1 are 15/75 — bump the opus row if you used those.
PRICING = {
    "fable":  {"in": 10.0, "out": 50.0},
    "opus":   {"in": 5.0,  "out": 25.0},
    "sonnet": {"in": 3.0,  "out": 15.0},
    "haiku":  {"in": 1.0,  "out": 5.0},
    "other":  {"in": 3.0,  "out": 15.0},  # fallback == sonnet
}


def model_tier(model):
    m = (model or "").lower()
    if "fable" in m:
        return "fable"
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "other"


def turn_cost(usage, tier):
    """USD cost of one assistant turn given its model tier."""
    p = PRICING.get(tier, PRICING["other"])
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cc = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    return (inp * p["in"] + cc * p["in"] * 1.25 + cr * p["in"] * 0.10
            + out * p["out"]) / 1_000_000

# Weight of each practice in the overall grade. Must sum to 100.
WEIGHTS = {
    # Scored practices: things the developer directly controls (session habits,
    # slash commands, model choice, how they phrase asks).
    #
    # tool_error_rate was removed from scoring (2026-07): tool calls are issued
    # by Claude, not the developer, so per the skill's own design rule
    # ("scored = developer-controlled") it now renders as an unscored
    # observation. Its 12 points were redistributed below (sum stays 100).
    "cache_efficiency": 28,
    "targeted_reads": 20,
    "output_size_discipline": 19,
    "context_discipline": 17,
    "model_efficiency": 16,
}

# Unscored observations: Claude's in-the-moment behavior. The developer can't
# control these per-call, so they don't affect the grade — but each has one
# real lever: a steering rule in CLAUDE.md. When a pattern is frequent, the
# report suggests the exact line to add.
OBSERVATIONS = {
    "native_search": "Prefer the Grep/Glob/Read tools over shell "
                     "`cat`/`grep`/`find`/`ls` for searching and reading files.",
    "redundant_reads": "Do not re-read files already in context unless they "
                       "have changed on disk.",
    "parallel_batching": "When tool calls are independent, issue them together "
                         "in a single message.",
    "subagent_offloading": "For broad codebase exploration or multi-file "
                           "searches, delegate to an Agent/Task subagent and return only "
                           "conclusions.",
    "tool_error_rate": "Re-read a file before editing it if it may have changed, "
                       "and verify paths with Glob/Grep before acting — each failed "
                       "tool call re-sends context on retry.",
}


# ----------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------
def approx_tokens(text):
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def content_to_text(content):
    """Flatten a tool_result content field (str | list | dict) to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text", "") or json.dumps(b.get("content", "")))
            else:
                parts.append(str(b))
        return "".join(parts)
    if isinstance(content, dict):
        return content.get("text", "") or json.dumps(content)
    return str(content)


def iter_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# Core: walk a list of session files and accumulate raw signals
# ----------------------------------------------------------------------------
class Stats:
    def __init__(self):
        self.sessions = 0
        self.assistant_turns = 0
        self.user_turns = 0           # real user prompts (not tool-result returns)
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation = 0
        self.cache_read = 0
        self.thinking_chars = 0
        self.compaction_events = 0    # auto/unknown compactions (scored)
        self.manual_compactions = 0   # user-invoked /compact (deliberate — NOT scored)
        self.max_session_input = 0    # peak SINGLE-TURN context window across all sessions
        self.sessions_with_compaction = 0  # distinct sessions that hit compaction

        # tool usage
        self.tool_calls = Counter()
        self.tool_use_total = 0
        self.tool_errors = 0           # total is_error=true results
        self.tool_errors_operator = 0  # subset attributable to operator (scored)
        self.tool_results = 0

        # reads
        self.reads = 0
        self.reads_bounded = 0        # used offset/limit
        self.large_reads = 0          # result above large_read_tokens
        self.redundant_reads = 0      # re-read same file w/o intervening edit

        # bash
        self.bash_calls = 0
        self.bash_search_calls = 0    # cat/grep/find/ls/... that duplicate native tools

        # output sizing
        self.oversized_outputs = 0

        # batching: tool_use blocks per assistant message
        self.tool_msgs = 0
        self.batched_tool_msgs = 0    # assistant msgs with >1 tool_use

        # subagents (delegations counted in main thread; spend folded separately)
        self.task_calls = 0
        self.subagent_sessions = 0
        self.subagent_turns = 0
        self.subagent_input_tokens = 0
        self.subagent_output_tokens = 0
        self.subagent_cache_creation = 0
        self.subagent_cache_read = 0
        self.subagent_cost_total = 0.0

        self.models = Counter()
        self.first_ts = None
        self.last_ts = None

        # cost & model efficiency
        self.cost_total = 0.0
        self.cost_by_tier = defaultdict(float)
        self.turns_by_tier = Counter()
        self.opus_turns = 0
        self.opus_simple_turns = 0          # trivial turns that ran on Opus
        self.opus_simple_savings = 0.0      # $ if those had run on Sonnet

        # Concrete offenders so feedback can name names (path/cmd, tokens).
        self.large_read_files = []     # [(path, tokens)]
        self.large_read_tokens_sum = 0
        self.oversized_items = []      # [(tool_name, tokens)]
        self.oversized_tokens_sum = 0
        self.bash_search_cmds = []     # [command, ...]
        self.redundant_files = []      # [path, ...]
        self.error_items = []          # [(tool_name, snippet)]
        self.heaviest_session = None   # (path, tokens)

        # repos worked in (derived from per-entry cwd / gitBranch + git Bash calls)
        self.repos = defaultdict(lambda: {
            "path": "", "branches": set(), "sessions": set(),
            "turns": 0, "commits": 0, "pushes": 0, "remotes": set(),
            "input": 0, "output": 0, "cache_creation": 0,
            "cache_read": 0, "cost": 0.0})


# Patterns that indicate an error is NOT attributable to the developer:
#   - User denied a permission prompt ("user doesn't want to proceed")
#   - Claude tried to edit/write without reading first ("File has not been read yet")
#   - Claude guessed a non-existent path ("File does not exist", "No such file")
#   - Claude referenced an unknown agent type
#   - Bash exit code 1 from tools that legitimately return nonzero (tsc, eslint,
#     git diff, grep with no match, etc.) — distinguished by short output with no
#     stack trace
#   - Browser/playwright trial-and-error (strict mode violations, null DOM reads)
#   - ENVIRONMENTAL failures outside the developer's control: network/DNS/TLS,
#     auth-token expiry, VPN unreachable, cluster/gateway timeouts, 5xx. These are
#     infrastructure, not habit, so they must not count against the grade.
_NOISE_CONTENT_PATTERNS = re.compile(
    r"user doesn.t want to proceed"
    r"|The tool use was rejected"
    r"|File has not been read yet"
    r"|file has not been read"
    r"|File does not exist"
    r"|No such file or directory"
    r"|Agent type .* not found"
    r"|strict mode violation"
    r"|locator\..*resolved to \d+ elements"
    r"|Cannot read propert"     # null DOM reads
    r"|playwright"
    # --- environmental / infrastructure (not developer-preventable) ---
    r"|ETIMEDOUT|ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN|EHOSTUNREACH"
    r"|could not resolve host|name resolution|temporary failure in name resolution"
    r"|network is unreachable|connection (?:refused|reset|timed out)"
    r"|context deadline exceeded|i/o timeout|deadline exceeded"
    r"|TLS handshake|x509|certificate (?:verify|has expired|is not valid)"
    r"|401 Unauthorized|403 Forbidden|token (?:has )?expired|authentication failed"
    r"|500 Internal Server Error|502 Bad Gateway|503 Service Unavailable|504 Gateway Time"
    r"|VPN|proxy",
    re.IGNORECASE,
)
_NOISE_TOOL_NAMES = {"AskUserQuestion", "ExitPlanMode", "mcp__Claude_Preview__preview_click",
                     "mcp__Claude_in_Chrome__"}


_SECRET_PATTERNS = [
    (re.compile(r"(https?://)[^/\s:@]+(?::[^/\s@]+)?@"), r"\1"),          # user:token@host
    (re.compile(r"(?i)(authorization:\s*)(bearer\s+)?\S+"), r"\1\2***"),  # auth headers
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ***"),  # bearer tokens
    (re.compile(r"(?i)\b(token|password|passwd|secret|api[_-]?key|access[_-]?key|"
                r"client[_-]?secret|private[_-]?token)(\s*[=:]\s*)\S+"), r"\1\2***"),
    (re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,})"), "***"),                 # GitHub tokens
    (re.compile(r"(glpat-[A-Za-z0-9_-]{16,})"), "***"),                   # GitLab PATs
]


def _scrub_secrets(text: str) -> str:
    """Redact credentials from a string before it is stored in report.json / examples."""
    if not text:
        return text
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _is_noise_error(content_text: str, tool_name: str) -> bool:
    """Return True if this error should NOT count against the developer's score."""
    if any(tool_name.startswith(prefix) for prefix in _NOISE_TOOL_NAMES):
        return True
    if _NOISE_CONTENT_PATTERNS.search(content_text or ""):
        return True
    return False


def analyze_files(files):
    s = Stats()
    for path in files:
        s.sessions += 1
        session_input = 0
        current_repo = "(unknown)"
        _session_compaction_count = 0
        # track Read paths and edits to detect redundant reads
        read_paths = set()
        toolid_to_meta = {}  # tool_use_id -> {"name":..., "is_read":bool}

        for entry in iter_lines(path):
            etype = entry.get("type")
            ts = parse_ts(entry.get("timestamp"))
            if ts:
                s.first_ts = ts if s.first_ts is None else min(s.first_ts, ts)
                s.last_ts = ts if s.last_ts is None else max(s.last_ts, ts)

            msg = entry.get("message") or {}

            cwd = entry.get("cwd")
            if cwd:
                current_repo = os.path.basename(cwd.rstrip("/")) or cwd
                R = s.repos[current_repo]
                R["path"] = cwd
                gb = entry.get("gitBranch")
                if gb:
                    R["branches"].add(gb)
                R["sessions"].add(os.path.basename(path))

            if etype == "system":
                sub = (entry.get("subtype") or "") + " " + content_to_text(entry.get("content"))
                if "compact" in sub.lower():
                    # Distinguish deliberate `/compact` (good hygiene) from auto-fired
                    # compaction (the lossy kind this metric should discourage).
                    meta_c = entry.get("compactMetadata") or msg.get("compactMetadata") or {}
                    trigger = (meta_c.get("trigger") or "").lower()
                    if trigger == "manual":
                        s.manual_compactions += 1          # not penalised
                    else:
                        s.compaction_events += 1           # auto / unknown -> scored
                        _session_compaction_count += 1
                continue

            if etype == "assistant":
                s.assistant_turns += 1
                usage = msg.get("usage") or {}
                inp = usage.get("input_tokens", 0) or 0
                s.input_tokens += inp
                s.output_tokens += usage.get("output_tokens", 0) or 0
                s.cache_creation += usage.get("cache_creation_input_tokens", 0) or 0
                s.cache_read += usage.get("cache_read_input_tokens", 0) or 0
                # Peak SINGLE-TURN context window (what actually approaches the model
                # limit), NOT a cumulative sum — summing every turn's cache_read grows
                # with session length, not context size, and massively overstates it.
                turn_window = (inp
                               + (usage.get("cache_read_input_tokens", 0) or 0)
                               + (usage.get("cache_creation_input_tokens", 0) or 0))
                if turn_window > session_input:
                    session_input = turn_window
                model = msg.get("model")
                if model:
                    s.models[model] += 1

                content = msg.get("content")
                tool_uses_here = 0
                thinking_here = False
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt == "thinking":
                            thinking_here = True
                            s.thinking_chars += len(b.get("thinking", "") or "")
                        elif bt == "tool_use":
                            name = b.get("name", "")
                            tid = b.get("id")
                            inp_obj = b.get("input") or {}
                            s.tool_calls[name] += 1
                            s.tool_use_total += 1
                            tool_uses_here += 1
                            is_read = (name == "Read")
                            toolid_to_meta[tid] = {
                                "name": name, "is_read": is_read,
                                "path": inp_obj.get("file_path", ""),
                                "cmd": inp_obj.get("command", ""),
                            }

                            if name == "Read":
                                s.reads += 1
                                fp = inp_obj.get("file_path", "")
                                if inp_obj.get("limit") or inp_obj.get("offset"):
                                    s.reads_bounded += 1
                                if fp:
                                    if fp in read_paths:
                                        s.redundant_reads += 1
                                        s.redundant_files.append(fp)
                                    read_paths.add(fp)
                            elif name in ("Edit", "Write", "NotebookEdit"):
                                fp = inp_obj.get("file_path", "")
                                read_paths.discard(fp)  # edited -> a re-read is justified
                            elif name == "Bash":
                                s.bash_calls += 1
                                cmd = inp_obj.get("command", "") or ""
                                if re.search(THRESHOLDS["bash_search_cmds"], cmd):
                                    s.bash_search_calls += 1
                                    s.bash_search_cmds.append(_scrub_secrets(cmd.strip())[:120])
                                if re.search(r"\bgit\s+commit\b", cmd):
                                    s.repos[current_repo]["commits"] += 1
                                if re.search(r"\bgit\s+push\b", cmd):
                                    s.repos[current_repo]["pushes"] += 1
                                rm = re.search(r"git\s+remote(?:\s+add\s+\S+)?\s+(https?://\S+|git@\S+)", cmd)
                                if rm:
                                    s.repos[current_repo]["remotes"].add(_scrub_secrets(rm.group(1)))
                            elif name in ("Task", "Agent"):
                                s.task_calls += 1

                if tool_uses_here:
                    s.tool_msgs += 1
                    if tool_uses_here > 1:
                        s.batched_tool_msgs += 1

                # cost + model efficiency
                tier = model_tier(model)
                cost = turn_cost(usage, tier)
                s.cost_total += cost
                s.cost_by_tier[tier] += cost
                R = s.repos[current_repo]
                R["turns"] += 1
                R["input"] += inp
                R["output"] += usage.get("output_tokens", 0) or 0
                R["cache_creation"] += usage.get("cache_creation_input_tokens", 0) or 0
                R["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
                R["cost"] += cost
                if model:
                    s.turns_by_tier[tier] += 1
                if tier == "opus":
                    s.opus_turns += 1
                    out_tok = usage.get("output_tokens", 0) or 0
                    simple = (tool_uses_here == 0 and not thinking_here
                              and out_tok < THRESHOLDS["simple_turn_output_tokens"])
                    if simple:
                        s.opus_simple_turns += 1
                        s.opus_simple_savings += cost - turn_cost(usage, "sonnet")
                continue

            if etype == "user":
                content = msg.get("content")
                # Distinguish a real prompt from a tool_result return
                is_tool_return = False
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            is_tool_return = True
                            s.tool_results += 1
                            meta = toolid_to_meta.get(b.get("tool_use_id"), {})
                            txt = content_to_text(b.get("content"))
                            size = approx_tokens(txt)
                            if b.get("is_error"):
                                s.tool_errors += 1
                                label = meta.get("cmd") or meta.get("path") or meta.get("name", "?")
                                # Classify: noise vs. operator-attributable errors.
                                # Noise = user permission denials, Claude wrong-path/unread
                                # guesses, Bash nonzero that is expected (typecheck, diff),
                                # and browser trial-and-error. These are excluded from the
                                # scored rate so the developer isn't penalised for Claude's
                                # own mistakes or their own permission choices.
                                noise = _is_noise_error(txt, meta.get("name", ""))
                                if not noise:
                                    s.tool_errors_operator += 1
                                    s.error_items.append((meta.get("name", "?"),
                                                          _scrub_secrets(str(label).strip())[:100]))
                            if size > THRESHOLDS["oversized_output_tokens"]:
                                s.oversized_outputs += 1
                                s.oversized_tokens_sum += size
                                label = meta.get("cmd") or meta.get("path") or meta.get("name", "?")
                                s.oversized_items.append((str(label).strip()[:80], size))
                            if meta.get("is_read") and size > THRESHOLDS["large_read_tokens"]:
                                s.large_reads += 1
                                s.large_read_tokens_sum += size
                                s.large_read_files.append((meta.get("path", "?"), size))
                if not is_tool_return:
                    s.user_turns += 1
                continue

        if session_input > s.max_session_input:
            s.max_session_input = session_input
            s.heaviest_session = (os.path.basename(path), session_input)
        if _session_compaction_count > 0:
            s.sessions_with_compaction += 1
    return s


def fold_subagent_tokens(subagent_files, s):
    """
    Fold subagent token usage and cost into s's totals and per-repo attribution.

    Subagent internals reflect Claude's own behavior, not the developer's habits,
    so we never update habit metrics (redundant reads, oversized outputs, error
    rate, batching, compaction, etc.) — only the billing / model-mix numbers.
    """
    for path in subagent_files:
        s.subagent_sessions += 1
        current_repo = "(unknown)"

        for entry in iter_lines(path):
            etype = entry.get("type")
            ts = parse_ts(entry.get("timestamp"))
            if ts:
                s.first_ts = ts if s.first_ts is None else min(s.first_ts, ts)
                s.last_ts = ts if s.last_ts is None else max(s.last_ts, ts)

            cwd = entry.get("cwd")
            if cwd:
                current_repo = os.path.basename(cwd.rstrip("/")) or cwd
                R = s.repos[current_repo]
                R["path"] = cwd
                gb = entry.get("gitBranch")
                if gb:
                    R["branches"].add(gb)
                R["sessions"].add(os.path.basename(path))

            if etype != "assistant":
                continue

            msg = entry.get("message") or {}
            usage = msg.get("usage") or {}
            model = msg.get("model")

            inp = usage.get("input_tokens", 0) or 0
            out = usage.get("output_tokens", 0) or 0
            cc = usage.get("cache_creation_input_tokens", 0) or 0
            cr = usage.get("cache_read_input_tokens", 0) or 0

            # Fold into global totals (so spend / model-mix tables are complete)
            s.input_tokens += inp
            s.output_tokens += out
            s.cache_creation += cc
            s.cache_read += cr
            s.subagent_turns += 1
            s.subagent_input_tokens += inp
            s.subagent_output_tokens += out
            s.subagent_cache_creation += cc
            s.subagent_cache_read += cr

            tier = model_tier(model)
            cost = turn_cost(usage, tier)
            s.cost_total += cost
            s.subagent_cost_total += cost
            s.cost_by_tier[tier] += cost
            s.turns_by_tier[tier] += 1
            if model:
                s.models[model] += 1

            R = s.repos[current_repo]
            R["turns"] += 1
            R["input"] += inp
            R["output"] += out
            R["cache_creation"] += cc
            R["cache_read"] += cr
            R["cost"] += cost


# ----------------------------------------------------------------------------
# Scoring: each practice -> 0..100 plus letter, then weighted overall
# ----------------------------------------------------------------------------
def pct(n, d):
    return (n / d) if d else 0.0


def top_counts(items, n=5):
    """Most frequent string items as 'value (xN)' lines."""
    c = Counter(items)
    return [f"`{v}`" + (f" ×{cnt}" if cnt > 1 else "") for v, cnt in c.most_common(n)]


def top_sized(pairs, n=5):
    """[(label, tokens)] -> 'label — ~Ntok', largest first."""
    out = []
    for label, tok in sorted(pairs, key=lambda x: -x[1])[:n]:
        out.append(f"`{label}` — ~{tok:,} tok")
    return out


def letter(score):
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def score_practices(s):
    P = {}

    # 1. Cache efficiency: cache_read share of all input-side tokens.
    cacheable = s.cache_read + s.cache_creation + s.input_tokens
    hit = pct(s.cache_read, cacheable)
    P["cache_efficiency"] = {
        "metric": f"{hit*100:.1f}% cache-read share",
        "value": hit,
        "score": min(100, hit / 0.90 * 100),  # 90%+ read share == full marks
        "detail": f"cache_read={s.cache_read:,} creation={s.cache_creation:,} "
                  f"fresh_input={s.input_tokens:,}",
        "advice": "Avoid edits/instructions that invalidate the cached prefix; keep "
                  "CLAUDE.md and tool set stable within a session.",
    }

    # 2. Targeted reads: share of Reads that used offset/limit OR were small.
    safe_reads = s.reads - s.large_reads  # small reads are fine even if unbounded
    good = safe_reads + 0  # bounded reads already counted within safe set
    targeted = pct(s.reads_bounded + max(0, safe_reads - s.reads_bounded), s.reads) if s.reads else 1.0
    P["targeted_reads"] = {
        "metric": f"{(1-pct(s.large_reads, s.reads))*100:.0f}% of reads were small/bounded"
                  if s.reads else "no reads",
        "value": 1 - pct(s.large_reads, s.reads),
        "score": (1 - pct(s.large_reads, s.reads)) * 100 if s.reads else 100,
        "detail": f"reads={s.reads} bounded(offset/limit)={s.reads_bounded} "
                  f"large(>{THRESHOLDS['large_read_tokens']}tok)={s.large_reads}",
        "advice": "Use Grep/Glob to locate, then Read with offset/limit instead of "
                  "pulling whole large files into context.",
    }

    # 3. Output size discipline: oversized tool_results as share of all results.
    over = pct(s.oversized_outputs, s.tool_results)
    P["output_size_discipline"] = {
        "metric": f"{over*100:.1f}% of tool outputs were oversized",
        "value": over,
        "score": max(0, 100 - over * 100 * 5),  # 20% oversized -> 0
        "detail": f"oversized(>{THRESHOLDS['oversized_output_tokens']}tok)="
                  f"{s.oversized_outputs} of {s.tool_results} results",
        "advice": "Pipe long command output through head/tail/wc or write to a file; "
                  "don't dump full logs/builds into the conversation.",
    }

    # 4. Redundant reads: re-reading the same file without an intervening edit.
    rr = pct(s.redundant_reads, s.reads) if s.reads else 0.0
    P["redundant_reads"] = {
        "metric": f"{s.redundant_reads} redundant re-reads ({rr*100:.0f}% of reads)",
        "value": rr,
        "score": max(0, 100 - rr * 100 * 4),  # 25% redundant -> 0
        "detail": f"redundant_reads={s.redundant_reads} reads={s.reads}",
        "advice": "Trust content already in context; only re-read a file after it "
                  "changed on disk.",
    }

    # 5. Native search over Bash: penalize cat/grep/find/ls done through Bash.
    bs = pct(s.bash_search_calls, s.bash_calls) if s.bash_calls else 0.0
    P["native_search"] = {
        "metric": f"{s.bash_search_calls} Bash search/read cmds "
                  f"({bs*100:.0f}% of Bash calls)",
        "value": bs,
        "score": max(0, 100 - bs * 100 * 1.5),
        "detail": f"bash_search={s.bash_search_calls} bash_total={s.bash_calls}",
        "advice": "Prefer Grep/Glob/Read tools over `cat`/`grep`/`find` in Bash — "
                  "they return tighter, more cache-friendly output.",
    }

    # 6. Tool error rate: operator-attributable errors waste a full round-trip.
    # Tool error rate — OBSERVED, NOT SCORED. Tool calls are issued by Claude,
    # not the developer, so failures here are Claude's in-the-moment behavior
    # (the skill's design rule: scored = developer-controlled only). Environmental
    # failures (network/auth/VPN), user permission denials, Claude's own
    # wrong-path/unread-file mistakes, expected-nonzero Bash, and browser
    # trial-and-error are additionally excluded from the reported figure.
    er = pct(s.tool_errors_operator, s.tool_results) if s.tool_results else 0.0
    noise_excluded = s.tool_errors - s.tool_errors_operator
    P["tool_error_rate"] = {
        "metric": f"{er*100:.1f}% tool-call error rate (not scored)",
        "value": er,
        "score": max(0, 100 - er * 100 * 5),  # informational only — weight is 0
        "detail": (f"errors={s.tool_errors_operator} of {s.tool_results} results"
                   + (f" ({noise_excluded} excluded: permission denials, environmental "
                      f"failures, Claude path-guesses, expected-nonzero Bash)"
                      if noise_excluded else "")),
        "advice": "These are Claude's failed calls, not yours — they never affect "
                  "your grade. If frequent, add the suggested CLAUDE.md rule; each "
                  "retry re-sends context.",
    }

    # 7. Context discipline: per-session compaction rate + peak session size.
    # Design goals (from reviewer feedback):
    #  - Penalise the *rate* of compactions per session, not the raw count over
    #    the whole window (an active developer over 30 days will always accrue 2+).
    #  - Only AUTO compactions count. A user-invoked `/compact` is deliberate hygiene
    #    and must never lower the score (tracked as manual_compactions, shown only).
    #  - The threshold is a real single-turn context window (peak input+cache), not a
    #    cumulative sum, so it reflects how BIG a session got, not how LONG it ran.
    #  - Leave room for justified heavy sessions (major refactors, new-app scaffolding).
    comp_rate = pct(s.sessions_with_compaction, s.sessions) if s.sessions else 0.0
    # Penalty: 0 at 0%, -30 at 100% of sessions hitting AUTO compaction (linear, capped 30)
    comp_pen = min(30, comp_rate * 30)
    # Size penalty: only if the peak single-turn window is very large.
    big = s.max_session_input > THRESHOLDS["big_session_tokens"]
    size_pen = 20 if big else 0
    _manual_note = (f", {s.manual_compactions} manual /compact (not scored)"
                    if s.manual_compactions else "")
    P["context_discipline"] = {
        "metric": (f"{s.sessions_with_compaction}/{s.sessions} sessions hit auto-compaction "
                   f"({comp_rate*100:.0f}%), peak window ~{s.max_session_input:,} tok{_manual_note}"),
        "value": s.max_session_input,
        "score": max(0, 100 - comp_pen - size_pen),
        "detail": (f"sessions_with_compaction={s.sessions_with_compaction}/{s.sessions} "
                   f"auto_compactions={s.compaction_events} manual_compactions={s.manual_compactions} "
                   f"peak_turn_window={s.max_session_input:,}"),
        "advice": ("Run /clear between unrelated tasks so sessions don't grow into "
                   "forced compaction. For large intentional sessions (major refactor, "
                   "new app), /compact with a focus note preserves key context."),
    }

    # 8. Parallel batching: independent tool calls sent together.
    batch = pct(s.batched_tool_msgs, s.tool_msgs) if s.tool_msgs else 0.0
    P["parallel_batching"] = {
        "metric": f"{batch*100:.0f}% of tool turns batched 2+ calls",
        "value": batch,
        "score": min(100, batch / 0.40 * 100),  # 40%+ batched == full marks
        "detail": f"batched_tool_msgs={s.batched_tool_msgs} tool_msgs={s.tool_msgs}",
        "advice": "Issue independent tool calls in a single turn to cut round-trips "
                  "(each round-trip re-bills the context).",
    }

    # 9. Subagent offloading: presence of Agent/Task delegation (informational/light).
    P["subagent_offloading"] = {
        "metric": f"{s.task_calls} subagent (Agent/Task) delegation(s)",
        "value": s.task_calls,
        "score": 100 if s.task_calls > 0 else 60,
        "detail": f"agent_or_task_calls={s.task_calls}",
        "advice": "Delegate broad searches/exploration to subagents so their large "
                  "intermediate output never enters your main context.",
    }

    # 10. Model efficiency: expensive-model turns that look trivial.
    # Heuristic (not ground truth): an Opus turn with no tool calls, no extended
    # thinking, and a short answer probably didn't need Opus.
    simple_ratio = pct(s.opus_simple_turns, s.opus_turns) if s.opus_turns else 0.0
    if s.opus_turns == 0:
        me_score = 100  # no premium-model spend to optimize
        me_metric = "no Opus turns — already economical"
    else:
        # Penalty: each 1% trivial-Opus share costs 1 point (100 trivial = 0).
        # Old formula used ×1000 which zeroed the score at 0.1% trivial — far too harsh.
        me_score = max(0, 100 - simple_ratio * 100)
        me_metric = (f"{s.opus_simple_turns}/{s.opus_turns} Opus turns looked trivial "
                     f"(~${s.opus_simple_savings:.2f} saveable)")
    P["model_efficiency"] = {
        "metric": me_metric,
        "value": simple_ratio,
        "score": me_score,
        "detail": f"est. cost ${s.cost_total:.2f} · "
                  + ", ".join(f"{t}:{n}turns/${s.cost_by_tier[t]:.2f}"
                              for t, n in s.turns_by_tier.most_common())
                  if s.turns_by_tier else f"est. cost ${s.cost_total:.2f}",
        "advice": "Start tasks in Sonnet and escalate to Opus only for genuinely "
                  "hard reasoning/refactoring; use Haiku for trivial edits.",
    }

    # Attach concrete offenders + a quantified, do-this-next action per practice.
    for k in P:
        P[k]["examples"] = []
        P[k]["action"] = ""

    if s.large_read_files:
        P["targeted_reads"]["examples"] = top_sized(s.large_read_files)
        P["targeted_reads"]["action"] = (
            f"These whole-file reads cost ~{s.large_read_tokens_sum:,} tokens "
            f"(and re-cost on every later turn). For each, Grep for the symbol you "
            f"need, then Read with offset/limit around the hit.")

    if s.oversized_items:
        P["output_size_discipline"]["examples"] = top_sized(s.oversized_items)
        P["output_size_discipline"]["action"] = (
            f"These outputs added ~{s.oversized_tokens_sum:,} tokens. Re-run them as "
            f"`<cmd> | tail -50` or redirect to a file and Read a slice; for tests use "
            f"`-q`/`--no-header` or filter to failures.")

    if s.redundant_files:
        P["redundant_reads"]["examples"] = top_counts(s.redundant_files)
        P["redundant_reads"]["action"] = (
            "You already had these files in context. Scroll up instead of re-reading; "
            "only Read again after an Edit/Write changed the file on disk.")

    if s.bash_search_cmds:
        P["native_search"]["examples"] = top_counts(s.bash_search_cmds)
        P["native_search"]["action"] = (
            "Replace these shell commands with native tools: `grep` → Grep, "
            "`find`/`ls` → Glob, `cat`/`head`/`tail file` → Read. They return scoped, "
            "cache-stable output instead of raw dumps.")

    if s.error_items:
        P["tool_error_rate"]["examples"] = [f"{n}: `{lbl}`" for n, lbl in s.error_items[:5]]
        P["tool_error_rate"]["action"] = (
            "Each failed call burned a round-trip. Confirm the path/command exists "
            "before calling; for Edit, copy the exact `old_string` from a fresh Read.")

    if s.opus_turns and s.opus_simple_turns:
        P["model_efficiency"]["action"] = (
            f"{s.opus_simple_turns} of your {s.opus_turns} Opus turns were trivial "
            f"(no tools, no thinking, short answer) — ~${s.opus_simple_savings:.2f} "
            f"of the ${s.cost_by_tier.get('opus', 0):.2f} Opus spend. Use `/model "
            f"sonnet` for routine work and switch to Opus only when you hit genuinely "
            f"hard reasoning; Haiku for trivial edits.")

    if s.heaviest_session and s.max_session_input > THRESHOLDS["big_session_tokens"]:
        sid, tok = s.heaviest_session
        P["context_discipline"]["examples"] = [f"`{sid}` peaked at ~{tok:,} input tok"]
        P["context_discipline"]["action"] = (
            "Run /clear when you switch to unrelated work so the next task starts near "
            "zero, and /compact (with a focus note) before you're forced into it.")
    elif s.compaction_events:
        P["context_discipline"]["action"] = (
            f"{s.compaction_events} auto-compaction(s) fired — that's lossy and "
            f"token-heavy. Pre-empt it with /clear between tasks.")

    for k in P:
        if k in WEIGHTS:
            P[k]["weight"] = WEIGHTS[k]
            P[k]["grade"] = letter(P[k]["score"])
            P[k]["observation"] = False
        else:
            P[k]["weight"] = 0
            P[k]["grade"] = "-"  # observations are not graded
            P[k]["observation"] = True
            P[k]["claude_md"] = OBSERVATIONS.get(k, "")
    return P


def overall(P):
    total_w = sum(WEIGHTS.values())
    weighted = sum(P[k]["score"] * P[k]["weight"] for k in WEIGHTS) / total_w
    return weighted, letter(weighted)


# ----------------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------------
def _load_helpdesk_email():
    """Read the helpdesk 'to' address from connectors.json, fallback to empty string."""
    try:
        cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "connectors.json")
        with open(cfg) as f:
            c = json.load(f)
        for key in ("email", "gmail"):
            addr = (c.get(key) or {}).get("to", "")
            if addr:
                return addr
    except Exception:
        pass
    return "helpdesk2@internetbrands.com"


def render_user_md(s, P, ov_score, ov_letter, files, ai_commits_data=None,
                   spend_data=None):
    L = []
    L.append("# Claude Code Token-Optimization Report\n")
    L.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")
    span = ""
    if s.first_ts and s.last_ts:
        span = f" · {s.first_ts.date()} → {s.last_ts.date()}"
    subagent_note = ""
    if s.subagent_sessions:
        subagent_note = (f", +{s.subagent_sessions} subagent session(s) "
                         f"({s.subagent_turns} turns, ~${s.subagent_cost_total:.2f})")
    L.append(f"**Scope:** {s.sessions} main session(s){span}, "
             f"{s.assistant_turns} main-thread turns, {s.user_turns} user prompts"
             f"{subagent_note}\n")
    L.append(f"## Overall grade: {ov_letter}  ({ov_score:.0f}/100)\n")

    total = s.input_tokens + s.output_tokens + s.cache_creation + s.cache_read
    main_in = s.input_tokens - s.subagent_input_tokens
    main_out = s.output_tokens - s.subagent_output_tokens
    main_cc = s.cache_creation - s.subagent_cache_creation
    main_cr = s.cache_read - s.subagent_cache_read
    L.append("### Token totals\n")
    L.append(f"| Bucket | Main thread | Subagents | Total |\n|---|--:|--:|--:|")
    L.append(f"| Fresh input | {main_in:,} | {s.subagent_input_tokens:,} | {s.input_tokens:,} |")
    L.append(f"| Cache creation | {main_cc:,} | {s.subagent_cache_creation:,} | {s.cache_creation:,} |")
    L.append(f"| Cache read | {main_cr:,} | {s.subagent_cache_read:,} | {s.cache_read:,} |")
    L.append(f"| Output | {main_out:,} | {s.subagent_output_tokens:,} | {s.output_tokens:,} |")
    main_total = main_in + main_cc + main_cr + main_out
    sub_total  = (s.subagent_input_tokens + s.subagent_cache_creation
                  + s.subagent_cache_read + s.subagent_output_tokens)
    L.append(f"| **Total** | **{main_total:,}** | **{sub_total:,}** | **{total:,}** |\n")

    L.append("### Cost & model mix\n")
    if spend_data:
        _p = spend_data.get("period") or {}
        L.append(f"Authoritative spend (billing): **${float(spend_data['spend_usd']):.2f}** "
                 f"for {_p.get('month', '?')}/{_p.get('year', '?')} "
                 f"(source: Anthropic cost report via Athena API"
                 + (f", refreshed {spend_data['data_refreshed_at']}"
                    if spend_data.get("data_refreshed_at") else "") + ").  ")
        if spend_data.get("cap_warning") and spend_data.get("user_message"):
            L.append(f"\n> ⚠️ {spend_data['user_message']}\n")
        L.append(f"Transcript estimate (this analysis window): **${s.cost_total:.2f}** "
                 f"— a relative efficiency signal at API list rates, not a bill.\n")
    else:
        L.append(f"Estimated spend: **${s.cost_total:.2f}** "
                 f"(transcript estimate at current API rates — authoritative billing "
                 f"was unavailable for this run; edit `PRICING` in analyze.py if "
                 f"you're on a plan or different models).\n")
    if s.turns_by_tier:
        L.append("| Model tier | Turns | Est. cost |\n|---|--:|--:|")
        for t, n in s.turns_by_tier.most_common():
            L.append(f"| {t} | {n} | ${s.cost_by_tier[t]:.2f} |")
        L.append("")

    if s.repos:
        L.append("### Repos worked in (from Claude Code sessions)\n")
        L.append("Repos touched in the analyzed sessions, with authoritative GitLab "
                 "commit data where available. AI Commits reflects actual commits "
                 "flagged by GitLab across all instances.\n")

        # Build a lookup from repo name → commit row from the API
        commit_by_repo: dict = {}
        if ai_commits_data and ai_commits_data.get("by_project"):
            for row in ai_commits_data["by_project"]:
                commit_by_repo[row.get("repo", "")] = row

        L.append("| Repo | Branch(es) | GL Commits | AI Commits | Turns | Est. cost | Notes |\n"
                 "|---|---|--:|--:|--:|--:|---|")
        for name, r in sorted(s.repos.items(), key=lambda kv: -kv[1]["cost"]):
            br = ", ".join(sorted(r["branches"])) or "—"
            commit_row = commit_by_repo.get(name)
            if commit_row:
                gl_commits = str(commit_row.get("total_commits", "—"))
                ai_commits = str(commit_row.get("ai_commits", "—"))
                notes = ""
            else:
                gl_commits = "—"
                ai_commits = "—"
                notes = "⚠ no commit data found"

            # Check if any remote is outside org domains
            remotes = r.get("remotes", set())
            if remotes and not any(_is_org_remote(u) for u in remotes):
                notes = ("⚠ not an org project" if not notes
                         else notes + "; ⚠ not an org project")

            L.append(f"| {name} | {br} | {gl_commits} | {ai_commits} | "
                     f"{r['turns']} | ${r['cost']:.2f} | {notes} |")
        L.append("")

    scored = sorted((k for k in P if not P[k]["observation"]),
                    key=lambda k: -P[k]["weight"])
    observed = [k for k in P if P[k]["observation"]]

    # ── DEVELOPER VIEW ────────────────────────────────────────────────────────
    # One card per scored practice: grade, signal, plain-English definition,
    # and the specific action — all in one place so the reader never has to
    # jump between sections.

    L.append("---\n")
    L.append("## Developer view — your habits & next actions\n")
    L.append(
        "Grades reflect habits **you directly control**. "
        "A ≥90 · B ≥80 · C ≥70 · D ≥60 · F <60. "
        "Overall = weighted average of all practices below.\n"
    )

    # Highest-leverage practice (biggest drag on the grade): the one with the most
    # recoverable weighted points = headroom (100-score) × weight. Subtracting weight
    # from a 0-100 score is dimensionally meaningless and lets a low-weight metric
    # outrank a high-weight one.
    weakest = max(scored, key=lambda k: (100 - P[k]["score"]) * P[k]["weight"])
    wp = P[weakest]
    L.append(f"> **Start here → {weakest.replace('_',' ').title()} "
             f"({wp['score']:.0f}/100, weight {wp['weight']}):** "
             f"{wp.get('action') or wp['advice']}\n")

    # Consolidated practice cards
    DEFINITIONS = {
        "cache_efficiency": (
            "How much of your input-token spend is served from Claude's prompt "
            "cache rather than re-billed as fresh input.",
            f"cache_read ÷ (cache_read + cache_creation + fresh_input). "
            f"Full marks at ≥90% hit rate."
        ),
        "targeted_reads": (
            "Whether file reads are scoped with offset/limit or stay small, "
            "rather than loading entire large files into context.",
            f"(reads − large_unbounded) ÷ reads. "
            f"'Large' = result >{THRESHOLDS['large_read_tokens']:,} tokens."
        ),
        "output_size_discipline": (
            "Whether tool results (Bash output, search results, file reads) are "
            "kept to a usable size rather than flooding the context.",
            f"Share of tool results exceeding {THRESHOLDS['oversized_output_tokens']:,} "
            f"tokens. Score = 100 − (oversized_share × 500)."
        ),
        "context_discipline": (
            "How often sessions grow large enough to trigger auto-compaction "
            "(which is lossy — Claude discards earlier context). "
            "Heavy sessions for big refactors are normal; the score reacts only "
            "when compaction is a recurring pattern.",
            f"Rate: sessions_with_compaction ÷ total_sessions (−30 max). "
            f"Extra −20 if the peak single-turn context window exceeds "
            f"{THRESHOLDS['big_session_tokens']:,} tokens. "
            f"Manual /compact is shown but never scored."
        ),
        "model_efficiency": (
            "Whether expensive Opus turns were justified by task complexity, or "
            "whether simpler turns could have run on Sonnet/Haiku. "
            "This is a conservative heuristic — flagged turns are candidates "
            "to review, not a verdict.",
            f"Opus turns with no tool use, no thinking, and <"
            f"{THRESHOLDS['simple_turn_output_tokens']} output tokens flagged. "
            f"Score = 100 − (trivial_ratio × 100)."
        ),
    }

    for k in scored:
        p = P[k]
        name = k.replace("_", " ").title()
        grade_icon = {"A": "[A]", "B": "[B]", "C": "[C]", "D": "[D]", "F": "[F]"}.get(p["grade"], "")
        defn, calc = DEFINITIONS.get(k, ("", ""))
        L.append(f"### {grade_icon} {name} — {p['grade']} ({p['score']:.0f}/100, "
                 f"weight {p['weight']})\n")
        L.append(f"**Your result:** {p['metric']}  ")
        L.append(f"**What this measures:** {defn}  ")
        L.append(f"**How it's scored:** {calc}\n")
        if p["score"] < 80:
            if p.get("examples"):
                L.append("**Worst offenders:**")
                for ex in p["examples"]:
                    L.append(f"  - {ex}")
            action = p.get("action") or p["advice"]
            L.append(f"\n**→ Action:** {action}\n")
        else:
            L.append("**→ On track** — keep it up.\n")

    # Agent behaviour observations (Claude's choices, not scored)
    if observed:
        L.append("### Claude behaviour observations _(not scored — these are Claude's choices, not yours)_\n")
        L.append(
            "These patterns don't affect your grade, but a CLAUDE.md steering rule "
            "reduces them. Add the suggested lines to your project's CLAUDE.md.\n"
        )
        for k in observed:
            p = P[k]
            name = k.replace("_", " ").title()
            L.append(f"**{name}** — {p['metric']}  ")
            if p["score"] < 80:
                if p.get("examples"):
                    L.append("Frequent examples:")
                    for ex in p["examples"][:3]:
                        L.append(f"  - {ex}")
                if p.get("claude_md"):
                    L.append(f"\n→ **Add to CLAUDE.md:** \"{p['claude_md']}\"\n")
            else:
                L.append("→ No action needed.\n")

    L.append("---\n")
    L.append(f"> The IT report (`IT.pdf`) for this period has been prepared separately. "
             f"To request a budget increase, open a ticket with the IT HelpDesk and "
             f"attach `IT.pdf`.\n")

    L.append("---\n")
    L.append("<sub>Source files analyzed:</sub>\n")
    for f in files[:20]:
        L.append(f"<sub>- {f}</sub>")
    return "\n".join(L)


def render_it_md(s, P, ov_score, ov_letter, files, ai_commits_data=None,
                 spend_data=None):
    """IT/Manager-facing report: spend, repo audit, efficiency verdict. No session details."""
    L = []
    helpdesk = _load_helpdesk_email()

    scored = sorted((k for k in P if not P[k]["observation"]),
                    key=lambda k: -P[k]["weight"])

    L.append("# Claude Code Coach — IT Report\n")
    L.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}_  ")
    L.append(f"_To: {helpdesk}_\n")
    L.append(
        "_This report is intended for managers and IT reviewing a budget request. "
        "It contains spend, repo activity, and the efficiency verdict. "
        "It does not contain session details, file paths, or prompt contents._\n"
    )
    L.append("---\n")

    period_start = s.first_ts.strftime("%Y-%m-%d") if s.first_ts else "—"
    period_end   = s.last_ts.strftime("%Y-%m-%d")  if s.last_ts  else "—"
    L.append(f"**Period:** {period_start} → {period_end}  ")
    L.append(f"**Sessions:** {s.sessions} main + {s.subagent_sessions} subagent  ")
    if spend_data:
        _p = spend_data.get("period") or {}
        L.append(f"**Authoritative spend (billing, {_p.get('month','?')}/{_p.get('year','?')}):** "
                 f"${float(spend_data['spend_usd']):.2f}"
                 + (f" _(refreshed {spend_data['data_refreshed_at']})_"
                    if spend_data.get("data_refreshed_at") else "") + "  ")
        L.append(f"**Transcript estimate (analysis window):** ${s.cost_total:.2f}  ")
    else:
        L.append(f"**Estimated spend (transcript-based — authoritative billing "
                 f"unavailable for this run):** ${s.cost_total:.2f}  ")
    L.append(f"**Overall efficiency grade:** {ov_letter} ({ov_score:.0f}/100)\n")

    L.append("## Scorecard\n")
    L.append("| Practice | Grade | Score | Weight |\n|---|:--:|--:|--:|")
    for k in scored:
        p = P[k]
        L.append(f"| {k.replace('_',' ').title()} | {p['grade']} | "
                 f"{p['score']:.0f} | {p['weight']} |")
    L.append("")

    L.append("## Model mix & cost\n")
    L.append("| Model tier | Turns | Est. cost |\n|---|--:|--:|")
    for t, n in s.turns_by_tier.most_common():
        L.append(f"| {t} | {n} | ${s.cost_by_tier[t]:.2f} |")
    L.append("")

    if s.repos:
        L.append("## Repos worked in\n")
        L.append("Repo names, branches, and token cost only — no code or prompt content.\n")
        # Reuse the same commit lookup logic
        commit_by_repo = {}
        if ai_commits_data and ai_commits_data.get("by_project"):
            for row in ai_commits_data["by_project"]:
                commit_by_repo[row.get("repo", "")] = row
        L.append("| Repo | Branch(es) | GL Commits | AI Commits | Turns | Est. cost |\n"
                 "|---|---|--:|--:|--:|--:|")
        for name, r in sorted(s.repos.items(), key=lambda kv: -kv[1]["cost"]):
            br = ", ".join(sorted(r["branches"])) or "—"
            commit_row = commit_by_repo.get(name)
            gl = str(commit_row.get("total_commits", "—")) if commit_row else "—"
            ai = str(commit_row.get("ai_commits", "—"))    if commit_row else "—"
            L.append(f"| {name} | {br} | {gl} | {ai} | {r['turns']} | ${r['cost']:.2f} |")
        L.append("")

    L.append("## Efficiency verdict\n")
    if ov_score >= 90:
        verdict = "**Approve** — strong habits across all practices."
    elif ov_score >= 70:
        verdict = ("**Approve with conditions** — acceptable efficiency; "
                   "developer should address the lowest-scoring practices.")
    else:
        verdict = ("**Coach first** — efficiency gaps significant enough to address "
                   "before increasing the cap.")
    L.append(f"{verdict}\n")

    L.append(
        "> **Manipulation risk (acknowledged):** This report is generated locally "
        "from session transcripts on the developer's machine and is not "
        "server-validated in the initial rollout phase. The SHA-256 packet hash in "
        "`log.json` records what was generated but does not prove the input was "
        "unmodified. Reconcile against authoritative Claude Code Analytics spend "
        "figures before any cap decision.\n"
    )
    return "\n".join(L)


# ----------------------------------------------------------------------------
# AI commits fetch
# ----------------------------------------------------------------------------
ORG_GITLAB_DOMAINS = {"gitlab.webmd.com", "git.internetbrands.com", "gitlab.mercuryhealthcare.com"}


# Authoritative spend API endpoint.
SPEND_API_BASE = "https://athena.webmdhelios.com/api/claude-code/coach/spend"


def fetch_authoritative_spend(email: str, month: int, year: int) -> dict:
    """Fetch the developer's authoritative month-to-date spend from the Athena
    cc-coach API. Returns {} on any failure — the reports fall back to the
    transcript estimate, clearly labelled."""
    if not SPEND_API_BASE or not email:
        return {}
    try:
        from urllib.request import urlopen, Request
        url = f"{SPEND_API_BASE}?email={email}&month={month}&year={year}"
        # The API gateway rejects Python's default User-Agent with 403;
        # send a browser UA (same workaround as fetch_ai_commits).
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"),
        })
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # sanity: must carry a numeric spend_usd to be usable
        float(data["spend_usd"])
        return data
    except Exception:
        return {}


def fetch_ai_commits(base_url: str, email: str, month: int, year: int) -> dict:
    """Fetch AI commit summary from helios-metrics API. Returns {} on any failure."""
    if not base_url or not email:
        return {}
    try:
        from urllib.request import urlopen, Request
        url = (f"{base_url.rstrip('/')}/asterix-page/ai-commits"
               f"?email={email}&month={month}&year={year}")
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"),
        })
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def _is_org_remote(url: str) -> bool:
    for domain in ORG_GITLAB_DOMAINS:
        if domain in url:
            return True
    return False


# ----------------------------------------------------------------------------
# File discovery
# ----------------------------------------------------------------------------
def discover(args):
    """
    Returns (main_files, subagent_files).

    main_files  — top-level session transcripts: projects/<proj>/<session>.jsonl
    subagent_files — transcripts spawned by Agent/Task tool calls, found
                     recursively under: projects/<proj>/<session>/subagents/*.jsonl
                     (Claude Code stores them one level deeper than the session).
    """
    if args.session:
        return [os.path.expanduser(args.session)], []

    root = os.path.expanduser(args.root)
    if args.project:
        proj = os.path.expanduser(args.project)
        main_files = glob.glob(os.path.join(proj, "*.jsonl"))
        subagent_files = glob.glob(os.path.join(proj, "*", "subagents", "*.jsonl"))
    else:
        main_files = glob.glob(os.path.join(root, "*", "*.jsonl"))
        subagent_files = glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl"))

    # Default scope: ALL projects, last 30 days. (The old default of "newest
    # project only" silently dropped every other project's sessions and
    # produced incomplete reports.)
    days = args.days
    if not days and args.project is None and args.session is None:
        days = 30
        print("Scope: all projects, last 30 days (default — pass --days, "
              "--project or --session to change)", file=sys.stderr)

    if days:
        cutoff = datetime.now().timestamp() - days * 86400
        main_files = [f for f in main_files if os.path.getmtime(f) >= cutoff]
        subagent_files = [f for f in subagent_files if os.path.getmtime(f) >= cutoff]

    return (sorted(main_files, key=os.path.getmtime),
            sorted(subagent_files, key=os.path.getmtime))


def main():
    # On Windows the console/file default encoding is cp1252, which cannot encode
    # the em-dashes and arrows used in the reports. Force UTF-8 everywhere.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Score Claude Code token optimization.")
    ap.add_argument("--root", default="~/.claude/projects")
    ap.add_argument("--ai-commits-api", default="https://athena.webmdhelios.com",
                    help="Base URL for AI commits API (set to '' to skip)")
    ap.add_argument("--project", help="a ~/.claude/projects/<dir> folder")
    ap.add_argument("--session", help="a single .jsonl transcript")
    ap.add_argument("--days", type=int, default=0, help="only sessions active in last N days")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--out-dir", default="",
                    help="directory to write User.md, User.pdf, IT.md, IT.pdf "
                         "(defaults to current directory)")
    args = ap.parse_args()

    files, subagent_files = discover(args)
    if not files:
        print(f"No .jsonl transcripts found under {args.root}. "
              f"Pass --session or --project.", file=sys.stderr)
        sys.exit(1)

    s = analyze_files(files)
    if subagent_files:
        fold_subagent_tokens(subagent_files, s)
    P = score_practices(s)
    ov_score, ov_letter = overall(P)

    # Fetch AI commits from helios-metrics API (best-effort; {} on failure)
    _email = None
    for _cfg in [
        os.path.expanduser("~/.claude.json"),
        os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                     "claude/.claude.json"),
        os.path.expanduser("~/.athena-config/athena-config.json"),
    ]:
        if os.path.exists(_cfg):
            try:
                with open(_cfg) as _f:
                    _d = json.load(_f)
                _email = ((_d.get("oauthAccount") or {}).get("emailAddress")
                          or _d.get("user-email") or "")
                if _email:
                    break
            except Exception:
                pass
    now = datetime.now(timezone.utc)
    ai_commits_data = fetch_ai_commits(
        args.ai_commits_api, _email or "", now.month, now.year
    )

    # Authoritative spend (billing) — best-effort; {} on failure
    spend_data = fetch_authoritative_spend(_email or "", now.month, now.year)
    if spend_data:
        print(f"Authoritative spend: ${float(spend_data['spend_usd']):.2f} "
              f"({spend_data.get('email', _email)})", file=sys.stderr)
    else:
        print("Authoritative spend unavailable — reports use the transcript "
              "estimate, clearly labelled.", file=sys.stderr)

    user_md = render_user_md(s, P, ov_score, ov_letter, files, ai_commits_data,
                             spend_data)
    it_md   = render_it_md(s, P, ov_score, ov_letter, files, ai_commits_data,
                           spend_data)
    blob = {
        "overall_score": round(ov_score, 1),
        "overall_grade": ov_letter,
        "sessions": s.sessions,
        "subagent_sessions": s.subagent_sessions,
        "token_totals": {
            "input": s.input_tokens, "output": s.output_tokens,
            "cache_creation": s.cache_creation, "cache_read": s.cache_read,
            "subagent_input": s.subagent_input_tokens,
            "subagent_output": s.subagent_output_tokens,
            "subagent_cache_creation": s.subagent_cache_creation,
            "subagent_cache_read": s.subagent_cache_read,
        },
        "practices": {k: {kk: vv for kk, vv in v.items() if kk != "advice"}
                      for k, v in P.items() if not v["observation"]},
        "observations": {k: {kk: vv for kk, vv in v.items() if kk != "advice"}
                         for k, v in P.items() if v["observation"]},
        "wasted_tokens": {
            "whole_file_reads": s.large_read_tokens_sum,
            "oversized_outputs": s.oversized_tokens_sum,
        },
        "repos": [
            {"repo": name, "path": r["path"], "branches": sorted(r["branches"]),
             "sessions": len(r["sessions"]), "turns": r["turns"],
             "commits": r["commits"], "pushes": r["pushes"],
             "remotes": sorted(r["remotes"]),
             "tokens": {"input": r["input"], "output": r["output"],
                        "cache_creation": r["cache_creation"],
                        "cache_read": r["cache_read"]},
             "estimated_cost_usd": round(r["cost"], 2)}
            for name, r in sorted(s.repos.items(), key=lambda kv: -kv[1]["cost"])
        ],
        "cost": {
            "estimated_total_usd": round(s.cost_total, 2),
            "by_tier": {t: round(c, 2) for t, c in s.cost_by_tier.items()},
            "turns_by_tier": dict(s.turns_by_tier),
            "opus_simple_turns": s.opus_simple_turns,
            "opus_simple_savings_usd": round(s.opus_simple_savings, 2),
        },
        "authoritative_spend": spend_data or None,
        "ai_commits_data": ai_commits_data,
    }

    if args.json_out:
        with open(os.path.expanduser(args.json_out), "w", encoding="utf-8") as f:
            json.dump(blob, f, indent=2)

    import subprocess, tempfile
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _gen = os.path.join(_script_dir, "generate_pdf.py")

    def _write_pdf(md_text, pdf_path):
        tmp = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8")
        tmp.write(md_text)
        tmp.close()
        result = subprocess.run(
            [sys.executable, _gen, "--input", tmp.name, "--output", pdf_path],
            capture_output=True, text=True,
        )
        os.unlink(tmp.name)
        if result.returncode == 0:
            print(f"PDF written → {pdf_path}", file=sys.stderr)
        else:
            print(f"PDF generation failed: {result.stderr.strip()}", file=sys.stderr)

    # Determine output directory
    out_dir = os.path.expanduser(args.out_dir) if args.out_dir else os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    user_md_path = os.path.join(out_dir, "User.md")
    it_md_path   = os.path.join(out_dir, "IT.md")
    user_pdf_path = os.path.join(out_dir, "User.pdf")
    it_pdf_path   = os.path.join(out_dir, "IT.pdf")

    with open(user_md_path, "w", encoding="utf-8") as f:
        f.write(user_md)
    print(f"User report → {user_md_path}", file=sys.stderr)

    with open(it_md_path, "w", encoding="utf-8") as f:
        f.write(it_md)
    print(f"IT report   → {it_md_path}", file=sys.stderr)

    _write_pdf(user_md, user_pdf_path)
    _write_pdf(it_md, it_pdf_path)

    print(user_md)


if __name__ == "__main__":
    main()
