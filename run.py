#!/usr/bin/env python3
"""Watch a GitHub repo's open PRs, review each new head commit, and post the review.

Each PR head commit is reviewed and posted once. Results are recorded in
data/posted.json so a restart doesn't post duplicates.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic

import reviewer
import watcher

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data"


def comment_lines(change: dict) -> set[tuple[str, int]]:
    """(file, new line) pairs that appear in the diff, where inline comments can go."""
    pairs = set()
    for hunk in change["hunks"]:
        for line in hunk["lines"]:
            if "new_line" in line:
                pairs.add((hunk["file"], line["new_line"]))
    return pairs


def build_review(change: dict, review: dict) -> dict:
    """Turn stored review results into a GitHub review payload.

    Comments on lines inside the diff become inline comments. Anything else goes
    into the review body, because GitHub rejects inline comments on other lines.
    """
    valid = comment_lines(change)
    inline, body_lines = [], []
    total = 0
    for hunk in review["hunks"]:
        for c in hunk["comments"]:
            total += 1
            text = f"**{c['severity']}**: {c['comment']}"
            if (hunk["file"], c["line"]) in valid:
                inline.append({"path": hunk["file"], "line": c["line"], "side": "RIGHT", "body": text})
            else:
                body_lines.append(f"- `{hunk['file']}:{c['line']}` {text}")
    summary = (
        f"🤖 **Bryan's Robot** (`{review['model']}`) reviewed {len(review['hunks'])} hunks "
        f"and found {total} thing(s) to look at ✨"
    )
    failed = [h for h in review["hunks"] if h["error"]]
    if failed:
        summary += f"\n\n⚠️ {len(failed)} hunk(s) got stuck and weren't reviewed."
    if body_lines:
        summary += "\n\nComments on lines outside the diff:\n" + "\n".join(body_lines)
    return {
        "commit_id": change["new_sha"],
        "event": "COMMENT",
        "body": summary,
        "comments": inline,
    }


def post_review(slug: str, pr: int, payload: dict) -> None:
    result = subprocess.run(
        ["gh", "api", f"repos/{slug}/pulls/{pr}/reviews", "--input", "-"],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"posting review to PR #{pr} failed: {result.stderr.strip()}")


def load_posted(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def process(slug: str, data: Path) -> None:
    """Review and post every PR change file that hasn't been posted yet."""
    posted_path = data / "posted.json"
    posted = load_posted(posted_path)
    client = None
    for path in sorted((data / "changes").glob("pr-*.json")):
        change = json.loads(path.read_text())
        key = f"pr-{change['pr']}-{change['new_sha']}"
        if key in posted:
            continue
        review_path = data / "reviews" / path.name
        if review_path.exists():
            review = json.loads(review_path.read_text())
        else:
            client = client or anthropic.Anthropic()
            review = reviewer.review_change(client, change)
            review_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.write_text(json.dumps(review, indent=2))
        payload = build_review(change, review)
        post_review(slug, change["pr"], payload)
        posted[key] = {"pr": change["pr"], "comments": len(payload["comments"])}
        watcher.write_json(posted_path, posted)
        print(f"posted review on PR #{change['pr']} @ {change['new_sha'][:7]}: "
              f"{len(payload['comments'])} inline comment(s)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github", required=True, metavar="OWNER/REPO")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--interval", type=float, default=30, help="seconds between checks")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    reviewer.load_env(HERE / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (checked environment and .env)", file=sys.stderr)
        return 1

    while True:
        try:
            watcher.scan_github(args.github, args.data)
            process(args.github, args.data)
        except (RuntimeError, anthropic.APIError, json.JSONDecodeError) as error:
            print(f"error: {error}", file=sys.stderr, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
