#!/usr/bin/env python3
"""Run the reviewer over the labelled cases and report precision and recall.

    python3 -m evals.run_eval              # one pass, calls the Anthropic API
    python3 -m evals.run_eval --repeat 3   # three passes, to see run-to-run variance

Results are written to evals/results/<timestamp>.json. Review the false positives
by hand: a line-level match shows that a comment landed near a labelled problem,
not that its explanation is correct.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import reviewer
from evals.cases import CASES
from evals.score import aggregate, build_hunks, expected_lines, match

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def run_case(client, case: dict) -> dict:
    expected = expected_lines(case)
    predicted: list[dict] = []
    errors = 0
    for hunk in build_hunks(case):
        try:
            predicted.extend(reviewer.review_hunk(client, hunk))
        except (ValueError, anthropic.APIError) as exc:
            errors += 1
            print(f"  {case['id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
    counts = match([c["line"] for c in predicted], expected)
    return {
        "id": case["id"],
        "kind": case["kind"],
        "expected_lines": expected,
        "predicted": predicted,
        "errors": errors,
        **counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=1, help="number of full passes")
    args = parser.parse_args()

    reviewer.load_env(reviewer.HERE / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (checked environment and .env)", file=sys.stderr)
        return 1

    client = anthropic.Anthropic()
    runs = []
    for n in range(1, args.repeat + 1):
        print(f"pass {n}/{args.repeat}", file=sys.stderr)
        case_results = [run_case(client, case) for case in CASES]
        runs.append({"cases": case_results, "summary": aggregate(case_results)})

    summaries = [r["summary"] for r in runs]
    spread = {
        key: {
            "mean": round(statistics.mean(s[key] for s in summaries), 3),
            "min": min(s[key] for s in summaries),
            "max": max(s[key] for s in summaries),
        }
        for key in ("precision", "recall", "f1")
        if all(s[key] is not None for s in summaries)
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{stamp}.json"
    out.write_text(json.dumps({
        "model": reviewer.MODEL,
        "run_at": stamp,
        "repeat": args.repeat,
        "spread": spread,
        "runs": runs,
    }, indent=2))

    last = runs[-1]
    print(f"\nModel {reviewer.MODEL}, {len(CASES)} cases, {args.repeat} pass(es)\n")
    print("| case | kind | expected | tp | fp | dup | fn | errors |")
    print("|---|---|---|---|---|---|---|---|")
    for r in last["cases"]:
        print(f"| {r['id']} | {r['kind']} | {len(r['expected_lines'])} | {r['tp']} | {r['fp']} | {r['dup']} | {r['fn']} | {r['errors']} |")
    s = last["summary"]
    print(f"\nLast pass: precision {s['precision']}, recall {s['recall']}, F1 {s['f1']}, "
          f"clean cases with comments {s['clean_cases_with_comments']}/{s['clean_cases']}, duplicates {s['dup']}")
    if spread:
        print("Across passes:", json.dumps(spread))
    print(f"Saved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
