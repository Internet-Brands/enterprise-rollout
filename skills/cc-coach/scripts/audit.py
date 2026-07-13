#!/usr/bin/env python3
"""
Lightweight audit/compliance log for the Claude Code Coach skill.

Records *what happened* — packet generation and (later) HelpDesk submission —
without ever recording anything sensitive. The log is a plain JSON array in
`log.json`, appended to via load-modify-write (volume is one entry per budget
request, so a valid-JSON array beats append-only JSONL for reviewer-friendliness).

Privacy rules (enforced by what this module accepts, not by hope):
  - NEVER log source code, prompt contents, or tool output.
  - NEVER log secrets/tokens (connectors read those at send time and pass them
    here redacted, if at all).
  - Store a content *hash* of the packet (`packet_sha256`), not the packet body,
    for tamper-evidence without duplication.
  - Timestamps are absolute UTC (ISO-8601, 'Z').

Usage (from build_packet.py / a future submit.py):
    import audit
    audit.record(log_path, audit.generated_event(...))
"""
import hashlib
import json
import os
from datetime import datetime, timezone

# Keys that must never appear in an audit record. If a caller passes one, we
# drop it rather than persist it — defense against accidental secret logging.
_FORBIDDEN_KEYS = {
    "token", "api_key", "apikey", "admin_key", "password", "secret",
    "authorization", "bearer", "smtp_pass", "youtrack_token",
    "packet_md", "ticket_txt", "code", "prompt", "content",
}


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def packet_hash(text):
    """SHA-256 of the packet markdown — tamper-evidence without storing the body."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scrub(record):
    """Drop any forbidden key (case-insensitive) before persisting."""
    return {k: v for k, v in record.items()
            if k.lower() not in _FORBIDDEN_KEYS}


def generated_event(dev, period, current_cap, requested_cap, spend,
                    spend_source, grade, overall_score, recommendation,
                    approval_route, helpdesk, out_md, out_ticket, packet_md):
    """Audit record for a packet-generation event."""
    return {
        "timestamp": _utc_now_iso(),
        "event": "generated",
        "developer": dev,
        "period": period,
        "current_cap": current_cap,
        "requested_cap": requested_cap,
        "spend": spend,
        "spend_source": spend_source,          # "authoritative" | "estimate"
        "grade": grade,
        "overall_score": overall_score,
        "recommendation": recommendation,
        "approval_route": approval_route,
        "helpdesk": helpdesk,
        "packet_sha256": packet_hash(packet_md),
        "outputs": {"packet": out_md, "ticket": out_ticket},
    }


def submitted_event(dev, period, channel, ticket_id, packet_md,
                    approved_by, approved_at):
    """Audit record for a HelpDesk-submission event (used by the future connector)."""
    return {
        "timestamp": _utc_now_iso(),
        "event": "submitted",
        "developer": dev,
        "period": period,
        "channel": channel,                    # "youtrack" | "email" | ...
        "ticket_id": ticket_id,
        "packet_sha256": packet_hash(packet_md),
        "approved_by": approved_by,
        "approved_at": approved_at,
    }


def record(log_path, event):
    """Append one scrubbed event to the JSON-array log at log_path."""
    path = os.path.expanduser(log_path)
    entries = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        except (json.JSONDecodeError, OSError):
            entries = []  # corrupt/unreadable log -> start fresh rather than crash
    entries.append(_scrub(event))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    return path
