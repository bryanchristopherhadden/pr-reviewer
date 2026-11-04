import unittest

from run import build_review, comment_lines

CHANGE = {
    "new_sha": "a" * 40,
    "hunks": [{
        "file": "app.py",
        "lines": [
            {"type": "context", "old_line": 1, "new_line": 1, "text": "x = 1"},
            {"type": "add", "new_line": 2, "text": "y = x / 0"},
            {"type": "del", "old_line": 2, "text": "old"},
        ],
    }],
}
REVIEW = {
    "model": "claude-haiku-5-5",
    "hunks": [{
        "file": "app.py",
        "error": None,
        "comments": [
            {"line": 2, "severity": "bug", "comment": "division by zero"},
            {"line": 99, "severity": "warning", "comment": "outside the diff"},
        ],
    }],
}


class BuildReview(unittest.TestCase):
    def test_comment_lines_uses_new_side_only(self):
        self.assertEqual(comment_lines(CHANGE), {("app.py", 1), ("app.py", 2)})

    def test_inline_when_in_diff_body_otherwise(self):
        payload = build_review(CHANGE, REVIEW)
        self.assertEqual(payload["commit_id"], "a" * 40)
        self.assertEqual(payload["event"], "COMMENT")
        self.assertEqual(payload["comments"], [{
            "path": "app.py", "line": 2, "side": "RIGHT",
            "body": "**bug**: division by zero",
        }])
        self.assertIn("`app.py:99`", payload["body"])
        self.assertIn("Bryan's Robot", payload["body"])
        self.assertIn("reviewed 1 hunks and found 2 thing(s)", payload["body"])

    def test_reports_failed_hunks(self):
        review = {"model": "m", "hunks": [{"file": "a", "error": "boom", "comments": []}]}
        payload = build_review({"new_sha": "s", "hunks": []}, review)
        self.assertIn("1 hunk(s) got stuck", payload["body"])


if __name__ == "__main__":
    unittest.main()
