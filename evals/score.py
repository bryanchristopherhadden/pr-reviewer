"""Turn labelled cases into hunks and score reviewer comments against them.

Nothing here calls an API, so the scoring rules can be unit-tested offline.
"""
from __future__ import annotations

import difflib
import textwrap

from watcher import parse_hunks

# A comment counts as a hit if it lands within this many lines of a labelled problem.
TOLERANCE = 1


def build_hunks(case: dict) -> list[dict]:
    """Make the same hunk structure watcher.py saves, from a before/after pair."""
    path = case["path"]
    before = textwrap.dedent(case["before"]).lstrip("\n")
    after = textwrap.dedent(case["after"]).lstrip("\n")
    body = "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    if not body:
        return []
    return parse_hunks(f"diff --git a/{path} b/{path}\n{body}")


def expected_lines(case: dict) -> list[int]:
    """Resolve each expected problem to a NEW-side line number, and check it is in the diff."""
    after_lines = textwrap.dedent(case["after"]).lstrip("\n").splitlines()
    in_diff = {
        line["new_line"]
        for hunk in build_hunks(case)
        for line in hunk["lines"]
        if line.get("new_line") is not None
    }
    resolved = []
    for item in case.get("expect", []):
        found = [i + 1 for i, text in enumerate(after_lines) if item["contains"] in text]
        if len(found) != 1:
            raise ValueError(f"{case['id']}: {item['contains']!r} matches {len(found)} lines, need 1")
        if found[0] not in in_diff:
            raise ValueError(f"{case['id']}: line {found[0]} is not part of the diff")
        resolved.append(found[0])
    return resolved


def match(predicted: list[int], expected: list[int], tolerance: int = TOLERANCE) -> dict:
    """Pair predictions with expected lines.

    Each expected line is matched once (tp). A further comment near an already-matched
    problem is a "dup": a second comment on a real issue, not a wrong one. Anything
    else is an fp. Expected lines with no comment are fn.
    """
    unmatched = list(expected)
    matched: list[int] = []
    tp = fp = dup = 0
    for line in sorted(predicted):
        hit = next((e for e in unmatched if abs(e - line) <= tolerance), None)
        if hit is not None:
            unmatched.remove(hit)
            matched.append(hit)
            tp += 1
        elif any(abs(e - line) <= tolerance for e in matched):
            dup += 1
        else:
            fp += 1
    return {"tp": tp, "fp": fp, "fn": len(unmatched), "dup": dup}


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def aggregate(case_results: list[dict]) -> dict:
    """Overall precision, recall and F1, plus the share of clean cases that drew any comment."""
    tp = sum(r["tp"] for r in case_results)
    fp = sum(r["fp"] for r in case_results)
    fn = sum(r["fn"] for r in case_results)
    dup = sum(r["dup"] for r in case_results)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 3) if precision and recall else None
    clean = [r for r in case_results if r["kind"] == "clean"]
    noisy_clean = [r for r in clean if r["fp"] + r["dup"] > 0]
    return {
        "cases": len(case_results),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "dup": dup,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "clean_cases": len(clean),
        "clean_cases_with_comments": len(noisy_clean),
        "errors": sum(r["errors"] for r in case_results),
    }
