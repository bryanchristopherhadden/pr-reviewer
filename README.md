# PR Reviewer

PR Reviewer is an in-progress Python tool for monitoring code changes, asking an AI model to look for concrete problems, and optionally publishing review comments to GitHub pull requests.

The project is intentionally focused on the review loop: detect a new change, split its diff into reviewable hunks, request findings about correctness and security risks, and save or publish the results. It is a prototype, not a hosted service or a replacement for human review.

## Why I built this

Code review is essential, but it can be easy to miss a subtle bug in a busy diff. I built this to explore how AI can provide a useful first pass: focus on the changed code, surface specific risks, and put actionable comments where engineers already work—in the pull request. The fun part is connecting the whole loop, from tracking new commits and mapping diff line numbers to producing structured findings and GitHub reviews, while keeping a human in the loop.

## What it does

- **Watches local Git branches** and records new branch changes relative to their merge base with a base branch. New commits on the base branch are compared with the previous base tip.
- **Watches open GitHub pull requests** and records each newly observed PR head commit.
- **Parses unified diffs into hunks**, retaining file paths and old/new line numbers for review comments.
- **Reviews hunks with Claude** for concrete bugs, security issues, error-handling problems, and correctness risks. Results are saved as JSON.
- **Can publish a GitHub pull request review**, placing comments inline when the referenced line is in the diff and putting other findings in the review summary.

The reviewer sends diff hunks to the configured Anthropic API. Treat the diffs accordingly and only use it with code you are authorized to share.

## Requirements

- Python 3.10 or later
- Git
- The GitHub CLI (`gh`) for GitHub PR workflows
- An Anthropic API key for AI reviews

Install the Python dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Set `ANTHROPIC_API_KEY` in your environment or in a `.env` file in the project directory. The `.env` file is read by the review commands and should not be committed.

For GitHub workflows, authenticate the GitHub CLI with access to the repository. Publishing reviews also requires permission to submit pull request reviews.

## Usage

### Watch local changes

By default, the watcher looks for a sibling repository at `../checkout-api`, uses `main` as the base branch, and writes state and change files under `data/`.

```sh
python3 watcher.py --once
python3 watcher.py --repo ../your-repo --base main
```

The first local scan records a baseline. Later scans save each new branch-tip diff as a JSON file in `data/changes/`. Local watching only collects changes; it does not post to GitHub.

To review the collected changes with Claude and save the results under `data/reviews/`:

```sh
python3 reviewer.py
```

Use `--force` to review changes that already have a saved review.

### Watch GitHub pull requests

To collect changes for open pull requests without running an AI review:

```sh
python3 watcher.py --github OWNER/REPO --once
```

To continuously scan, review each newly observed PR head, and post a GitHub review:

```sh
python3 run.py --github OWNER/REPO --once
python3 run.py --github OWNER/REPO --interval 30
```

`run.py` requires both a working `gh` login and `ANTHROPIC_API_KEY`. Each PR head commit is posted once; posting state is saved in `data/posted.json`. A review is submitted as a GitHub `COMMENT` review, not as an approval or request for changes.

Both watcher commands support `--data PATH` to change the output directory. `watcher.py` also supports `--interval SECONDS`, `--repo PATH`, and `--base BRANCH`.

## How it is organized

- `watcher.py` scans local Git repositories or GitHub PRs, parses diffs, and persists detected changes.
- `reviewer.py` sends saved hunks to Claude and persists structured review results.
- `run.py` connects GitHub scanning, AI review, and review submission.
- `test_watcher.py`, `test_reviewer.py`, and `test_run.py` cover diff scanning, review parsing, and GitHub review payload construction.

Generated state, changes, and reviews are stored under `data/` and are excluded from Git.

## Development

Run the test suite with:

```sh
python3 -m unittest
```

## Project status

This is an actively developed prototype. It currently handles the detection-to-review flow described above; findings still need human judgment, and the project does not claim that every issue will be detected. Automated tests use mocked API responses and local temporary Git repositories, so running the suite does not require GitHub or Anthropic credentials.
