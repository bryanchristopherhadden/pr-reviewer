import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from reviewer import parse_comments, render_hunk, review_change, load_env


def fake_client(text):
    block = SimpleNamespace(type="text", text=text)
    create = lambda **kwargs: SimpleNamespace(content=[block])
    return SimpleNamespace(messages=SimpleNamespace(create=create))


HUNK = {
    "file": "app.py",
    "enclosing": "def f():",
    "lines": [
        {"type": "context", "old_line": 1, "new_line": 1, "text": "x = 1"},
        {"type": "add", "new_line": 2, "text": "y = x / 0"},
    ],
}


class Parse(unittest.TestCase):
    def test_keeps_valid_items_and_drops_bad_ones(self):
        text = '[{"line": 2, "severity": "bug", "comment": "div by zero"},' \
               ' {"line": "2", "severity": "bug", "comment": "bad line type"},' \
               ' {"line": 3, "severity": "critical", "comment": "bad severity"}]'
        self.assertEqual(parse_comments(text), [
            {"line": 2, "severity": "bug", "comment": "div by zero"},
        ])

    def test_empty_array(self):
        self.assertEqual(parse_comments("[]"), [])

    def test_tolerates_prose_around_json(self):
        self.assertEqual(parse_comments('Here you go: [] thanks'), [])

    def test_no_array_raises(self):
        with self.assertRaises(ValueError):
            parse_comments("no json here")


class Render(unittest.TestCase):
    def test_shows_both_line_numbers(self):
        text = render_hunk(HUNK)
        self.assertIn("File: app.py", text)
        self.assertIn("new=    2 +y = x / 0", text)


class ReviewChange(unittest.TestCase):
    def test_collects_comments_per_hunk(self):
        client = fake_client('[{"line": 2, "severity": "bug", "comment": "boom"}]')
        review = review_change(client, {"repo": "r", "branch": "b", "new_sha": "s",
                                        "hunks": [HUNK]})
        self.assertIsNone(review["hunks"][0]["error"])
        self.assertEqual(review["hunks"][0]["comments"][0]["line"], 2)

    def test_api_failure_is_recorded_not_raised(self):
        import anthropic

        def boom(**kwargs):
            raise anthropic.APIConnectionError(request=None)

        client = SimpleNamespace(messages=SimpleNamespace(create=boom))
        review = review_change(client, {"hunks": [HUNK]})
        self.assertEqual(review["hunks"][0]["comments"], [])
        self.assertIn("APIConnectionError", review["hunks"][0]["error"])


class EnvFile(unittest.TestCase):
    def test_loads_without_overwriting(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text('PR_TEST_A=from_file\nPR_TEST_B="quoted"\n')
            os.environ["PR_TEST_A"] = "preset"
            load_env(env)
            self.assertEqual(os.environ["PR_TEST_A"], "preset")
            self.assertEqual(os.environ["PR_TEST_B"], "quoted")
            del os.environ["PR_TEST_A"], os.environ["PR_TEST_B"]


if __name__ == "__main__":
    unittest.main()
