#!/usr/bin/env python3
"""MCP server exposing the PR reviewer as tools.

Run over stdio so an MCP client (such as Claude Code) can start it:

    .venv/bin/python mcp_server.py

Tools scan repos or PRs for changes, review saved changes with Claude, read the
results, and post reviews to GitHub. Posting is the only tool that changes
anything outside data/, and it only runs when explicitly called.

Nothing here writes to stdout: over stdio, stdout is the protocol channel.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic
from mcp.server.mcpserver import MCPServer

import reviewer
import run
import watcher

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PR_REVIEWER_DATA", HERE / "data"))

mcp = MCPServer(
    name="pr-reviewer",
    instructions=(
        "Scan local branches or GitHub PRs for changes, review them with Claude, "
        "read the findings, and optionally post them to a GitHub PR as a COMMENT review."
    ),
)

reviewer.load_env(HERE / ".env")


def _change_path(change_file: str) -> Path:
    """Resolve a change file name inside data/changes, refusing any path tricks."""
    if Path(change_file).name != change_file or not change_file.endswith(".json"):
        raise ValueError(f"change_file must be a bare file name like pr-12-<sha>.json: {change_file!r}")
    path = DATA / "changes" / change_file
    if not path.exists():
        raise FileNotFoundError(f"no change file named {change_file!r}; call list_changes")
    return path


DEFAULT_REPO = os.environ.get("PR_REVIEWER_REPO", "")


@mcp.tool()
def scan_github(slug: str = DEFAULT_REPO) -> list[str]:
    """Scan open PRs of a GitHub repo (OWNER/REPO) and save any new PR head diffs.

    Defaults to the PR_REVIEWER_REPO setting. Requires an authenticated `gh` CLI.
    Returns the change file names written.
    """
    if not slug:
        raise ValueError("no repo given and PR_REVIEWER_REPO is not set")
    written = watcher.scan_github(slug, DATA)
    return [p.name for p in written]


@mcp.tool()
def scan_local(repo: str, base: str = "main") -> list[str]:
    """Scan a local git repo's branches against a base branch and save new diffs.

    The repo is only read. Returns the change file names written.
    """
    written = watcher.scan(Path(repo).expanduser().resolve(), DATA, base)
    return [p.name for p in written]


@mcp.tool()
def list_changes() -> list[str]:
    """List saved change files, newest names last."""
    return sorted(p.name for p in (DATA / "changes").glob("*.json"))


@mcp.tool()
def review_change(change_file: str, force: bool = False) -> dict:
    """Review a saved change with Claude and save the findings under data/reviews/.

    Returns a summary with hunk, comment, and error counts. Use get_review for the
    full findings. An existing review is reused unless force is true.
    """
    path = _change_path(change_file)
    target = DATA / "reviews" / path.name
    if target.exists() and not force:
        review = json.loads(target.read_text())
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set (checked environment and .env)")
        change = json.loads(path.read_text())
        review = reviewer.review_change(anthropic.Anthropic(), change)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(review, indent=2))
    return {
        "change_file": change_file,
        "hunks": len(review["hunks"]),
        "comments": sum(len(h["comments"]) for h in review["hunks"]),
        "errors": sum(1 for h in review["hunks"] if h["error"]),
    }


@mcp.tool()
def get_review(change_file: str) -> dict:
    """Return the saved review for a change file, with every finding."""
    target = DATA / "reviews" / _change_path(change_file).name
    if not target.exists():
        raise FileNotFoundError(f"no review for {change_file!r}; call review_change first")
    return json.loads(target.read_text())


@mcp.tool()
def post_review(change_file: str) -> dict:
    """Post a saved PR review to GitHub as a COMMENT review.

    This publishes to the pull request. Only call it when the user has asked for
    the review to be posted. A PR head that was already posted is not posted again.
    """
    path = _change_path(change_file)
    change = json.loads(path.read_text())
    if "pr" not in change:
        raise ValueError(f"{change_file!r} is a local branch change, not a PR; only PRs can be posted")
    key = f"pr-{change['pr']}-{change['new_sha']}"
    posted_path = DATA / "posted.json"
    posted = run.load_posted(posted_path)
    if key in posted:
        return {"status": "already_posted", "key": key}

    review_path = DATA / "reviews" / path.name
    if not review_path.exists():
        raise FileNotFoundError(f"no review for {change_file!r}; call review_change first")
    review = json.loads(review_path.read_text())
    payload = run.build_review(change, review)
    slug = review["source"].get("repo") or change.get("repo")
    if not slug:
        raise ValueError("change file has no repo slug; cannot tell where to post")
    run.post_review(slug, change["pr"], payload)
    posted[key] = {"pr": change["pr"], "comments": len(payload["comments"])}
    watcher.write_json(posted_path, posted)
    return {"status": "posted", "pr": change["pr"], "inline_comments": len(payload["comments"])}


if __name__ == "__main__":
    mcp.run()
