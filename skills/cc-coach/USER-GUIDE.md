# Claude Code Token Coach — Developer User Guide

A skill that audits **your own** Claude Code usage and does two things:

1. **Coaches you** — grades how efficiently you use tokens/context and tells you exactly what to fix.
2. **Builds your budget request** — when you need a higher spend cap, it generates a one-page packet for the IT HelpDesk (efficiency scorecard, the repos your budget is spent on, your justification, and remediation commitments).

You run it; it reads the session history Claude Code already saved on your machine. **Nothing leaves your machine unless you explicitly approve sending it.**

> **When do I need this?** Per policy, any request to raise your Claude Code spend cap must include a Coach audit. Run the skill, review the packet, and submit it with your request.

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
- **If you clone via HTTPS but are prompted for a password every time** — set up a credential helper so git stores your credentials:
  ```bash
  git config --global credential.helper store
  ```
  Then authenticate once more; the next clone/pull saves the credentials and stops prompting.

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

It then produces your coaching report **and** the budget packet, and shows you everything **before** anything is sent.

## 5. What you get

Every run produces **two reports, each in Markdown and PDF**:

- **`User.md` / `User.pdf`** — your developer coaching report: overall grade, token totals, your **authoritative billing spend** (fetched from the Athena API) alongside the transcript estimate, the repo table, the scorecard, and per-habit fixes.
- **`IT.md` / `IT.pdf`** — the manager / IT-HelpDesk view: **authoritative spend**, repo activity, and the efficiency verdict. It deliberately contains **no session details, file paths, or prompt contents** — it's the file you share when requesting a budget increase.

> If the billing API can't be reached (e.g. off VPN), both reports fall back to the transcript estimate and say so explicitly.

> PDFs require the `reportlab` Python package. If it isn't installed, the `.md` files are still produced and the PDF step is skipped with a notice.

## 6. Submitting to the HelpDesk

The skill **never auto-sends.** It shows you the full packet — including the repo audit — and waits for your OK. After you approve, either:

- it submits through a connected channel if your org set one up, **or**
- you attach `budget-request-packet.md` (and/or paste `helpdesk-ticket.txt`) into your HelpDesk ticket yourself.

You always see exactly what will be sent first.

## 7. Run it manually (optional — no Claude Code session needed)

The scripts are standalone. Use the platform wrapper, which checks for Python 3 and `reportlab` first, then writes `User.md`, `User.pdf`, `IT.md`, `IT.pdf` to the current directory:

```bash
# macOS / Linux — last 30 days across all projects
bash run.sh --days 30 --json-out report.json

# Windows
.\run.ps1 --days 30 --json-out report.json
```

`report.json` is the machine feed used to build the budget packet (next step). Run the wrapper from the skill's folder (for a managed-plugin install it lives under `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`).

Scope options:

- `--days N` — only sessions active in the last N days (across all projects)
- `--project ~/.claude/projects/<encoded-dir>` — a single project
- `--session path/to/<id>.jsonl` — a single session
- *(no flags)* — same as `--days 30`: **all projects** active in the last 30 days

Then the budget packet:

```bash
python3 scripts/build_packet.py --report report.json \
  --dev "Your Name" --period "June 2026" \
  --current-cap 50 --requested-cap 120 --actual-spend 48 \
  --justification "Owning the payments migration; cap is throttling mid-sprint." \
  --out-md budget-request-packet.md --out-ticket helpdesk-ticket.txt
```

Omit `--actual-spend` and the packet automatically uses the authoritative billing figure that analyze.py embedded in `report.json`; if that's absent too (API unreachable), it falls back to the transcript estimate, clearly labeled.

## 8. How you're graded — and what *isn't* graded

**Scored (habits you control)** — these set your grade:

| Practice | Weight | Good looks like |
|---|--:|---|
| Cache efficiency | 28 | Stable CLAUDE.md / tool set within a session |
| Targeted reads | 20 | Grep then read a slice, not whole files |
| Output-size discipline | 19 | Filter long command/test output |
| Context discipline | 17 | `/clear` between unrelated tasks; manual `/compact` is never penalized |
| Model right-sizing | 16 | Default Sonnet; Opus only for hard work |

**Not scored (Claude's own in-the-moment choices)** — native search vs. `cat`/`grep`, redundant re-reads, parallel batching, subagent use, and **tool-call error rate**. These are reported with a suggested CLAUDE.md rule, but **never affect your grade** — you shouldn't be penalized for something you can't control per call. (Tool errors are Claude's failed calls, not yours; user permission denials and environmental failures like VPN/auth issues are excluded from the reported figure too.)

**Repo audit** — lists the repos you worked in via Claude Code, with commits/pushes and estimated cost per repo. It shows **repo names, branches, and counts only — never your code.** It captures git activity run *through* Claude Code; commits made outside it won't appear.

## 9. Improve your grade fast

The three highest-leverage moves: keep a solid **CLAUDE.md** so Claude stops re-exploring; **`/clear`** between unrelated tasks; **default to Sonnet** and reserve Opus for genuinely hard reasoning. Your report names your single weakest area and the exact fix.

## 10. Privacy

Everything is computed locally from your own transcripts. The only data that leaves your machine is the packet you explicitly approve, and it contains efficiency metrics plus repo names/branches/counts — **no source code and no prompt contents.**

## 11. Troubleshooting

- **"No .jsonl transcripts found"** — no Claude Code history at the default path, or you scoped too narrowly. Try `--days 60`, or pass `--project` / `--root`.
- **`python3: command not found`** — install Python 3 (or try `python`).
- **Cost numbers look off** — they're estimates at default API rates. If you're on a plan or different models, edit `PRICING` in `scripts/analyze.py`.
- **Grade feels unfair** — check the scorecard signals; only the five scored practices count, and the unscored observations are listed separately.
- **The spend alert never fires (or fires too often)** — it's throttled to twice per day and only warns within $20 of a cap. Confirm `curl` and `jq` are installed and your email is configured; the caps and thresholds are controlled server-side (see 3).

## 12. Help

If you have any questions or concerns, you can reach out to the team via the Google Chat link: **https://chat.google.com/app/chat/AAAALy0lfXE**
