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


THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes { isResolved comments(first: 1) { nodes { author { login } } } }
      }
    }
  }
}
"""


def blocking_threads(slug: str, pr: int, bot_login: str) -> int:
    """Count unresolved review threads on the PR that the bot itself opened.

    Returns a large number if there are more than 100 threads, so the PR is held
    back rather than reviewed on partial data.
    """
    owner, name = slug.split("/", 1)
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={THREADS_QUERY}",
         "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={pr}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"reading threads on PR #{pr} failed: {result.stderr.strip()}")
    threads = json.loads(result.stdout)["data"]["repository"]["pullRequest"]["reviewThreads"]
    if threads["pageInfo"]["hasNextPage"]:
        return 10**6
    count = 0
    for thread in threads["nodes"]:
        if thread["isResolved"]:
            continue
        nodes = thread["comments"]["nodes"]
        opener = nodes[0]["author"]["login"] if nodes and nodes[0]["author"] else None
        if opener and same_account(opener, bot_login):
            count += 1
    return count


def same_account(a: str, b: str) -> bool:
    """GitHub reports bots as 'name[bot]' in REST and 'name' in GraphQL; treat them as one."""
    return a.removesuffix("[bot]") == b.removesuffix("[bot]")


def bot_login() -> str:
    """Login the reviews are posted as. Inside GitHub Actions the token has no /user, so use BOT_LOGIN."""
    if os.environ.get("BOT_LOGIN"):
        return os.environ["BOT_LOGIN"]
    if os.environ.get("GITHUB_ACTIONS"):
        return "github-actions[bot]"
    result = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"reading gh user failed: {result.stderr.strip()}")
    return result.stdout.strip()


def already_posted_on_github(slug: str, pr: int, sha: str, login: str) -> bool:
    """True if the bot already reviewed this head commit. Survives runner restarts."""
    result = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{slug}/pulls/{pr}/reviews"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"listing reviews on PR #{pr} failed: {result.stderr.strip()}")
    # --paginate prints one JSON array per page, possibly separated by whitespace; read them all.
    decoder, reviews, text, pos = json.JSONDecoder(), [], result.stdout, 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        page, pos = decoder.raw_decode(text, pos)
        reviews.extend(page)
    return any(
        r.get("commit_id") == sha and same_account(r["user"]["login"], login)
        for r in reviews
    )


def process(slug: str, data: Path) -> None:
    """Review and post every PR change file that hasn't been posted yet.

    A PR is skipped while the bot has an unresolved review thread on it. It is
    retried on later passes, so it's reviewed once those threads are resolved.
    """
    posted_path = data / "posted.json"
    posted = load_posted(posted_path)
    client = None
    login = None
    for path in sorted((data / "changes").glob("pr-*.json")):
        change = json.loads(path.read_text())
        key = f"pr-{change['pr']}-{change['new_sha']}"
        if key in posted:
            continue
        login = login or bot_login()
        if already_posted_on_github(slug, change["pr"], change["new_sha"], login):
            posted[key] = {"pr": change["pr"], "comments": None, "found_on_github": True}
            watcher.write_json(posted_path, posted)
            continue
        open_threads = blocking_threads(slug, change["pr"], login)
        if open_threads:
            print(f"holding PR #{change['pr']}: {open_threads} unresolved thread(s)", flush=True)
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
