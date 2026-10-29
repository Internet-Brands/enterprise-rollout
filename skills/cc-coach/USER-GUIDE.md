# Claude Code Token Coach — Developer User Guide

A skill that audits **your own** Claude Code usage and does two things:

1. **Coaches you** — checks model/effort fit for your work and grades token/context habits, aiming for successful results per dollar.
2. **Builds your budget request** — when you need a higher spend cap, it generates a one-page packet for the IT HelpDesk (efficiency scorecard, the repos your budget is spent on, your justification, and remediation commitments).

You run it; it reads the session history Claude Code already saved on your machine. **Transcripts stay local. On each run, the analyzer sends your configured email and billing month/year to the Athena spend and AI-commits APIs. Reports are submitted only by you.**

> **When do I need this?** Per policy, any request to raise your Claude Code spend cap must include a Coach audit. Run the skill, review `IT.pdf`, and attach it to your HelpDesk ticket.

---

## 1. Before you start

- You use **Claude Code on this machine** (so you have session history under `~/.claude/projects/`).
- **Python 3** is installed — check with `python3 --version` (on Windows, `python3` or `python`). The analysis itself uses only the standard library; **PDF output additionally needs the `reportlab` package** (`pip install reportlab`). Without it, you still get the Markdown reports.

## 2. Install

Nothing to do — it's distributed through your organization's **managed plugin marketplace**. IT enables it centrally, so it installs automatically when you start Claude Code. You may need to be on **VPN** for the first download and for auto-updates.

Depending on which git instance you have access to, you'll see it as **Claude Code Token Coach** (gitlab.webmd.com) and/or **Claude Code Token Coach 2** (git.internetbrands.com). Having at least one is enough; some people will see both.

### Confirm the skill is present

**In Claude Code (terminal / CLI):**

1. **Restart Claude Code** so it picks up the managed marketplace (make sure you're on **VPN** first).
2. Run **`/plugin`** and open the **Installed** tab. You should see **Claude Code Token Coach** (and/or **…Coach 2**) listed and enabled.
3. As a final check, run **`/doctor`**. A healthy install shows **no plugin errors**.
4. You can also just ask in a session: *"check my claude usage"* or *"run claude coach skill."* If the skill runs and produces the reports, you're good.

**In the Claude desktop app (no terminal):**

The desktop app's **Code** tab runs Claude Code and supports the same plugins — you just use the UI instead of slash commands:

1. Start or open a **Code** session (the **Code** tab, not **Chat**); be on **VPN**.
2. Click the **+** button next to the prompt box and choose **Plugins** — your installed plugins and their skills are listed. **Claude Code Token Coach** (and/or **…Coach 2**) should appear.
3. For detail or to toggle/inspect: **Settings → Customize → Plugins → Manage plugins**. A plugin that failed to load shows an **error badge** here.
4. Or simply ask in a Code session: *"check my claude usage."*

> ⚠️ **The desktop app's *Chat* tab is a different product and does not use Claude Code plugins** — this skill will **not** appear there, and there's no plugin screen for it. To use it you must be in **Claude Code**: the terminal/CLI, or the desktop app's **Code** tab.

### If you see an error

Common signs something's wrong:

- The skill is **missing** from the plugins list, or shows an **error badge** (desktop) / appears under **Errors** (`/plugin`, CLI).
- `/doctor` (CLI) reports a **plugin error**, a **validation error**, **"not cached,"** or **"failed to load."**

First, try the quick fixes:

- Confirm you're **connected to VPN**, then **fully quit and relaunch** Claude Code / the desktop app (not just a new session).
- Force a fresh pull: CLI → `/plugin` → **Marketplaces** → select → **Update**; desktop → **Settings → Customize → Plugins → Manage plugins**.

**Clone / authentication problems** — if the error mentions the repo can't be cloned, authentication failed, or git keeps asking for a password, fix your git auth and re-pull:

- **If you clone via SSH** — tell git to use SSH for these hosts instead of HTTPS, so the managed marketplace URLs resolve over your SSH key:
  ```bash
  git config --global url."ssh://git@git.internetbrands.com/".insteadOf "https://git.internetbrands.com/"
  git config --global url."ssh://git@gitlab.webmd.com/".insteadOf "https://gitlab.webmd.com/"
  ```
- **If HTTPS repeatedly asks for credentials** — configure an OS-backed secure
  credential helper, then authenticate again:

  | OS | Secure helper |
  |---|---|
  | macOS | `git config --global credential.helper osxkeychain` |
  | Windows | Install Git Credential Manager if needed, then `git credential-manager configure` (Windows Credential Manager storage) |
  | Linux desktop | Configure `git config --global credential.helper libsecret` with Git's `libsecret` helper with an unlocked Secret Service/keyring; your distribution may require installing/building the helper first |

  Check existing configuration with `git config --show-origin --get-all credential.helper`.
  Replace any existing `store` entry at its reported scope; adding a secure helper
  does not remove older plaintext copies. Do not paste credentials into chat or
  config files. Ask IT for the approved helper if your machine has no secure store.
  See [Git's credential storage guidance](https://git-scm.com/doc/credential-helpers).

After either change, **reload / re-pull the plugin** — relaunch Claude Code, or CLI → `/reload-plugins` (then `/plugin` → **Marketplaces** → **Update** to force a fresh clone); desktop → **Settings → Customize → Plugins → Manage plugins** — and confirm the skill is present (see *Confirm the skill is present* above).

If the error persists, **report it** — paste the exact error text (and a screenshot of `/doctor` if you can) into this space:

**→ https://chat.google.com/room/AAAALy0lfXE?cls=7**

Include your OS (Windows/macOS), whether you're on VPN, and which name you see (Coach or Coach 2). That's enough for us to debug the rollout on our end.

## 3. Automatic spend alerts (runs in the background)

Once the Claude Code hooks are installed, the Coach also watches your spend **for you** — you don't have to run the skill manually to find out you're near your cap.

- **What it does:** After Claude finishes responding, a background hook (`SpendCheck.sh`, wired to the **Stop** event) fetches your **authoritative month-to-date spend** from the Athena cc-coach API and checks it against your cap.
- **When it warns:** It surfaces an inline alert only when your spend is **within $20 of a cap** — that's **$80–$100** for the **$100** cap, or **$130–$150** for the **$150** cap — and not yet over. The alert nudges you to run the Coach skill for a full report and budget-request packet.
- **How often:** The check is **throttled to at most twice per day** (one AM, one PM, UTC) — it won't add latency to every response. If the API is unreachable, it stays silent and tries again next window.
- **Where the limits live:** The caps ($100 / $150), the $20 warning window, and the alert text are owned by the API **server-side**, so they can be changed without you reinstalling anything.

> The check needs `curl` and `jq` on your machine and uses your configured email to look up *your own* spend. No code or prompt content is sent — only your email.

### Installing the auto-check

The automatic spend alert ships with the **Claude Code hook setup**. To install it, follow the Claude Code setup steps in this doc:

**→ https://docs.google.com/document/d/1UGl6AXJvo6MNfAUPfqt7s5amgVP6kcd5FHum-_SAmI0/edit?usp=sharing**

## 4. Run it — the easy way (inside Claude Code)

Start a Claude Code session and say what you want in plain language:

- **Coaching:** "review my Claude Code token usage", "score my habits", "why is my context filling up so fast"
- **Budget request:** "I hit my Claude Code cap, help me request an increase", "justify my Claude Code spend to IT"

For a budget request the skill will ask you for three things:

| Input | Where to get it |
|---|---|
| Current cap | Your current limit |
| Requested cap | What you're asking for |
| Justification | One or two lines: why you need more (workload, role, project phase) |

**Your actual spend is fetched automatically** — the skill queries the Athena
billing API with your configured email and puts the authoritative month-to-date
figure in the reports and packet. You'll only be asked for a spend number if
that lookup fails (e.g. off VPN), in which case the transcript estimate is used
and clearly labelled as an estimate.

It then produces your reports — you review them and submit the IT report to the HelpDesk yourself (section 6).

## 5. What you get

Every run produces **two reports, each in Markdown and PDF**:

- **`User.md` / `User.pdf`** — your developer coaching report: overall grade, token totals, your **authoritative billing spend** (fetched from the Athena API) alongside the transcript estimate, the repo table, the scorecard, and per-habit fixes.
- **`IT.md` / `IT.pdf`** — the manager / IT-HelpDesk view: **authoritative spend**, repo activity, and the efficiency verdict. It deliberately contains **no session details, file paths, or prompt contents** — it's the file you share when requesting a budget increase.

> If the billing API can't be reached (e.g. off VPN), both reports fall back to the transcript estimate and say so explicitly.

> PDFs require the `reportlab` Python package. If it isn't installed, the `.md` files are still produced and the PDF step is skipped with a notice.

Your overall grade line also shows a trend arrow (🟢▲/🔴▼/⚪±) versus your previous run, plus a sparkline of recent scores and callouts like a multi-run streak or which practice moved the most — computed from `history.json` (last 12 runs by default, scores only, no code or session detail). The **first run ever**, or a missing/corrupted `history.json`, simply shows no trend line at all — that's expected, not an error. Pass `--no-history` to skip reading/writing it, or `--history-limit N` to change how many runs are kept.

> **History lives at one fixed location, not next to the reports.** `history.json` is always read from and written to `~/.cc-coach/history.json` — never `--out-dir`, never the current directory. This is deliberate: you can invoke the skill from a project folder, a different repo, or any of its installed copies (managed plugin, a checked-out repo, `~/.claude/skills/`), and every run still contributes to the same one trend. Pass `--history-out <path>` only when you deliberately want to test against an isolated file instead of your real history.

> **A trend jump isn't always a habit change.** If the scoring rules themselves change (weights, thresholds, or what counts as a practice — as happened in 2026-07 when tool-call error rate was removed from the grade), your trend arrow can jump even though your habits didn't. If a swing looks surprising, check whether the skill was updated between the two runs before assuming it's about you.

> **History is local and per-machine.** If you run the skill from two machines (e.g. laptop + desktop), each machine's `~/.cc-coach/history.json` is separate — there's no merging between them, so your trend may look like it "disappeared" when you switch machines. That's expected, not a bug.

## 6. Submitting to the HelpDesk

The skill **never submits reports.** Submission
is a manual step you do yourself:

1. Run the skill; it produces `User.md`/`User.pdf` (your coaching report) and
   `IT.md`/`IT.pdf` (the manager / IT view).
2. Review `IT.pdf` — it's the document IT uses to decide on a budget increase,
   and it contains only spend, repo activity, and the efficiency verdict (no
   session details, file paths, or prompt contents).
3. **Open a ticket with the IT HelpDesk and attach `IT.pdf`**, including your
   current cap, requested cap, and a one-line justification.

Reports leave your machine only when you attach and submit them. The automatic email-based API lookups still run (see Privacy).

## 7. Run it manually (optional — no Claude Code session needed)

You don't need an active Claude Code session for this. The scripts are standalone: you find the skill's folder, open a terminal there, and run two Python scripts yourself. Use this if you'd rather not ask Claude to run it, or if the skill isn't responding inside Claude Code and you want the reports anyway.

### Step 1: Find the skill's folder

Where the folder lives depends on how you got the skill.

**If it's the managed plugin (most people)** it lives under a per-version folder in the plugin cache:

- **macOS / Linux:**
  `~/.claude/plugins/cache/<marketplace>/<plugin-name>/<version>/`
- **Windows:**
  `%USERPROFILE%\.claude\plugins\cache\<marketplace>\<plugin-name>\<version>\`

  `<marketplace>` is `webmd-internal-tools` or `enterprise-rollout` (gitlab.webmd.com) or `internetbrands-internal-tools` (git.internetbrands.com). `<plugin-name>` is `claude-code-token-coach` or `claude-code-token-coach-2`. `<version>` is whatever the current release is (e.g. `1.0.10`) — list the folder to see it rather than guessing:

  ```bash
  # macOS / Linux
  ls ~/.claude/plugins/cache/*/claude-code-token-coach*/
  ```

  ```powershell
  # Windows (PowerShell)
  Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\*\claude-code-token-coach*\"
  ```

  You're looking for the folder that contains `run.sh`, `run.ps1`, and a `scripts/` subfolder — that's the one to `cd` into.

**If you have this repo checked out directly** (e.g. you're contributing to the skill itself), the folder is `skills/cc-coach/` inside your checkout of this repository — no searching needed.

### Step 2: Open a terminal there

- **macOS:** Terminal.app, or right-click the folder in Finder → **New Terminal at Folder**.
- **Linux:** your terminal emulator, then `cd` to the path from Step 1.
- **Windows:** PowerShell (search "PowerShell" in the Start menu), then `cd` to the path from Step 1. `cmd.exe` also works for `python`/`pip` commands, but the wrapper script (`run.ps1`) needs PowerShell specifically.

```bash
# macOS / Linux example
cd ~/.claude/plugins/cache/webmd-internal-tools/claude-code-token-coach/1.0.10
```

```powershell
# Windows example
cd "$env:USERPROFILE\.claude\plugins\cache\webmd-internal-tools\claude-code-token-coach\1.0.10"
```

### Step 3: Confirm Python 3 and `reportlab` are available

The wrapper script (next step) checks both of these for you and prints install instructions if either is missing — but you can check yourself first:

```bash
# macOS / Linux
python3 --version
python3 -c "import reportlab" && echo "reportlab OK"
```

```powershell
# Windows
python3 --version
python3 -c "import reportlab"
```

On Windows, if `python3` isn't recognized, try `python` or `py` instead — some installers only register one of the three.

If `reportlab` isn't installed, install it now (see the **reportlab** entry under *Common errors* below for exact commands) or just proceed — the wrapper still produces the Markdown reports without it.

### Step 4: Run the analyzer

The wrapper writes `User.md`, `User.pdf`, `IT.md`, `IT.pdf` to your **current directory**:

```bash
# macOS / Linux — last 30 days across all projects
bash run.sh --days 30 --json-out report.json
```

```powershell
# Windows
.\run.ps1 --days 30 --json-out report.json
```

`report.json` is the machine feed used to build the budget packet (Step 5). When it finishes, confirm the four report files landed where you expect — the script prints each file's full path as it writes it.

Scope options (same on both platforms):

- `--days N` — only sessions active in the last N days (across all projects)
- `--project ~/.claude/projects/<encoded-dir>` — a single project
- `--session path/to/<id>.jsonl` — a single session
- `--out-dir path/to/folder` — write the reports somewhere other than the current directory
- *(no flags)* — same as `--days 30`: **all projects** active in the last 30 days

### Step 5 (optional): Build the budget packet

Only needed if you're requesting a cap increase. Same command on macOS, Linux, and Windows — this one is plain Python, not a platform wrapper:

```bash
python3 scripts/build_packet.py --report report.json \
  --dev "Your Name" --period "June 2026" \
  --current-cap 50 --requested-cap 120 --actual-spend 48 \
  --justification "Owning the payments migration; cap is throttling mid-sprint." \
  --out-md budget-request-packet.md --out-ticket helpdesk-ticket.txt
```

On Windows, use `python` instead of `python3` if that's what Step 3 confirmed works.

Omit `--actual-spend` and the packet automatically uses the authoritative billing figure that analyze.py embedded in `report.json`; if that's absent too (API unreachable), it falls back to the transcript estimate, clearly labeled.

### Common errors when running manually

**`reportlab is required for PDF generation` / `PDF generation failed: reportlab is required...`**
This means Python ran fine but the `reportlab` package isn't installed, so only the `.md` files were written (no PDFs). Fix:

```bash
# macOS / Linux
pip3 install reportlab
# or, to install every dependency the skill needs at once:
pip3 install -r requirements.txt
```

```powershell
# Windows
pip install reportlab
# or:
pip install -r requirements.txt
```

If `pip3 install` fails with a permissions error, add `--user` (e.g. `pip3 install --user reportlab`), or create a virtual environment first:

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
.venv\Scripts\Activate.ps1      # Windows
pip install reportlab
```

Then re-run `run.sh` / `run.ps1` from that same shell — reports regenerate with PDFs included.

**`python3: command not found` (macOS/Linux) or `'python3' is not recognized...` (Windows)**
Python 3 isn't on your PATH. Install it (see section 1), or on Windows try `python` or `py` in place of `python3` in every command above — the wrapper (`run.ps1`) already tries all three automatically.

**`permission denied` when running `./run.sh`**
You invoked it directly instead of through `bash`. Either run it via `bash run.sh ...` (as shown above — this never needs execute permission) or make it executable once with `chmod +x run.sh` and then run `./run.sh ...`.

**`running scripts is disabled on this system` (Windows, running `.\run.ps1`)**
PowerShell's execution policy is blocking local scripts. Either bypass it for just this one run:

```powershell
powershell -ExecutionPolicy Bypass -File run.ps1 --days 30 --json-out report.json
```

or allow locally-created scripts for your user going forward:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**`No .jsonl transcripts found under ~/.claude/projects. Pass --session or --project.`**
No Claude Code session history was found at the default location, or your `--days`/`--project`/`--session` scope excluded everything that exists. Try a wider window (`--days 60`), confirm you're pointing at the right `--project` path, or drop the flag entirely to fall back to the last-30-days default across all projects.

## 8. How you're graded — and what *isn't* graded

**Scored (habits you control)** — these set your grade:

| Practice | Weight | Good looks like |
|---|--:|---|
| Cache efficiency | 28 | Stable CLAUDE.md / tool set within a session |
| Targeted reads | 20 | Grep then read a slice, not whole files |
| Output-size discipline | 19 | Filter long command/test output |
| Context discipline | 17 | `/clear` between unrelated tasks; manual `/compact` is never penalized |
| Model right-sizing | 16 | Review the structural signal alongside task fit; no universal model default |

**Not scored (Claude's own in-the-moment choices)** — native search vs. `cat`/`grep`, redundant re-reads, parallel batching, subagent use, and **tool-call error rate**. These are reported with a suggested CLAUDE.md rule, but **never affect your grade** — you shouldn't be penalized for something you can't control per call. (Tool errors are Claude's failed calls, not yours; user permission denials and environmental failures like VPN/auth issues are excluded from the reported figure too.)

**Repo audit** — lists the repos you worked in via Claude Code, with commits/pushes and estimated cost per repo. It shows **repo names, branches, and counts only — never your code.** It captures git activity run *through* Claude Code; commits made outside it won't appear.

## 9. Improve your grade fast

Keep a focused **CLAUDE.md**, use **`/clear`** between unrelated tasks, and
choose model **and effort** for the work. Review older-version spend first.
For routine tasks, compare lower effort on a strong model with a smaller model;
check quality, latency and retries rather than assuming fewer tokens means better
value. Read cache and context scores together: a long session may cache well
while still carrying excessive context.

See [the workload and effort guide](references/model-fit.md) for starting points.
The analyzer adds workload hints, explicitly logged effort (otherwise unknown),
older-version spend and same-token price comparisons to `User.md` and
`report.json`. These checks are unscored. The existing weights, formulas, grade
thresholds, caps and approval policy are unchanged. Chat shows a brief summary
and file links; the full report remains available on request.

## 10. Privacy

Transcript parsing and scoring run locally. **On each normal analyzer run,
your configured developer email and billing month/year are sent to the Athena
spend API and the AI-commits API**, including a prior-month lookup when needed.
The background spend hook sends your email on its throttled checks too. No
source code, prompts or transcripts are uploaded by these lookups.

The skill generates reports without submitting them. Review `IT.pdf` before
attaching it to a HelpDesk ticket yourself. The IT report contains spend,
repo activity and the verdict; `User.md` and `report.json` include more detailed
local diagnostics and should be reviewed before sharing.

## 11. Troubleshooting

- **"No .jsonl transcripts found"** — no Claude Code history at the default path, or you scoped too narrowly. Try `--days 60`, or pass `--project` / `--root`.
- **`python3: command not found`** — install Python 3 (or try `python`).
- **Cost numbers look off** — they're estimates at default API rates. If you're on a plan or different models, review version rates in `scripts/model_fit.py` and fallback `PRICING` in `scripts/analyze.py`.
- **Grade feels unfair** — check the scorecard signals; only the five scored practices count, and the unscored observations are listed separately.
- **The spend alert never fires (or fires too often)** — it's throttled to twice per day and only warns within $20 of a cap. Confirm `curl` and `jq` are installed and your email is configured; the caps and thresholds are controlled server-side (see 3).

## 12. Help

If you have any questions or concerns, you can reach out to the team via the Google Chat link: **https://chat.google.com/app/chat/AAAALy0lfXE**
