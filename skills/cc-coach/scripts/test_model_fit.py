"""Offline behavioral checks: python3 -m unittest discover -s scripts -p 'test_*.py'."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analyze
import model_fit


class FitTests(unittest.TestCase):
    def test_claude_code_effort_fields_and_per_turn_override(self):
        for level in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(level=level):
                self.assertEqual(model_fit.logged_effort({"effort": level}), level)
        self.assertEqual(model_fit.logged_effort({"effort": "high", "perTurnEffort": "medium"}), "medium")
        self.assertEqual(model_fit.logged_effort({"effort": "high", "perTurnEffort": None}), "high")
        self.assertEqual(model_fit.logged_effort({"perTurnEffort": "medium"}), "medium")
        self.assertEqual(model_fit.logged_effort({"effort": "auto"}), "unknown")
        self.assertEqual(model_fit.logged_effort({"perTurnEffort": 100}), "unknown")
        self.assertEqual(model_fit.logged_effort({"message": {"content": [{"type": "thinking"}]}}), "unknown")
        self.assertEqual(model_fit.logged_effort({"message": {"output_config": {"effort": "low"}}}), "low")

    def test_version_prices_and_cache_duration(self):
        usage = dict(input_tokens=1000, output_tokens=1000,
                     cache_creation_input_tokens=1000, cache_read_input_tokens=1000,
                     cache_creation={"ephemeral_1h_input_tokens": 500})
        # 4 fresh + 20 output + (2.5 + 4) writes + .2 read per thousand.
        self.assertAlmostEqual(analyze.turn_cost(usage, "claude-opus-5-5"), .0307)
        self.assertGreater(analyze.turn_cost(usage, "claude-opus-4-1-20250805"), .0307)
        self.assertEqual(model_fit.model_key("anthropic.claude-opus-5-5-v1:0"), "opus-5-5")
        self.assertEqual(model_fit.model_key("claude-3-5-sonnet-20241022"), "sonnet-3-5")
        self.assertIsNone(model_fit.model_key("opus"))
        self.assertIsNone(model_fit.rates("claude-opus-6-1", usage))

    def test_haiku_boundary_counts_cached_input(self):
        usage = dict(input_tokens=1, cache_read_input_tokens=99_999)
        self.assertEqual(model_fit.rates("claude-haiku-5-5", usage), (.1, .5, .01))
        usage["cache_read_input_tokens"] += 1
        self.assertEqual(model_fit.rates("claude-haiku-5-5", usage), (.5, 2.5, .05))

    def write_session(self, root):
        path = Path(root) / "session.jsonl"
        usage = dict(input_tokens=1000, output_tokens=40, cache_read_input_tokens=600_000)
        entries = [
            {"type": "user", "message": {"content": "Debug a race condition. PRIVATE_PROMPT"}},
            {"type": "assistant", "message": {"model": "claude-opus-4-6", "usage": usage,
                                               "content": [{"type": "text", "text": "Done"}]}},
            {"type": "user", "message": {"content": "Rename a typo"}},
            {"type": "assistant", "message": {"model": "claude-opus-5-5", "usage": usage,
                                               "output_config": {"effort": "low"}, "content": []}},
            {"type": "assistant", "message": {"model": "claude-opus-6-1", "usage": usage,
                                               "content": []}},
        ]
        path.write_text("\n".join(json.dumps(e) for e in entries))
        return path

    def test_fit_is_unscored_and_does_not_export_prompts(self):
        with tempfile.TemporaryDirectory() as root:
            s = analyze.analyze_files([str(self.write_session(root))])
            a = model_fit.assessment(s)
            self.assertEqual(a["workload_hints"][0]["task"], "complex")
            self.assertEqual(a["workload_hints"][0]["effort"], "unknown")
            self.assertTrue(any(r["effort"] == "low" for r in a["workload_hints"]))
            self.assertEqual(len(a["legacy_models"]), 1)
            self.assertEqual(a["legacy_models"][0]["replacement"], "claude-opus-5-5")
            self.assertTrue(a["cache_context"]["needs_review"])
            self.assertGreater(a["cache_context"]["cache_read_share"], .99)
            self.assertEqual(a["unpriced_turns"], 1)
            self.assertNotIn("PRIVATE_PROMPT", json.dumps(a))
            before = analyze.overall(analyze.score_practices(s))
            s.fit_counts.clear()
            s.legacy_models.clear()
            self.assertEqual(before, analyze.overall(analyze.score_practices(s)))
            self.assertEqual(set(analyze.WEIGHTS), {"cache_efficiency", "targeted_reads",
                             "output_size_discipline", "context_discipline", "model_efficiency"})

    def test_subagent_versions_and_effort_are_included_without_changing_habits(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.write_session(root)
            s = analyze.Stats()
            before = (s.assistant_turns, s.opus_turns, s.opus_simple_turns, s.compaction_events, s.max_session_input)
            analyze.fold_subagent_tokens([str(path)], s)
            self.assertEqual(s.subagent_turns, 3)
            self.assertTrue(all(k[0] == "unknown" for k in s.fit_counts))
            self.assertEqual(len(s.legacy_models), 1)
            self.assertEqual(before, (s.assistant_turns, s.opus_turns, s.opus_simple_turns,
                                      s.compaction_events, s.max_session_input))

    def test_cli_keeps_full_artifacts_and_prints_brief_summary(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.write_session(root)
            argv = ["analyze.py", "--session", str(path), "--out-dir", root,
                    "--json-out", str(Path(root) / "report.json"), "--no-history"]
            out, err = io.StringIO(), io.StringIO()
            # No billing, commits, PDF subprocesses or developer history in tests.
            with patch("sys.argv", argv), patch.object(analyze, "fetch_authoritative_spend", return_value={}), \
                 patch.object(analyze, "fetch_ai_commits", return_value={}), \
                 patch("subprocess.run") as run, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                run.return_value.returncode = 1
                run.return_value.stderr = "PDF dependency unavailable in test"
                analyze.main()
            user = (Path(root) / "User.md").read_text()
            it = (Path(root) / "IT.md").read_text()
            report = json.loads((Path(root) / "report.json").read_text())
            self.assertIn("Model and effort fit", user)
            self.assertIn("Repos worked in", user)
            self.assertIn("model_fit", report)
            self.assertNotIn("PRIVATE_PROMPT", user + it + json.dumps(report))
            self.assertNotIn("Model and effort fit", it)
            self.assertLess(len(out.getvalue().splitlines()), 6)
            self.assertNotIn("###", out.getvalue())
            self.assertIn("User report", err.getvalue())


if __name__ == "__main__":
    unittest.main()
