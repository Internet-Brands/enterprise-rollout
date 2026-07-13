#!/usr/bin/env python3
"""
Build a Claude Code budget-request packet for the HelpDesk/IT desk from the
analyzer's report.json.

This turns the deterministic efficiency report into the artifact IT needs to
approve, condition, or deny a cap increase. It produces two files:

  - budget-request-packet.md : the one-page packet (spend, scorecard, repo
                               audit, justification, remediation, recommendation)
  - helpdesk-ticket.txt      : a pre-filled plain-text ticket body the developer
                               submits to the HelpDesk

IMPORTANT (governance): this script only *generates* the packet. It does not
send anything. Routing to the HelpDesk is a separate, explicitly-confirmed step
performed by the developer (see SKILL.md). The developer reviews the full packet
before it goes anywhere.

Usage:
  python build_packet.py --report report.json \
      --dev "Jane Dev" --period "May 2026" \
      --current-cap 50 --requested-cap 120 \
      --actual-spend 47.80 \
      --justification "Owning the payments migration this quarter; expected to..." \
      --helpdesk "IT HelpDesk" \
      --out-md budget-request-packet.md --out-ticket helpdesk-ticket.txt

If --actual-spend is omitted, the analyzer's *estimated* spend is used and is
clearly labelled as an estimate to be replaced with the authoritative billing
figure.
"""
import argparse, json, os, subprocess, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit

# ----------------------------------------------------------------------------
# Skill root paths
# ----------------------------------------------------------------------------
_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_POLICY_FILE = os.path.join(_SKILL_ROOT, "policy.json")
_CONNECTORS_FILE = os.path.join(_SKILL_ROOT, "connectors.json")

# ----------------------------------------------------------------------------
# Approval policy — loaded from policy.json at the skill root.
# Defaults are used if the file is missing or unreadable; they match the
# committed policy.json so the only way to change policy is to edit that file.
# ----------------------------------------------------------------------------
_POLICY_DEFAULTS = {
    "self_approve_increment": 150.0,
    "escalation_approver": "Joe",
}


def _load_policy():
    try:
        with open(_POLICY_FILE) as f:
            data = json.load(f)
        return {
            "self_approve_increment": float(
                data.get("self_approve_increment", _POLICY_DEFAULTS["self_approve_increment"])
            ),
            "escalation_approver": str(
                data.get("escalation_approver", _POLICY_DEFAULTS["escalation_approver"])
            ),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return dict(_POLICY_DEFAULTS)


APPROVAL_POLICY = _load_policy()


def _active_connectors():
    """Return list of connector names that are enabled AND have their cred env var set."""
    try:
        with open(_CONNECTORS_FILE) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    active = []
    for name, conf in cfg.items():
        if name.startswith("_") or not isinstance(conf, dict):
            continue
        if not conf.get("enabled"):
            continue
        cred_env = (conf.get("token_env") or conf.get("app_password_env")
                    or conf.get("smtp_pass_env"))
        if cred_env and not os.environ.get(cred_env):
            continue
        active.append(name)
    return active

PRACTICE_LABEL = {
    "cache_efficiency": "Cache efficiency",
    "targeted_reads": "Targeted reads",
    "output_size_discipline": "Output-size discipline",
    "context_discipline": "Context discipline",
    "model_efficiency": "Model right-sizing",
    "tool_error_rate": "Tool-call error rate",
}


def fmt_usd(x):
    return f"${x:,.2f}" if x is not None else "—"


def recommend(grade, current_cap, requested_cap, policy=APPROVAL_POLICY):
    """Efficiency verdict = coaching grade, tempered by the size of the ask.

    "Large ask" is now defined by the org's self-approve increment (default
    $150) rather than a fixed 2x multiplier — keep it consistent with
    approval_route() so the packet's two recommendation dimensions agree.
    """
    big_ask = (current_cap is not None and requested_cap is not None
               and (requested_cap - current_cap) > policy["self_approve_increment"])
    if grade in ("A", "B"):
        if big_ask:
            return ("Approve",
                    "Strong efficiency habits; even with a large increase the budget "
                    "is well-managed.")
        return ("Approve",
                "Strong efficiency habits; the requested budget is well-managed.")
    if grade == "C":
        if big_ask:
            return ("Approve with conditions",
                    "Reasonable efficiency, but a large increase — approve alongside "
                    "the remediation commitments below and re-review next cycle.")
        return ("Approve with conditions",
                "Efficiency is acceptable; approve with the remediation commitments below.")
    # D / F
    return ("Coach first, re-review in 2 weeks",
            "Material avoidable waste detected. Recommend applying the remediation "
            "commitments and re-running this audit before increasing the cap.")


def approval_route(current_cap, requested_cap, policy=APPROVAL_POLICY):
    """Routing line from the SIZE of the ask, independent of the efficiency grade."""
    inc = policy["self_approve_increment"]
    approver = policy["escalation_approver"]
    if current_cap is None or requested_cap is None:
        return ("Approval route undetermined",
                "Provide --current-cap and --requested-cap to determine routing.")
    increase = requested_cap - current_cap
    if increase <= 0:
        return ("No increase requested",
                "Requested cap is not above the current cap.")
    if increase <= inc:
        return (f"Within standard approval (increase {fmt_usd(increase)} ≤ {fmt_usd(inc)})",
                "Can be approved by the team/manager without escalation.")
    return (f"Requires {approver}'s approval "
            f"(increase {fmt_usd(increase)} exceeds the {fmt_usd(inc)} self-approve limit)",
            f"Escalate to {approver}; the increase is above what the team/manager can sign off.")


def main():
    ap = argparse.ArgumentParser(description="Build a Claude Code budget-request packet.")
    ap.add_argument("--report", required=True, help="report.json from analyze.py")
    ap.add_argument("--dev", default="(developer)")
    ap.add_argument("--period", default=datetime.now().strftime("%B %Y"))
    ap.add_argument("--current-cap", type=float, default=None)
    ap.add_argument("--requested-cap", type=float, default=None)
    ap.add_argument("--actual-spend", type=float, default=None,
                    help="authoritative monthly spend (from billing/dashboard)")
    ap.add_argument("--fetch-spend", action="store_true",
                    help="auto-fetch authoritative spend via fetch_spend.py (overridden by --actual-spend)")
    ap.add_argument("--skill-cost-usd", type=float, default=None,
                    help="cost of running the coach skill itself (passed by SKILL.md workflow)")
    ap.add_argument("--justification", default="")
    ap.add_argument("--helpdesk", default="IT HelpDesk")
    ap.add_argument("--out-md", default="budget-request-packet.md")
    ap.add_argument("--out-ticket", default="helpdesk-ticket.txt")
    ap.add_argument("--out-pdf", default=None,
                    help="if set, also write a PDF version of the packet (requires reportlab)")
    ap.add_argument("--log-out", default="log.json",
                    help="audit log path (JSON array; one entry per generation)")
    ap.add_argument("--no-log", action="store_true",
                    help="skip writing the audit log entry")
    args = ap.parse_args()

    report_path = os.path.expanduser(args.report)
    try:
        with open(report_path, encoding="utf-8") as _f:
            d = json.load(_f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Could not read report JSON at {report_path}: {e}\n"
              f"Run analyze.py with --json-out first.", file=sys.stderr)
        sys.exit(1)

    grade = d.get("overall_grade", "?")
    score = d.get("overall_score", 0)
    practices = d.get("practices", {})
    cost = d.get("cost", {})
    waste = d.get("wasted_tokens", {})
    repos = d.get("repos", [])
    ai_commits_data = d.get("ai_commits_data", {})

    est_spend = cost.get("estimated_total_usd")

    # Resolve spend: --actual-spend > --fetch-spend > transcript estimate
    if args.actual_spend is not None:
        spend = args.actual_spend
        spend_is_estimate = False
        spend_source_label = "authoritative (provided)"
    elif args.fetch_spend:
        try:
            fetch_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_spend.py")
            result = subprocess.run(
                [sys.executable, fetch_script, "--quiet"],
                capture_output=True, text=True, timeout=12,
            )
            if result.returncode == 0:
                fetched = json.loads(result.stdout.strip())
                spend = fetched.get("spend_usd")
                spend_is_estimate = False
                spend_source_label = "authoritative (Athena API)"
            else:
                spend = est_spend
                spend_is_estimate = True
                spend_source_label = "estimate (fetch failed — see logs)"
        except Exception:
            spend = est_spend
            spend_is_estimate = True
            spend_source_label = "estimate (fetch error)"
    elif (d.get("authoritative_spend") or {}).get("spend_usd") is not None:
        # analyze.py already fetched authoritative billing for this report
        auth = d["authoritative_spend"]
        spend = float(auth["spend_usd"])
        spend_is_estimate = False
        _p = auth.get("period") or {}
        spend_source_label = (f"authoritative (Athena API, "
                              f"{_p.get('month','?')}/{_p.get('year','?')})")
    else:
        spend = est_spend
        spend_is_estimate = True
        spend_source_label = "estimate (transcript-based)"
    opus_savings = cost.get("opus_simple_savings_usd", 0) or 0

    rec, rec_why = recommend(grade, args.current_cap, args.requested_cap)
    route, route_why = approval_route(args.current_cap, args.requested_cap)

    # weakest scored practices -> remediation commitments
    weak = sorted(((k, v) for k, v in practices.items() if v.get("score", 100) < 80),
                  key=lambda kv: kv[1].get("score", 100))
    commitments = []
    for k, v in weak:
        label = PRACTICE_LABEL.get(k, k.replace("_", " ").title())
        action = (v.get("action") or "").strip()
        if not action:
            action = f"Improve {label.lower()} (currently {v.get('score',0):.0f}/100)."
        commitments.append((label, v.get("score", 0), action))

    # ---------- packet markdown ----------
    L = []
    L.append("# Claude Code — Budget-Request Packet\n")
    L.append(f"**Developer:** {args.dev}  ")
    L.append(f"**Period analyzed:** {args.period}  ")
    L.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    L.append(f"**For:** {args.helpdesk}\n")

    L.append(f"## Recommendation: {rec}\n")
    L.append(f"{rec_why}\n")
    L.append(f"**Approval routing:** {route} — {route_why}\n")

    # 1. Spend
    L.append("## 1. Spend\n")
    L.append("| Item | Value |\n|---|--:|")
    L.append(f"| Current cap | {fmt_usd(args.current_cap)} |")
    if spend_is_estimate:
        L.append(f"| Spend this period | {fmt_usd(spend)} *(estimated from sessions — "
                 f"replace with billing figure)* |")
    else:
        L.append(f"| Spend this period (authoritative) | {fmt_usd(spend)} |")
    L.append(f"| Requested cap | {fmt_usd(args.requested_cap)} |")
    L.append(f"| Identified avoidable waste (model right-sizing, this window) | {fmt_usd(opus_savings)} |")
    L.append("")
    wf = waste.get("whole_file_reads", 0) or 0
    ov = waste.get("oversized_outputs", 0) or 0
    if wf or ov:
        L.append(f"_Additional avoidable token waste in the analyzed window: "
                 f"~{wf:,} tokens in whole-file reads, ~{ov:,} tokens in oversized "
                 f"tool outputs — recoverable via the remediation commitments below._\n")

    # 2. Efficiency scorecard
    L.append("## 2. Efficiency scorecard\n")
    L.append(f"**Overall grade: {grade} ({score:.0f}/100)** — habits the developer "
             f"directly controls. (Claude's own in-session choices are reported "
             f"separately in the coaching report and are *not* graded here.)\n")
    L.append("| Practice | Grade | Score | Weight | Signal |\n|---|:--:|--:|--:|---|")
    for k, v in sorted(practices.items(), key=lambda kv: -kv[1].get("weight", 0)):
        label = PRACTICE_LABEL.get(k, k.replace("_", " ").title())
        L.append(f"| {label} | {v.get('grade','-')} | {v.get('score',0):.0f} | "
                 f"{v.get('weight',0)} | {v.get('metric','')} |")
    L.append("")

    # 3. Repos
    L.append("## 3. Repos this budget is spent on\n")
    if repos:
        L.append("Repos worked in during the analyzed Claude Code sessions, with "
                 "check-ins made through Claude Code. (Captures git activity run "
                 "through Claude Code only.)\n")
        L.append("| Repo | Branch(es) | Commits | Pushes | Turns | Est. cost |\n"
                 "|---|---|--:|--:|--:|--:|")
        for r in repos:
            br = ", ".join(r.get("branches", [])) or "—"
            L.append(f"| {r.get('repo','?')} | {br} | {r.get('commits',0)} | "
                     f"{r.get('pushes',0)} | {r.get('turns',0)} | "
                     f"{fmt_usd(r.get('estimated_cost_usd',0))} |")
        L.append("")
    else:
        L.append("_No repo activity captured from the analyzed sessions._\n")

    # 3b. AI commits breakdown (if available)
    ai_summary = ai_commits_data.get("summary", {})
    if ai_summary.get("total_commits", 0) > 0:
        L.append("## 3b. AI Commits Breakdown\n")
        L.append(f"Total commits this period: **{ai_summary['total_commits']}** "
                 f"({ai_summary.get('ai_commits',0)} AI-assisted · "
                 f"{ai_summary.get('human_commits',0)} human · "
                 f"{ai_summary.get('ai_pct',0):.0f}% AI)\n")
        L.append("| Repo | Total | AI | Human | AI% | Lines Added | Lines Modified |\n"
                 "|---|--:|--:|--:|--:|--:|--:|")
        for p in ai_commits_data.get("by_project", []):
            pct = round(p["ai_commits"] / p["total_commits"] * 100) if p["total_commits"] else 0
            L.append(f"| {p['repo']} | {p['total_commits']} | {p['ai_commits']} | "
                     f"{p['total_commits']-p['ai_commits']} | {pct}% | "
                     f"{p['lines_added']} | {p['lines_modified']} |")
        L.append("")

    # 4. Justification
    L.append("## 4. Justification (developer-provided)\n")
    L.append((args.justification.strip() or
              "_(developer to complete: why the additional budget is needed — "
              "workload, role, project phase)_") + "\n")

    # 5. Remediation commitments
    L.append("## 5. Remediation commitments\n")
    if commitments:
        L.append("The developer commits to the following efficiency improvements:\n")
        for label, sc, action in commitments:
            L.append(f"- **{label}** (currently {sc:.0f}/100): {action}")
        L.append("")
    else:
        L.append("All scored practices are at or above target (80/100) — no "
                 "remediation required.\n")

    L.append("---")
    L.append("<sub>Generated by the Claude Code Coach skill from local session "
             "transcripts. Spend figures marked *estimated* are notional "
             "API-equivalent costs and should be reconciled against billing before "
             "a final cap decision.</sub>")
    md = "\n".join(L)

    # ---------- helpdesk ticket ----------
    T = []
    T.append(f"Subject: Claude Code budget-increase request — {args.dev}")
    T.append("")
    T.append(f"Requested by: {args.dev}")
    T.append(f"Period analyzed: {args.period}")
    T.append(f"Current cap: {fmt_usd(args.current_cap)}")
    T.append(f"Requested cap: {fmt_usd(args.requested_cap)}")
    T.append(f"Spend this period: {fmt_usd(spend)}"
             + ("  (estimated — see packet)" if spend_is_estimate else ""))
    T.append("")
    T.append(f"Efficiency grade: {grade} ({score:.0f}/100)")
    T.append(f"Coach recommendation: {rec}")
    T.append(f"  {rec_why}")
    T.append(f"Approval routing: {route}")
    T.append(f"  {route_why}")
    T.append("")
    if repos:
        T.append("Repos worked in (via Claude Code):")
        for r in repos:
            T.append(f"  - {r.get('repo','?')} "
                     f"[{', '.join(r.get('branches', [])) or '—'}] "
                     f"commits={r.get('commits',0)} pushes={r.get('pushes',0)} "
                     f"cost~{fmt_usd(r.get('estimated_cost_usd',0))}")
        T.append("")
    T.append("Justification:")
    T.append("  " + (args.justification.strip() or "(to be completed by developer)"))
    T.append("")
    if commitments:
        T.append("Remediation commitments:")
        for label, sc, action in commitments:
            T.append(f"  - {label}: {action}")
        T.append("")
    T.append("Full efficiency + repo audit attached: budget-request-packet.md")
    ticket = "\n".join(T)

    with open(os.path.expanduser(args.out_md), "w") as f:
        f.write(md)
    with open(os.path.expanduser(args.out_ticket), "w") as f:
        f.write(ticket)

    if not args.no_log:
        audit.record(args.log_out, audit.generated_event(
            dev=args.dev, period=args.period,
            current_cap=args.current_cap, requested_cap=args.requested_cap,
            spend=spend, spend_source=("estimate" if spend_is_estimate else "authoritative"),
            grade=grade, overall_score=score, recommendation=rec,
            approval_route=route, helpdesk=args.helpdesk,
            out_md=args.out_md, out_ticket=args.out_ticket, packet_md=md))

    print(f"wrote {args.out_md} and {args.out_ticket}")
    print(f"recommendation: {rec}")
    print(f"approval routing: {route}")
    if not args.no_log:
        print(f"audit entry appended to {args.log_out}")

    connectors = _active_connectors()
    _send_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "send_report.py")
    if connectors:
        print(f"\nConnectors available: {', '.join(connectors)}"
              f" — review the packet above, then confirm to send.")
        print(f"  Dry-run preview : python {_send_script} --packet {args.out_md} --ticket {args.out_ticket} --dev \"{args.dev}\" --period \"{args.period}\"")
        print(f"  Send (confirmed): python {_send_script} --packet {args.out_md} --ticket {args.out_ticket} --dev \"{args.dev}\" --period \"{args.period}\" --confirm")
    else:
        print(f"\nNo connector configured."
              f" Attach {args.out_md} (or paste {args.out_ticket}) to your HelpDesk ticket manually.")

    # Generate PDF if reportlab is available
    pdf_path = args.out_pdf or (os.path.splitext(args.out_md)[0] + ".pdf")
    try:
        gen_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_pdf.py")
        if os.path.exists(gen_script):
            pdf_result = subprocess.run(
                [sys.executable, gen_script, "--input", args.out_md, "--output", pdf_path],
                capture_output=True, text=True, timeout=30,
            )
            if pdf_result.returncode == 0:
                print(f"wrote {pdf_path}")
            elif pdf_result.returncode == 2:
                pass  # reportlab not installed — silent skip
    except Exception:
        pass


if __name__ == "__main__":
    main()
