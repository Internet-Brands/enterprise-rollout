# cc-coach runner for Windows (PowerShell)
# Checks for python3 / python, then runs analyze.py.
# All arguments are forwarded to analyze.py unchanged.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── 1. Find Python 3 ──────────────────────────────────────────────────────────
$Python = $null

foreach ($candidate in @("python3", "python", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        # Confirm it is actually Python 3 (not Python 2 aliased as "python")
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3") {
            $Python = $candidate
            break
        }
    }
}

if (-not $Python) {
    Write-Host ""
    Write-Host "  cc-coach requires Python 3, which was not found on your PATH."
    Write-Host ""
    Write-Host "  Install it:"
    Write-Host "    Windows Store:   search 'Python 3' in the Microsoft Store"
    Write-Host "    winget:          winget install Python.Python.3"
    Write-Host "    Official:        https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "  Make sure to check 'Add Python to PATH' during installation."
    Write-Host ""
    exit 1
}

$PyVersion = & $Python --version 2>&1
Write-Host "Using $PyVersion ($Python)"

# ── 2. Check reportlab (needed for PDF generation) ────────────────────────────
$hasReportlab = & $Python -c "import reportlab" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  reportlab is required for PDF generation but is not installed."
    Write-Host "  Install it with:"
    Write-Host ""
    Write-Host "    pip install reportlab"
    Write-Host ""
    Write-Host "  Or install all dependencies at once:"
    Write-Host ""
    Write-Host "    pip install -r `"$ScriptDir\requirements.txt`""
    Write-Host ""
    Write-Host "  PDF output will be skipped until reportlab is installed."
    Write-Host "  Continuing without PDF support..."
    Write-Host ""
}

# ── 3. Run the analyzer, forwarding all arguments ─────────────────────────────
& $Python "$ScriptDir\scripts\analyze.py" @args
exit $LASTEXITCODE
