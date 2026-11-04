# pr-reviewer

AI PR reviewer, in progress. So far it only has step 1: watch a repo and save each change's diff, split into hunks.

```sh
python3 watcher.py --github bryanchristopherhadden/checkout-api          # poll open PRs every 30 seconds
python3 watcher.py --github bryanchristopherhadden/checkout-api --once   # scan once
python3 -m unittest                                                      # run the tests
```

GitHub mode needs `gh` to be logged in. Each open PR with a new head commit creates `data/changes/pr-<number>-<sha>.json`. It posts nothing to GitHub.

PRs already open on the first scan are picked up too.

## Local mode

Leave out `--github` to watch local commits in `../checkout-api` instead. The first scan records a baseline. After that, branches are diffed from their merge-base with `main`, and commits on `main` against its previous tip. These files are named `<branch>-<sha>.json`.

Use `--repo`, `--base`, `--data` and `--interval` to change the defaults.
