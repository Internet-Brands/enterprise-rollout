#!/usr/bin/env bash
# cc-coach runner for macOS / Linux
# Checks for python3 and reportlab, then runs analyze.py.
# Generates User.md, User.pdf, IT.md, IT.pdf in the current directory.
# All arguments are forwarded to analyze.py unchanged.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Check python3 ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  cc-coach requires Python 3, which was not found on your PATH."
    echo ""
    echo "  Install it:"
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "    macOS (Homebrew):  brew install python3"
        echo "    macOS (official):  https://www.python.org/downloads/"
    else
        echo "    Ubuntu / Debian:   sudo apt install python3 python3-pip"
        echo "    Fedora / RHEL:     sudo dnf install python3 python3-pip"
        echo "    Other:             https://www.python.org/downloads/"
    fi
    echo ""
    exit 1
fi

PYTHON=$(command -v python3)
PY_VERSION=$("$PYTHON" --version 2>&1)
echo "Using $PY_VERSION ($PYTHON)"

# ── 2. Check reportlab (needed for PDF generation) ────────────────────────────
if ! "$PYTHON" -c "import reportlab" &>/dev/null; then
    echo ""
    echo "  reportlab is required for PDF generation but is not installed."
    echo "  Install it with:"
    echo ""
    echo "    pip3 install reportlab"
    echo ""
    echo "  Or install all dependencies at once:"
    echo ""
    echo "    pip3 install -r \"$SCRIPT_DIR/requirements.txt\""
    echo ""
    echo "  PDF output will be skipped until reportlab is installed."
    echo "  Continuing without PDF support..."
    echo ""
fi

# ── 3. Run the analyzer, forwarding all arguments ─────────────────────────────
exec "$PYTHON" "$SCRIPT_DIR/scripts/analyze.py" "$@"
