#!/usr/bin/env python3
"""Review each hunk in data/changes/*.json with Claude and save comments locally.

Nothing is posted to GitHub. Output goes to data/reviews/<change file name>.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

MODEL = "claude-haiku-5-5"
HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data"
SEVERITIES = {"info", "suggestion", "warning", "bug"}

SYSTEM = """You review one hunk of a code diff. Report only concrete problems the \
diff introduces: bugs, security issues, broken error handling, or clear \
correctness risks. Do not comment on style, naming, or things you cannot see \
from the hunk.

Reply with only a JSON array, no prose. Each item must be an object with:
- "line": integer, a line number on the NEW side of the file (from the "new" \
numbers shown). Use the line the problem is on.
- "severity": one of "info", "suggestion", "warning", "bug".
- "comment": one or two sentences explaining the problem and a fix.

Reply with [] if the hunk has no real problems."""


def load_env(path: Path) -> None:
    """Load KEY=VALUE lines from .env into os.environ without overwriting."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def render_hunk(hunk: dict) -> str:
    """Show each line with its old and new line numbers so the model can cite lines."""
    rows = [f"File: {hunk['file']}", f"Enclosing: {hunk.get('enclosing') or '(none)'}", ""]
    for line in hunk["lines"]:
        kind = line["type"]
        marker = {"add": "+", "del": "-", "context": " "}[kind]
        old = line.get("old_line", "")
        new = line.get("new_line", "")
        rows.append(f"old={old!s:>5} new={new!s:>5} {marker}{line['text']}")
    return "\n".join(rows)


def parse_comments(text: str) -> list[dict]:
    """Parse the model's JSON array and drop anything that doesn't match the schema."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in reply: {text[:200]!r}")
    items = json.loads(text[start : end + 1])
    comments = []
    for item in items:
        if (
            isinstance(item, dict)
            and isinstance(item.get("line"), int)
            and item.get("severity") in SEVERITIES
            and isinstance(item.get("comment"), str)
            and item["comment"].strip()
        ):
            comments.append({
                "line": item["line"],
                "severity": item["severity"],
                "comment": item["comment"].strip(),
            })
    return comments


def review_hunk(client, hunk: dict) -> list[dict]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": render_hunk(hunk)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return parse_comments(text)


def review_change(client, change: dict) -> dict:
    results = []
    for index, hunk in enumerate(change["hunks"]):
        try:
            comments = review_hunk(client, hunk)
            error = None
        except (ValueError, json.JSONDecodeError, anthropic.APIError) as exc:
            comments, error = [], f"{type(exc).__name__}: {exc}"
        results.append({
            "hunk": index,
            "file": hunk["file"],
            "comments": comments,
            "error": error,
        })
    return {
        "source": {k: change[k] for k in ("repo", "branch", "new_sha") if k in change},
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "hunks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--force", action="store_true", help="re-review changes already reviewed")
    args = parser.parse_args()

    load_env(HERE / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (checked environment and .env)", file=sys.stderr)
        return 1

    client = anthropic.Anthropic()
    out_dir = args.data / "reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted((args.data / "changes").glob("*.json")):
        target = out_dir / path.name
        if target.exists() and not args.force:
            continue
        change = json.loads(path.read_text())
        review = review_change(client, change)
        target.write_text(json.dumps(review, indent=2))
        total = sum(len(h["comments"]) for h in review["hunks"])
        failed = sum(1 for h in review["hunks"] if h["error"])
        print(f"{path.name}: {len(review['hunks'])} hunks, {total} comments, {failed} errors -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
