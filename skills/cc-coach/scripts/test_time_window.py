"""Regression checks for timestamp windows; no real transcripts or network calls."""
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analyze

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
START = NOW - timedelta(days=30)


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def turn(ts, tokens=100, cwd=None):
    entry = {"type": "assistant", "timestamp": ts,
             "message": {"model": "claude-sonnet-5-5", "content": [],
                         "usage": {"input_tokens": tokens, "output_tokens": 10}}}
    if cwd:
        entry["cwd"] = cwd
    return entry


def write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries))
    return str(path)


class TimeWindowTests(unittest.TestCase):
    def test_old_cost_compaction_tools_and_repos_do_not_affect_scores(self):
        with tempfile.TemporaryDirectory() as root:
            old = turn("2026-06-18T10:00:00Z", 1_000_000, "/old/repo")
            old["message"]["content"] = [{"type": "tool_use", "id": "old",
                                          "name": "Bash", "input": {"command": "git commit -am old"}}]
            compaction = {"type": "system", "timestamp": "2026-06-18T11:00:00Z",
                          "subtype": "compact_boundary"}
            recent = [turn(START.isoformat(), 100, "/current/repo"),
                      turn(NOW.isoformat(), 200)]
            mixed = write(Path(root) / "mixed.jsonl", [old, compaction] + recent)
            clean = write(Path(root) / "clean.jsonl", recent)
            s = analyze.analyze_files([mixed], START, NOW)
            baseline = analyze.analyze_files([clean])
            self.assertEqual(s.input_tokens, 300)
            self.assertEqual(s.assistant_turns, 2)
            self.assertEqual(s.compaction_events, 0)
            self.assertEqual(s.tool_use_total, 0)
            self.assertEqual(s.cost_total, baseline.cost_total)
            self.assertEqual(analyze.overall(analyze.score_practices(s)),
                             analyze.overall(analyze.score_practices(baseline)))
            self.assertEqual(len(s.repos), 1)
            self.assertEqual(s.first_ts, START)
            self.assertEqual(s.last_ts, NOW)

    def test_subagents_empty_sessions_missing_dates_and_offsets(self):
        with tempfile.TemporaryDirectory() as root:
            old = write(Path(root) / "old.jsonl", [turn("2026-06-18T10:00:00Z", 1_000_000)])
            current = write(Path(root) / "current.jsonl", [
                turn(None), turn("invalid"), turn("2026-10-30T00:00:00Z"),
                turn("2026-09-29T13:00:00+01:00", 100),  # exact lower bound
                turn("2026-10-29T12:00:00", 200)])  # naive timestamp = UTC
            s = analyze.analyze_files([old, current], START, NOW)
            self.assertEqual(s.sessions, 1)
            self.assertEqual(s.main_files, [current])
            self.assertEqual(s.skipped_timestamp_entries, 2)
            analyze.fold_subagent_tokens([old, current], s, START, NOW)
            self.assertEqual(s.subagent_sessions, 1)
            self.assertEqual(s.subagent_turns, 2)
            self.assertEqual(s.input_tokens, 600)
            self.assertEqual(s.subagent_input_tokens, 300)
            self.assertEqual(s.first_ts, START)
            self.assertEqual(s.last_ts, NOW)

    def test_pre_window_repo_metadata_is_carried_without_counting_old_activity(self):
        with tempfile.TemporaryDirectory() as root:
            first = turn("2026-06-18T10:00:00Z", 1_000_000, "/work/project")
            first["gitBranch"] = "main"
            path = write(Path(root) / "s.jsonl", [first, turn(NOW.isoformat())])
            s = analyze.analyze_files([path], START, NOW)
            repo = next(iter(s.repos.values()))
            self.assertEqual(repo["path"], "/work/project")
            self.assertEqual(repo["branches"], {"main"})
            self.assertEqual(repo["input"], 100)

    def test_cli_default_project_and_session_use_entry_dates_not_mtime(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "projects" / "project" / "s.jsonl"
            write(path, [turn("2026-06-18T10:00:00Z", 1_000_000), turn(NOW.isoformat(), 100)])
            # Restored files may have an old mtime despite current entries.
            os.utime(path, (0, 0))
            for flags in ([], ["--project", str(path.parent), "--days", "30"],
                          ["--session", str(path), "--days", "30"]):
                with self.subTest(flags=flags):
                    output = Path(root) / "output"
                    argv = ["analyze.py", "--root", str(Path(root) / "projects"),
                            "--out-dir", str(output), "--json-out", str(Path(root) / "report.json"),
                            "--no-history"] + flags
                    with patch("sys.argv", argv), patch.object(analyze, "datetime", Clock), \
                         patch.object(analyze, "fetch_authoritative_spend", return_value={}), \
                         patch.object(analyze, "fetch_ai_commits", return_value={}), \
                         patch("subprocess.run") as pdf, contextlib.redirect_stdout(io.StringIO()), \
                         contextlib.redirect_stderr(io.StringIO()):
                        pdf.return_value.returncode = 1
                        pdf.return_value.stderr = "No PDFs in unit test"
                        analyze.main()
                    report = json.loads((Path(root) / "report.json").read_text())
                    self.assertEqual(report["token_totals"]["input"], 100)
                    self.assertEqual(report["analysis_window"]["days"], 30)
                    self.assertEqual(report["analysis_window"]["start"], START.isoformat())
                    self.assertIn("entry timestamps", (output / "User.md").read_text())
                    self.assertNotIn("2026-06-18", (output / "User.md").read_text())

    def test_unbounded_explicit_analysis_preserves_full_history(self):
        with tempfile.TemporaryDirectory() as root:
            path = write(Path(root) / "s.jsonl", [turn("2026-06-18T10:00:00Z"), turn(None)])
            s = analyze.analyze_files([path])
            self.assertEqual(s.assistant_turns, 2)
            self.assertEqual(s.skipped_timestamp_entries, 0)


if __name__ == "__main__":
    unittest.main()
