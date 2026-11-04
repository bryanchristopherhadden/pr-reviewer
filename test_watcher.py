import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from watcher import parse_hunks, scan, scan_github


class ParseHunks(unittest.TestCase):
    def test_line_numbers_and_diff_like_content(self):
        text = (
            "diff --git a/a.sql b/a.sql\n--- a/a.sql\n+++ b/a.sql\n"
            "@@ -2,2 +2,2 @@ def f():\n keep\n--- old comment\n+++ new comment\n"
        )
        [hunk] = parse_hunks(text)
        self.assertEqual(hunk["file"], "a.sql")
        self.assertEqual(hunk["enclosing"], "def f():")
        self.assertEqual(
            [(l["type"], l.get("old_line"), l.get("new_line")) for l in hunk["lines"]],
            [("context", 2, 2), ("del", 3, None), ("add", None, 3)],
        )

    def test_deleted_file_keeps_old_path(self):
        text = "diff --git a/x b/x\n--- a/x\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
        [hunk] = parse_hunks(text)
        self.assertEqual(hunk["file"], "x")
        self.assertIsNone(hunk["new_file"])


class Scan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        self.data = Path(tmp.name) / "data"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.commit("app.py", "one\n")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def commit(self, name, content):
        (self.repo / name).write_text(content)
        self.git("add", name)
        self.git("commit", "-qm", f"change {name}")

    def scan(self):
        return [json.loads(p.read_text()) for p in scan(self.repo, self.data, "main")]

    def test_first_scan_is_only_a_baseline(self):
        self.assertEqual(self.scan(), [])

    def test_commit_on_base_is_reported_once(self):
        self.scan()
        self.commit("app.py", "one\ntwo\n")
        [change] = self.scan()
        self.assertEqual(change["branch"], "main")
        self.assertEqual(self.scan(), [])

    def test_branch_lifecycle(self):
        self.scan()
        self.git("switch", "-qc", "feature/x")
        self.assertEqual(self.scan(), [], "branch level with main has nothing to review")
        self.commit("new.py", "hello\n")
        [change] = self.scan()
        self.assertEqual(change["branch"], "feature/x")
        self.assertEqual(change["hunks"][0]["file"], "new.py")

    def test_branch_ignores_later_commits_on_base(self):
        self.scan()
        self.git("switch", "-qc", "feature")
        self.commit("new.py", "hello\n")
        self.git("switch", "-q", "main")
        self.commit("app.py", "one\ntwo\n")
        self.git("switch", "-q", "feature")
        changes = {c["branch"]: c for c in self.scan()}
        self.assertEqual([h["file"] for h in changes["feature"]["hunks"]], ["new.py"])


class ScanGithub(unittest.TestCase):
    DIFF = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.head = "a" * 40
        self.fail_compare = False

    def fake_gh(self, *args):
        if args[:2] == ("pr", "list"):
            return json.dumps([{
                "number": 7, "title": "T", "url": "u", "author": {"login": "me"},
                "headRefName": "feature", "headRefOid": self.head, "baseRefName": "main",
            }])
        if self.fail_compare:
            raise RuntimeError("HTTP 502")
        self.assertIn(f"compare/main...{self.head}", args[1])
        return "b" * 40 + "\n" if "--jq" in args else self.DIFF

    def scan(self):
        with mock.patch("watcher.gh", self.fake_gh), mock.patch("sys.stderr"):
            return scan_github("o/r", self.data)

    def test_reports_each_head_once(self):
        [path] = self.scan()
        change = json.loads(path.read_text())
        self.assertEqual((change["pr"], change["old_sha"]), (7, "b" * 40))
        self.assertEqual(self.scan(), [])
        self.head = "c" * 40
        self.assertEqual(len(self.scan()), 1)

    def test_failed_fetch_is_retried(self):
        self.fail_compare = True
        self.assertEqual(self.scan(), [])
        self.fail_compare = False
        self.assertEqual(len(self.scan()), 1)


if __name__ == "__main__":
    unittest.main()
