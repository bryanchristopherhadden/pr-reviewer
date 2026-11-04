import unittest

from evals.cases import CASES
from evals.score import aggregate, build_hunks, expected_lines, match


class Labels(unittest.TestCase):
    def test_every_case_resolves_to_a_line_inside_the_diff(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                expected_lines(case)  # raises if a label is ambiguous or outside the diff

    def test_buggy_cases_have_labels_and_clean_cases_do_not(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                if case["kind"] == "buggy":
                    self.assertTrue(case["expect"])
                else:
                    self.assertEqual(case["expect"], [])

    def test_case_ids_are_unique(self):
        ids = [c["id"] for c in CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_clean_set_includes_safe_versions_of_buggy_cases(self):
        clean = [c["id"] for c in CASES if c["kind"] == "clean"]
        self.assertGreaterEqual(len(clean), 10)
        self.assertGreaterEqual(sum(c["kind"] == "buggy" for c in CASES), 10)


class BuildHunks(unittest.TestCase):
    def test_new_file_produces_one_hunk_with_added_lines(self):
        case = {"id": "x", "path": "n.py", "before": "", "after": "a = 1\nb = 2\n"}
        [hunk] = build_hunks(case)
        self.assertEqual(hunk["file"], "n.py")
        self.assertEqual([l["new_line"] for l in hunk["lines"]], [1, 2])

    def test_identical_files_produce_no_hunks(self):
        self.assertEqual(build_hunks({"id": "x", "path": "a.py", "before": "x\n", "after": "x\n"}), [])


class Match(unittest.TestCase):
    def test_exact_and_near_hits_count_once(self):
        self.assertEqual(match([5], [5]), {"tp": 1, "fp": 0, "fn": 0, "dup": 0})
        self.assertEqual(match([6], [5]), {"tp": 1, "fp": 0, "fn": 0, "dup": 0})

    def test_far_prediction_is_false_positive_and_miss_is_false_negative(self):
        self.assertEqual(match([9], [5]), {"tp": 0, "fp": 1, "fn": 1, "dup": 0})

    def test_second_comment_on_same_problem_is_a_dup_not_a_false_positive(self):
        self.assertEqual(match([4, 5], [5]), {"tp": 1, "fp": 0, "fn": 0, "dup": 1})

    def test_any_comment_on_clean_case_is_false_positive(self):
        self.assertEqual(match([3, 7], []), {"tp": 0, "fp": 2, "fn": 0, "dup": 0})


class Aggregate(unittest.TestCase):
    def test_precision_recall_and_clean_noise(self):
        results = [
            {"kind": "buggy", "tp": 1, "fp": 0, "fn": 1, "dup": 0, "errors": 0},
            {"kind": "buggy", "tp": 1, "fp": 1, "fn": 0, "dup": 2, "errors": 0},
            {"kind": "clean", "tp": 0, "fp": 0, "fn": 0, "dup": 0, "errors": 0},
            {"kind": "clean", "tp": 0, "fp": 2, "fn": 0, "dup": 0, "errors": 1},
        ]
        s = aggregate(results)
        self.assertEqual((s["tp"], s["fp"], s["fn"], s["dup"]), (2, 3, 1, 2))
        self.assertEqual(s["precision"], 0.4)
        self.assertEqual(s["recall"], 0.667)
        self.assertEqual(s["clean_cases_with_comments"], 1)
        self.assertEqual(s["errors"], 1)

    def test_no_predictions_gives_none_precision(self):
        s = aggregate([{"kind": "buggy", "tp": 0, "fp": 0, "fn": 2, "dup": 0, "errors": 0}])
        self.assertIsNone(s["precision"])
        self.assertEqual(s["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
