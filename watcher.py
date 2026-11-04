#!/usr/bin/env python3
"""Watch a local git repo and save the diff of each change, split into hunks.

Feature branches act as PRs (merge-base with the base branch -> branch tip).
New commits on the base branch are diffed against its previous tip. The watched
repo is only ever read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
DEFAULT_REPO = Path(__file__).resolve().parent.parent / "checkout-api"
DEFAULT_DATA = Path(__file__).resolve().parent / "data"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def diff(repo: Path, old: str, new: str) -> str:
    return git(
        repo, "diff", "--no-color", "--no-ext-diff", "--find-renames",
        "--src-prefix=a/", "--dst-prefix=b/", old, new,
    )


def _path(line: str, prefix: str) -> str | None:
    value = line[4:].rstrip("\n").rstrip("\t")
    if value == "/dev/null":
        return None
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    return value[len(prefix):] if value.startswith(prefix) else value


def parse_hunks(text: str) -> list[dict]:
    """Split unified diff text into hunks with old and new line numbers."""
    hunks: list[dict] = []
    old_path = new_path = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("diff --git "):
            old_path = new_path = None
        elif line.startswith("--- "):
            old_path = _path(line, "a/")
        elif line.startswith("+++ "):
            new_path = _path(line, "b/")
        else:
            match = HUNK_HEADER.match(line)
            if not match:
                continue
            old_start, old_count, new_start, new_count, context = match.groups()
            old_left = 1 if old_count is None else int(old_count)
            new_left = 1 if new_count is None else int(new_count)
            old_line, new_line = int(old_start), int(new_start)
            body: list[dict] = []
            # Count lines from the header, so removed content that looks like
            # "--- x" or "@@ ..." is never mistaken for diff structure.
            while i < len(lines) and (old_left > 0 or new_left > 0):
                raw = lines[i]
                i += 1
                kind = raw[:1]
                if kind == "\\":
                    continue
                if kind == "+":
                    body.append({"type": "add", "new_line": new_line, "text": raw[1:]})
                    new_line += 1
                    new_left -= 1
                elif kind == "-":
                    body.append({"type": "del", "old_line": old_line, "text": raw[1:]})
                    old_line += 1
                    old_left -= 1
                else:
                    body.append({
                        "type": "context", "old_line": old_line,
                        "new_line": new_line, "text": raw[1:],
                    })
                    old_line += 1
                    new_line += 1
                    old_left -= 1
                    new_left -= 1
            hunks.append({
                "file": new_path or old_path,
                "old_file": old_path,
                "new_file": new_path,
                "enclosing": context,
                "lines": body,
            })
    return hunks


def load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def write_json(path: Path, value: dict) -> None:
    """Replace the file atomically so a crash can't leave partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2)
    os.replace(tmp, path)


def scan(repo: Path, data: Path, base: str) -> list[Path]:
    """Save a change file for each new branch tip and return the files written."""
    state_path = data / "state.json"
    seen = load_state(state_path)
    first_run = not seen
    output = git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    tips = dict(line.rsplit(" ", 1) for line in output.splitlines())
    if base not in tips:
        raise RuntimeError(f"base branch {base!r} not found in {repo}")

    written: list[Path] = []
    next_seen: dict[str, str] = {}
    for branch, head in tips.items():
        previous = seen.get(branch)
        next_seen[branch] = head
        if previous == head:
            continue
        try:
            if branch == base:
                # The base tip at first sight is the starting point, not a change.
                if first_run or previous is None:
                    continue
                old = previous
            else:
                old = git(repo, "merge-base", tips[base], head).strip()
            hunks = parse_hunks(diff(repo, old, head))
        except RuntimeError as error:
            print(f"skipped {branch}: {error}", file=sys.stderr)
            # Forget this tip so the next scan tries it again.
            if previous is None:
                del next_seen[branch]
            else:
                next_seen[branch] = previous
            continue
        if not hunks:
            continue  # For example, a new branch still level with the base.
        safe_branch = re.sub(r"[^A-Za-z0-9._-]+", "_", branch)
        target = data / "changes" / f"{safe_branch}-{head[:12]}.json"
        write_json(target, {
            "repo": str(repo),
            "branch": branch,
            "base": base,
            "old_sha": old,
            "new_sha": head,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "hunks": hunks,
        })
        written.append(target)
    write_json(state_path, next_seen)
    return written


def gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def fetch_compare(slug: str, base: str, head: str) -> tuple[str, list[dict]]:
    """Return the merge-base and hunks for base...head, pinned to the head SHA."""
    endpoint = f"repos/{slug}/compare/{quote(base, safe='')}...{head}"
    merge_base = gh("api", endpoint, "--jq", ".merge_base_commit.sha").strip()
    text = gh("api", endpoint, "-H", "Accept: application/vnd.github.diff")
    return merge_base, parse_hunks(text)


def scan_github(slug: str, data: Path, base: str = "main") -> list[Path]:
    """Save a change file for each open PR into `base` whose head commit is new."""
    state_path = data / "github-state.json"
    seen = load_state(state_path)
    pulls = json.loads(gh(
        "pr", "list", "-R", slug, "--state", "open", "--limit", "100",
        "--json", "number,title,url,author,headRefName,headRefOid,baseRefName",
    ))
    written: list[Path] = []
    next_seen: dict[str, str] = {}  # Closed PRs drop out; reopening rechecks them.
    for pull in pulls:
        number, head = str(pull["number"]), pull["headRefOid"]
        if pull["baseRefName"] != base:
            continue
        next_seen[number] = head
        if seen.get(number) == head:
            continue
        try:
            merge_base, hunks = fetch_compare(slug, pull["baseRefName"], head)
        except RuntimeError as error:
            print(f"skipped PR #{number}: {error}", file=sys.stderr)
            # Keep the old tip, or none, so the next scan tries again.
            if number in seen:
                next_seen[number] = seen[number]
            else:
                del next_seen[number]
            continue
        if not hunks:
            continue
        target = data / "changes" / f"pr-{number}-{head[:12]}.json"
        write_json(target, {
            "repo": slug,
            "pr": pull["number"],
            "title": pull["title"],
            "url": pull["url"],
            "author": pull["author"]["login"],
            "branch": pull["headRefName"],
            "base": pull["baseRefName"],
            "old_sha": merge_base,
            "new_sha": head,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "hunks": hunks,
        })
        written.append(target)
    write_json(state_path, next_seen)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github", metavar="OWNER/REPO", help="watch open PRs instead of a local repo")
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--base", default="main")
    parser.add_argument("--interval", type=float, default=30, help="seconds between scans")
    parser.add_argument("--once", action="store_true", help="scan once and exit")
    args = parser.parse_args()

    if not args.once:
        target = args.github or f"{args.repo} (base: {args.base})"
        print(f"watching {target}, every {args.interval:g}s", flush=True)
    while True:
        try:
            paths = (
                scan_github(args.github, args.data) if args.github
                else scan(args.repo, args.data, args.base)
            )
            for path in paths:
                change = json.loads(path.read_text())
                print(
                    f"{change['branch']} @ {change['new_sha'][:7]}: "
                    f"{len(change['hunks'])} hunks -> {path}",
                    flush=True,
                )
        except RuntimeError as error:
            if args.once:
                print(error, file=sys.stderr)
                return 1
            print(error, file=sys.stderr, flush=True)
        if args.once:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
