#!/usr/bin/env python3
"""Generate synthetic Claude Code session transcripts for testing.

Writes two sessions into one project folder, each with a different cwd/repo and
git check-ins, so the repo-audit and budget-packet paths have content to work
with. Pass an output root dir (default: ./fixture_projects).
"""
import json, os, sys

root = sys.argv[1] if len(sys.argv) > 1 else "./fixture_projects"
proj = os.path.join(root, "-Users-me-work")
os.makedirs(proj, exist_ok=True)


def build(sid, cwd, branch, lines_spec):
    out = []

    def asst(blocks, usage, model="claude-opus-4-6"):
        return {"type": "assistant", "uuid": "a" + str(len(out)), "parentUuid": None,
                "timestamp": "2026-06-01T10:%02d:00Z" % (len(out) % 60),
                "sessionId": sid, "cwd": cwd, "gitBranch": branch, "version": "1.0",
                "message": {"role": "assistant", "model": model,
                            "content": blocks, "usage": usage}}

    def user(blocks):
        return {"type": "user", "uuid": "u" + str(len(out)), "parentUuid": None,
                "timestamp": "2026-06-01T10:%02d:30Z" % (len(out) % 60),
                "sessionId": sid, "cwd": cwd, "gitBranch": branch,
                "message": {"role": "user", "content": blocks}}

    for kind, payload in lines_spec(asst, user):
        out.append(json.dumps(payload))
    with open(os.path.join(proj, sid + ".jsonl"), "w") as f:
        f.write("\n".join(out) + "\n")
    return len(out)


def tu(tid, name, inp): return {"type": "tool_use", "id": tid, "name": name, "input": inp}
def tr(tid, text, err=False): return {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": err}


# ---- Session 1: the messy "app" repo (whole-file reads, oversized output,
#      redundant read, a failed call, trivial Opus turns, a compaction) ----
def s1(asst, user):
    return [
        ("u", user("Refactor the auth module and run the tests.")),
        ("a", asst([{"type": "thinking", "thinking": "plan" * 50},
                    tu("t1", "Read", {"file_path": "/app/auth.py"}),
                    tu("t2", "Grep", {"pattern": "login"})],
                   {"input_tokens": 1200, "output_tokens": 300,
                    "cache_creation_input_tokens": 8000, "cache_read_input_tokens": 2000})),
        ("u", user([tr("t1", "X" * 12000), tr("t2", "auth.py:10 def login")])),
        ("a", asst([tu("t3", "Read", {"file_path": "/app/auth.py"})],
                   {"input_tokens": 900, "output_tokens": 50,
                    "cache_creation_input_tokens": 500, "cache_read_input_tokens": 14000})),
        ("u", user([tr("t3", "X" * 12000)])),
        ("a", asst([tu("t4", "Bash", {"command": "cat build.log"})],
                   {"input_tokens": 300, "output_tokens": 40,
                    "cache_creation_input_tokens": 200, "cache_read_input_tokens": 26000})),
        ("u", user([tr("t4", "L" * 40000)])),
        ("a", asst([tu("t5", "Read", {"file_path": "/app/tests.py", "offset": 1, "limit": 40})],
                   {"input_tokens": 200, "output_tokens": 30,
                    "cache_creation_input_tokens": 100, "cache_read_input_tokens": 30000})),
        ("u", user([tr("t5", "def test_login(): ...")])),
        ("a", asst([tu("t6", "Edit", {"file_path": "/app/auth.py", "old_string": "a", "new_string": "b"})],
                   {"input_tokens": 150, "output_tokens": 40,
                    "cache_creation_input_tokens": 80, "cache_read_input_tokens": 31000})),
        ("u", user([tr("t6", "ok")])),
        ("a", asst([tu("t7", "Bash", {"command": "pytest"})],
                   {"input_tokens": 120, "output_tokens": 20,
                    "cache_creation_input_tokens": 50, "cache_read_input_tokens": 31500})),
        ("u", user([tr("t7", "command not found: pytest", True)])),
        # git check-ins through Claude Code
        ("a", asst([tu("t8", "Bash", {"command": "git commit -am 'fix auth token refresh'"})],
                   {"input_tokens": 110, "output_tokens": 25,
                    "cache_creation_input_tokens": 40, "cache_read_input_tokens": 31800})),
        ("u", user([tr("t8", "[main 1a2b3c4] fix auth token refresh")])),
        ("a", asst([tu("t9", "Bash", {"command": "git push origin main"})],
                   {"input_tokens": 90, "output_tokens": 20,
                    "cache_creation_input_tokens": 30, "cache_read_input_tokens": 32000})),
        ("u", user([tr("t9", "To github.com:acme/app.git\n   1a2b3c4..5d6e7f8  main -> main")])),
        # trivial Opus turn (no tools/thinking, short answer)
        ("a", asst([{"type": "text", "text": "Quick note: looks fine."}],
                   {"input_tokens": 60, "output_tokens": 40,
                    "cache_creation_input_tokens": 10, "cache_read_input_tokens": 32500})),
        ("s", {"type": "system", "subtype": "compact_boundary",
               "content": "compacted conversation", "sessionId": "s1",
               "cwd": "/Users/me/app", "timestamp": "2026-06-01T11:00:00Z"}),
        ("a", asst([{"type": "text", "text": "Done. Tests pass."}],
                   {"input_tokens": 80, "output_tokens": 120,
                    "cache_creation_input_tokens": 30, "cache_read_input_tokens": 33000})),
    ]


# ---- Session 2: a cleaner "api" repo session, mostly Sonnet, good habits ----
def s2(asst, user):
    return [
        ("u", user("Add a rate-limit header to the /search endpoint; show me just the handler.")),
        ("a", asst([tu("u1", "Grep", {"pattern": "def search"}),
                    tu("u2", "Read", {"file_path": "/api/routes.py", "offset": 40, "limit": 30})],
                   {"input_tokens": 400, "output_tokens": 120,
                    "cache_creation_input_tokens": 1500, "cache_read_input_tokens": 9000},
                   model="claude-sonnet-4-6")),
        ("u", user([tr("u1", "routes.py:42 def search"), tr("u2", "def search(req): ...")])),
        ("a", asst([tu("u3", "Edit", {"file_path": "/api/routes.py", "old_string": "return resp", "new_string": "resp.headers['X-RateLimit'] = limit; return resp"})],
                   {"input_tokens": 250, "output_tokens": 90,
                    "cache_creation_input_tokens": 100, "cache_read_input_tokens": 12000},
                   model="claude-sonnet-4-6")),
        ("u", user([tr("u3", "ok")])),
        ("a", asst([tu("u4", "Bash", {"command": "git commit -am 'add rate-limit header'"})],
                   {"input_tokens": 120, "output_tokens": 30,
                    "cache_creation_input_tokens": 40, "cache_read_input_tokens": 13000},
                   model="claude-sonnet-4-6")),
        ("u", user([tr("u4", "[feature/ratelimit 9z8y7x] add rate-limit header")])),
        ("a", asst([{"type": "text", "text": "Added the header and committed on feature/ratelimit."}],
                   {"input_tokens": 90, "output_tokens": 110,
                    "cache_creation_input_tokens": 20, "cache_read_input_tokens": 13500},
                   model="claude-sonnet-4-6")),
    ]


n1 = build("11111111-2222-3333-4444-555555555555", "/Users/me/app", "main", s1)
n2 = build("99999999-8888-7777-6666-555555555555", "/Users/me/api", "feature/ratelimit", s2)
print(f"wrote {n1}+{n2} lines into {proj}")
