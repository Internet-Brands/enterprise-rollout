#!/usr/bin/env python3
"""
Send the cc-coach budget-request packet to the HelpDesk via an enabled connector.

Supported connectors (checked in priority order):
  gmail  — Gmail SMTP with App Password (GMAIL_FROM + GMAIL_APP_PASSWORD env vars)
  email  — Generic SMTP (SMTP_HOST + SMTP_USER + SMTP_PASS env vars)

This script NEVER sends without an explicit --confirm flag — the caller (SKILL.md
workflow) must show the packet to the developer first and pass --confirm only after
they approve.

Usage:
  python send_report.py --packet budget-request-packet.md \\
      --ticket helpdesk-ticket.txt \\
      --dev "Jane Dev" --period "May 2026" \\
      --confirm

  # Dry-run (show what would be sent, no actual send):
  python send_report.py --packet budget-request-packet.md \\
      --ticket helpdesk-ticket.txt \\
      --dev "Jane Dev" --period "May 2026"
"""

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONNECTORS_FILE = os.path.join(_SKILL_ROOT, "connectors.json")


def _load_connectors():
    try:
        with open(_CONNECTORS_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_connector():
    """
    Return (connector_name, config_dict) for the first enabled connector
    whose credentials are present in env. Returns (None, None) if none ready.
    Priority: gmail > email.
    """
    cfg = _load_connectors()
    for name in ("gmail", "email"):
        conf = cfg.get(name, {})
        if not isinstance(conf, dict) or not conf.get("enabled"):
            continue
        # Check credential env vars
        cred_env = conf.get("app_password_env") or conf.get("smtp_pass_env")
        if cred_env and not os.environ.get(cred_env):
            continue
        return name, conf
    return None, None


def _build_message(dev, period, to_addr, from_addr, cc_addr, ticket_body, packet_md):
    """Build the MIME email."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Claude Code budget-increase request — {dev}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    if cc_addr and cc_addr != to_addr:
        msg["Cc"] = cc_addr

    body = MIMEText(ticket_body, "plain", "utf-8")
    msg.attach(body)

    attachment = MIMEText(packet_md, "markdown", "utf-8")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"cc-coach-packet-{period.replace(' ', '-')}.md",
    )
    msg.attach(attachment)
    return msg


def _send_via_gmail(conf, msg):
    host = conf.get("smtp_host", "smtp.gmail.com")
    port = int(conf.get("smtp_port", 587))
    from_addr = os.environ[conf["gmail_from_env"]]
    password = os.environ[conf["app_password_env"]]
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(from_addr, password)
        server.send_message(msg)


def _send_via_smtp(conf, msg):
    host = os.environ.get(conf["smtp_host_env"], "")
    port = int(conf.get("smtp_port", 587))
    user = os.environ.get(conf.get("smtp_user_env", ""), "")
    password = os.environ.get(conf.get("smtp_pass_env", ""), "")
    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls(context=context)
        if user and password:
            server.login(user, password)
        server.send_message(msg)


def main():
    ap = argparse.ArgumentParser(description="Send cc-coach packet to HelpDesk.")
    ap.add_argument("--packet", required=True, help="Path to budget-request-packet.md")
    ap.add_argument("--ticket", required=True, help="Path to helpdesk-ticket.txt")
    ap.add_argument("--dev", default="(developer)")
    ap.add_argument("--period", default="")
    ap.add_argument("--confirm", action="store_true",
                    help="Actually send. Without this flag the script runs as a dry-run.")
    args = ap.parse_args()

    connector_name, conf = _resolve_connector()
    if not connector_name:
        print("No enabled connector with credentials found.")
        print("Enable 'gmail' or 'email' in connectors.json and set the required env vars.")
        sys.exit(1)

    packet_md = open(os.path.expanduser(args.packet)).read()
    ticket_body = open(os.path.expanduser(args.ticket)).read()

    to_addr = conf.get("to", "helpdesk2@internetbrands.com")

    if connector_name == "gmail":
        from_env = conf.get("gmail_from_env", "GMAIL_FROM")
        from_addr = os.environ.get(from_env, "")
        if not from_addr:
            print(f"env var {from_env} is not set — cannot determine sender.")
            sys.exit(1)
    else:
        from_addr = os.environ.get(conf.get("smtp_user_env", ""), "")

    cc_addr = from_addr if conf.get("cc_developer") else ""

    msg = _build_message(args.dev, args.period, to_addr, from_addr, cc_addr,
                         ticket_body, packet_md)

    recipients = [to_addr]
    if cc_addr and cc_addr != to_addr:
        recipients.append(cc_addr)

    print(f"Connector : {connector_name}")
    print(f"From      : {from_addr}")
    print(f"To        : {to_addr}")
    if cc_addr and cc_addr != to_addr:
        print(f"Cc        : {cc_addr}")
    print(f"Subject   : {msg['Subject']}")
    print(f"Attachment: {args.packet}")
    print()

    if not args.confirm:
        print("DRY RUN — no email sent. Re-run with --confirm to send.")
        return

    try:
        if connector_name == "gmail":
            _send_via_gmail(conf, msg)
        else:
            _send_via_smtp(conf, msg)
        print("Sent.")
    except Exception as e:
        print(f"Send failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
