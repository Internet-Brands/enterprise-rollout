"""Local, unscored model/effort coaching. No prompts are retained in results."""
import re

# Verified 2026-10-29 against https://platform.claude.com/docs/en/about-claude/pricing
# USD/M tokens: fresh input, output, cache read. Five-minute writes use 1.25x.
CURRENT = {"opus": "5-5", "sonnet": "5-5", "haiku": "5-5", "fable": "5-1"}
RATES = {
    "opus-5-5": (4, 20, .20), "sonnet-5-5": (2, 10, .10),
    "haiku-5-5": (.10, .50, .01), "fable-5-1": (10, 50, .25),
    "opus-5": (5, 25, .50), "fable-5": (10, 50, 1),
    "sonnet-5": (2, 10, .20),
    **{f"opus-4-{v}": (5, 25, .50) for v in (5, 6, 7, 8)},
    "opus-4": (15, 75, 1.50), "opus-4-1": (15, 75, 1.50),
    **{f"sonnet-{v}": (3, 15, .30) for v in ("4", "4-5", "4-6", "3-5", "3-7")},
    "haiku-4-5": (1, 5, .10), "haiku-3-5": (.80, 4, .08),
    "opus-3": (15, 75, 1.50), "sonnet-3": (3, 15, .30),
    "haiku-3": (.25, 1.25, .025),
}
FIT_GUIDE = {
    "routine": ("Mechanical edits, formatting, extraction", "Haiku 5.5 or Sonnet 5.5", "low"),
    "implementation": ("Well-specified features and tests", "Sonnet 5.5 or Opus 5.5", "medium"),
    "complex": ("Architecture, difficult debugging, broad refactors", "Opus 5.5", "high"),
    "deep": ("Long-horizon reasoning after measured quality gaps", "Opus 5.5; Fable 5.1 if needed", "high; xhigh/max only after evaluation"),
    "unknown": ("Insufficient task evidence", "Confirm the work before advising", "unknown"),
}


def model_key(model):
    # Supports API IDs, dated snapshots, Bedrock prefixes and Vertex @dates.
    match = re.search(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2})(?!\d))?", model or "", re.I)
    if not match:
        old = re.search(r"claude-(3)(?:-(5|7))?-(opus|sonnet|haiku)(?=$|[-@:.])", model or "", re.I)
        if not old:
            return None
        major, minor, tier = old.groups()
    else:
        tier, major, minor = match.groups()
    return f"{tier.lower()}-{major}" + (f"-{minor}" if minor else "")


def rates(model, usage):
    key = model_key(model)
    if key == "haiku-5-5":
        window = sum(usage.get(k, 0) or 0 for k in
                     ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        if window > 100_000:
            return (.50, 2.50, .05)
    return RATES.get(key)


def cost_at_rates(usage, prices):
    inp, out, read = prices
    creation = usage.get("cache_creation_input_tokens", 0) or 0
    cache = usage.get("cache_creation") or {}
    hour = min(creation, cache.get("ephemeral_1h_input_tokens", 0) or 0)
    return ((usage.get("input_tokens", 0) or 0) * inp
            + (usage.get("output_tokens", 0) or 0) * out
            + (creation - hour) * inp * 1.25 + hour * inp * 2
            + (usage.get("cache_read_input_tokens", 0) or 0) * read) / 1_000_000


def task_kind(content):
    # These are low-confidence workload hints, never a difficulty verdict.
    if isinstance(content, list):
        text = " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = content if isinstance(content, str) else ""
    for kind, pattern in (
        ("deep", r"\b(long.horizon|research problem|prove|proof)\b"),
        ("complex", r"\b(architect\w*|debug\w*|refactor\w*|race condition|migration)\b"),
        ("implementation", r"\b(implement\w*|add\w*|feature\w*|test\w*|endpoint)\b"),
        ("routine", r"\b(format\w*|rename\w*|typo\w*|extract\w*|classify|mechanical)\b"),
    ):
        if re.search(pattern, text, re.I):
            return kind
    return "unknown"


def logged_effort(entry):
    msg = entry.get("message") or {}
    value = ((msg.get("output_config") or {}).get("effort")
             or (entry.get("output_config") or {}).get("effort")
             or entry.get("effortLevel") or msg.get("effort"))
    return value if value in ("low", "medium", "high", "xhigh", "max") else "unknown"


def record(s, entry, task, cost):
    model = (entry.get("message") or {}).get("model") or "unknown"
    effort = logged_effort(entry)
    s.fit_counts[(task, model, effort)] += 1
    s.cost_by_model[model] += cost
    key = model_key(model)
    if not key or key not in RATES:
        s.unpriced_turns += 1
        return
    tier, version = key.split("-", 1)
    # Only known older versions; unknown/future IDs and aliases are never legacy.
    if tuple(map(int, version.split("-"))) >= tuple(map(int, CURRENT[tier].split("-"))):
        return
    target = f"claude-{tier}-{CURRENT[tier]}"
    usage = (entry.get("message") or {}).get("usage") or {}
    delta = max(0, cost - cost_at_rates(usage, rates(target, usage)))
    item = s.legacy_models.setdefault(model, {"model": model, "replacement": target,
                                             "turns": 0, "estimated_cost_usd": 0,
                                             "same_tokens_savings_usd": 0})
    item["turns"] += 1
    item["estimated_cost_usd"] += cost
    item["same_tokens_savings_usd"] += delta


def assessment(s, big_session_tokens=500_000):
    cache_total = s.input_tokens + s.cache_creation + s.cache_read
    cache_share = s.cache_read / cache_total if cache_total else 0
    return {
        "scored": False,
        "workload_hints": [dict(task=k[0], model=k[1], effort=k[2], turns=n)
                           for k, n in sorted(s.fit_counts.items())],
        "legacy_models": list(s.legacy_models.values()),
        "unpriced_turns": s.unpriced_turns,
        "cache_context": {
            "cache_read_share": cache_share,
            "peak_input_tokens": s.max_session_input,
            "sessions": s.sessions,
            "auto_compacted_sessions": s.sessions_with_compaction,
            "needs_review": s.max_session_input > big_session_tokens or s.sessions_with_compaction > 0,
        },
    }


def render(s, big_session_tokens=500_000):
    a = assessment(s, big_session_tokens)
    lines = ["### Model and effort fit (unscored)",
             "Optimize successful results per dollar, balancing quality and latency. "
             "Workload hints below come from developer prompts, not measured task difficulty. "
             "Confirm the work and its outcome before changing model or effort. "
             "Task success, rework and end-to-end latency are not measured here.",
             "| Workload hint | Model observed | Effort logged | Turns |",
             "|---|---|---|--:|"]
    for row in a["workload_hints"]:
        model = re.sub(r"[^a-zA-Z0-9_.:@/-]", "_", row["model"])
        lines.append(f"| {row['task']} | {model} | {row['effort']} | {row['turns']} |")
    lines += ["", "Missing effort means unknown; never infer it from output length or thinking blocks.",
              "", "| Kind of work | Candidate model | Starting effort |", "|---|---|---|"]
    for label, model, effort in FIT_GUIDE.values():
        lines.append(f"| {label} | {model} | {effort} |")
    lines += ["", "For routine work, compare a strong model at low/medium effort with a smaller model. "
              "They can have similar task cost; validate quality, retries, latency and total spend. "
              "Lower effort changes token use, not the price per token; no fixed savings are assumed.",
              "", "**Older model versions:**"]
    if a["legacy_models"]:
        for item in a["legacy_models"]:
            model = re.sub(r"[^a-zA-Z0-9_.:@/-]", "_", item["model"])
            lines.append(f"- `{model}`: {item['turns']} turns, ~${item['estimated_cost_usd']:.2f} estimated spend. "
                         f"Evaluate `{item['replacement']}` in the same tier "
                         f"(~${item['same_tokens_savings_usd']:.2f} potential list-cost reduction at identical token usage).")
    else:
        lines.append("No known older versions detected; unversioned aliases remain unknown.")
    lines.append("Same-token comparisons are scenarios, not realized savings or a guarantee of identical outcomes. "
                 "Check availability, compatibility and representative tasks before migrating.")
    if a["unpriced_turns"]:
        lines.append(f"{a['unpriced_turns']} turn(s) have unknown version pricing; estimates use fallback tier rates.")
    c = a["cache_context"]
    lines += ["", "**Cache and context together:** "
              f"{c['cache_read_share']:.1%} cache-read share; peak input ~{c['peak_input_tokens']:,} tokens; "
              f"{c['auto_compacted_sessions']}/{c['sessions']} main sessions auto-compacted. "
              + ("Review context growth even with a high cache score: a large cached prefix still costs on every turn. "
                 "Use /clear between unrelated tasks or a focused /compact for continuing work."
                 if c["needs_review"] else
                 "Cache reuse alone does not establish efficiency; confirm task boundaries and context growth."),
              "One long session can produce a high cache score. Read both practice scores together; "
              "the grade is a habit rubric, not a measured result-per-dollar ranking.", ""]
    return "\n\n".join(lines[:2]) + "\n\n" + "\n".join(lines[2:])
