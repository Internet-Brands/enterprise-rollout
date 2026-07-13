#!/usr/bin/env python3
"""
Convert a coaching-report or budget-packet markdown file to PDF.

Requires: reportlab  (pip install reportlab)

Usage:
  python generate_pdf.py --input budget-request-packet.md --output packet.pdf
  python generate_pdf.py --input report.md --output report.pdf
"""
import argparse
import os
import re
import sys

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
except ImportError:
    print(
        "reportlab is required for PDF generation.\n"
        "Install it with:  pip install reportlab",
        file=sys.stderr,
    )
    sys.exit(2)


# ── Colour palette ────────────────────────────────────────────────────────────
C_PRIMARY   = colors.HexColor("#1a1a2e")   # deep navy — H1
C_SECONDARY = colors.HexColor("#16213e")   # H2
C_ACCENT    = colors.HexColor("#0f3460")   # H3 / table header bg
C_TEXT      = colors.HexColor("#2d2d2d")   # body text
C_MUTED     = colors.HexColor("#666666")   # sub-text / footer
C_ROW_ALT   = colors.HexColor("#f4f6fb")   # alternating table rows
C_BORDER    = colors.HexColor("#c8d0e0")   # table borders
C_HR        = colors.HexColor("#d0d5e0")   # horizontal rule


def _make_styles():
    base = getSampleStyleSheet()
    s = {
        "h1": ParagraphStyle("h1", parent=base["Normal"],
                              fontSize=20, leading=26, textColor=C_PRIMARY,
                              fontName="Helvetica-Bold", spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Normal"],
                              fontSize=14, leading=20, textColor=C_SECONDARY,
                              fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=14),
        "h3": ParagraphStyle("h3", parent=base["Normal"],
                              fontSize=11, leading=16, textColor=C_ACCENT,
                              fontName="Helvetica-Bold", spaceAfter=4, spaceBefore=10),
        "body": ParagraphStyle("body", parent=base["Normal"],
                               fontSize=9, leading=13, textColor=C_TEXT,
                               fontName="Helvetica", spaceAfter=4),
        "bullet": ParagraphStyle("bullet", parent=base["Normal"],
                                 fontSize=9, leading=13, textColor=C_TEXT,
                                 fontName="Helvetica", leftIndent=14,
                                 bulletIndent=4, spaceAfter=2),
        "footer": ParagraphStyle("footer", parent=base["Normal"],
                                 fontSize=7, leading=10, textColor=C_MUTED,
                                 fontName="Helvetica"),
        "blockquote": ParagraphStyle("blockquote", parent=base["Normal"],
                                     fontSize=8, leading=12, textColor=C_MUTED,
                                     fontName="Helvetica-Oblique", leftIndent=16,
                                     spaceAfter=4),
        "numbered": ParagraphStyle("numbered", parent=base["Normal"],
                                   fontSize=9, leading=13, textColor=C_TEXT,
                                   fontName="Helvetica", leftIndent=18,
                                   spaceAfter=2),
        "th": ParagraphStyle("th", parent=base["Normal"],
                             fontSize=8, leading=11, textColor=colors.white,
                             fontName="Helvetica-Bold", alignment=TA_CENTER),
        "td": ParagraphStyle("td", parent=base["Normal"],
                             fontSize=8, leading=11, textColor=C_TEXT,
                             fontName="Helvetica"),
    }
    return s


def _inline(text: str, style) -> Paragraph:
    """Convert inline **bold**, *italic*, and `code` to reportlab markup."""
    # Strip characters outside Latin-1 range — WinAnsiEncoding can't encode them
    text = text.encode("latin-1", errors="ignore").decode("latin-1")
    # Escape XML special chars first (but not our own tags)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Bold: **...**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic: *...*
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    # Inline code: `...`
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    return Paragraph(text, style)


def _build_table(rows: list[list[str]], styles) -> Table:
    # First row = header (pipe-separated, may have :--: alignment hints)
    # Second row may be separator (|---|---|)
    header = rows[0]
    data_rows = [r for r in rows[2:] if r]  # skip separator row

    col_count = len(header)
    usable_w = 6.5 * inch
    col_w = usable_w / col_count

    table_data = []
    table_data.append([Paragraph(h.strip(), styles["th"]) for h in header])
    for i, row in enumerate(data_rows):
        # Pad/trim to col_count
        cells = (row + [""] * col_count)[:col_count]
        table_data.append([_inline(c.strip(), styles["td"]) for c in cells])

    tbl = Table(table_data, colWidths=[col_w] * col_count, repeatRows=1)

    ts = TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), C_ACCENT),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 8),
        ("ALIGN",       (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_ROW_ALT]),
        ("GRID",        (0, 0), (-1, -1), 0.4, C_BORDER),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ])
    tbl.setStyle(ts)
    return tbl


def _is_separator(line: str) -> bool:
    return bool(re.match(r"^\|[-|: ]+\|$", line.strip()))


def _split_pipe_row(line: str) -> list[str]:
    """Split a pipe-delimited table row into cells."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return line.split("|")


def md_to_story(md_text: str, styles: dict) -> list:
    story = []
    lines = md_text.splitlines()
    i = 0
    table_buf: list[list[str]] = []

    def flush_table():
        if len(table_buf) >= 2:
            story.append(Spacer(1, 4))
            story.append(_build_table(table_buf, styles))
            story.append(Spacer(1, 6))
        table_buf.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Table row ────────────────────────────────────────────────────────
        if stripped.startswith("|"):
            table_buf.append(_split_pipe_row(stripped))
            i += 1
            continue
        else:
            if table_buf:
                flush_table()

        # ── Blank line ───────────────────────────────────────────────────────
        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        # ── Horizontal rule ──────────────────────────────────────────────────
        if re.match(r"^-{3,}$", stripped) or re.match(r"^\*{3,}$", stripped):
            story.append(Spacer(1, 2))
            story.append(HRFlowable(width="100%", thickness=0.5, color=C_HR))
            story.append(Spacer(1, 2))
            i += 1
            continue

        # ── Headers ──────────────────────────────────────────────────────────
        m = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            sty = styles[f"h{level}"] if level <= 3 else styles["h3"]
            story.append(_inline(text, sty))
            i += 1
            continue

        # ── Bullet list ───────────────────────────────────────────────────────
        if re.match(r"^[-*]\s+", stripped):
            text = re.sub(r"^[-*]\s+", "", stripped)
            story.append(_inline("• " + text, styles["bullet"]))
            i += 1
            continue

        # ── Numbered list ─────────────────────────────────────────────────────
        m_num = re.match(r"^\d+\.\s+(.*)", stripped)
        if m_num:
            num = re.match(r"^(\d+)\.", stripped).group(1)
            text = m_num.group(1)
            story.append(_inline(f"{num}. {text}", styles["numbered"]))
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────────────
        if stripped.startswith(">"):
            text = re.sub(r"^>\s*", "", stripped)
            story.append(_inline(text, styles["blockquote"]))
            i += 1
            continue

        # ── HTML sub tag (footer) ─────────────────────────────────────────────
        if stripped.startswith("<sub>") and stripped.endswith("</sub>"):
            text = stripped[5:-6]
            story.append(Paragraph(text, styles["footer"]))
            i += 1
            continue

        # ── Regular paragraph ─────────────────────────────────────────────────
        story.append(_inline(stripped, styles["body"]))
        i += 1

    if table_buf:
        flush_table()

    return story


def generate_pdf(input_path: str, output_path: str) -> None:
    with open(input_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    styles = _make_styles()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
        title="Claude Code Coach Report",
        author="cc-coach",
    )
    story = md_to_story(md_text, styles)
    doc.build(story)


def main():
    ap = argparse.ArgumentParser(description="Convert coaching markdown to PDF.")
    ap.add_argument("--input", "-i", required=True, help="Input .md file")
    ap.add_argument("--output", "-o", required=True, help="Output .pdf file")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    generate_pdf(args.input, args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
