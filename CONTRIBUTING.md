# Contributing: PR workflow and merge guardrails

## The loop
```bash
git checkout main && git pull --rebase origin main
git checkout -b a/probe-bakeoff            # <role>/<topic>, where role is a, b or c
# ... work only inside your lane (see CLAUDE.md rule 2) ...
python3 scripts/guard_repo.py              # secrets, test-set access, sizes, contracts
python3 scripts/verify_data.py             # leakage audit (must print 0 failure(s))
git add <specific files>                   # never `git add -A` blindly; check `git status` first
git diff --cached | grep -inE 'sk-ant-|api[_-]?key *=|secret *=|Bearer [A-Za-z0-9]' || echo "no secrets"
git commit -m "a: linear-probe bake-off on 3 backbones"
git push -u origin a/probe-bakeoff
gh pr create --fill                          # then fill in the template
```

## What every PR must have (the template asks for each)
1. **What and why** in two lines, plus which gate (G1–G5) it serves.
2. **Lane:** which directory it touches. If it touches a shared file, label it `shared` and tag both teammates.
3. **Evidence:** the exact commands run and their output (trimmed), and a screenshot or curl transcript for anything user-facing. "It works" alone isn't evidence.
4. **Numbers** cite the `reports/*.json` file they come from.
5. **Test-set statement:** "This PR does not read test data", or the TEST_LEDGER line it adds.

## Merge guardrails
| Rule | Why |
|---|---|
| **No direct pushes to `main`.** Everything goes through a PR. | One bad push breaks all three sessions at once. |
| **1 approval from someone other than the author.** 2 for `shared`-labelled PRs. | A second set of eyes, and contract changes affect everyone. |
| **CI must be green** (`guards` job: data audit, guardrails, contract tests, syntax; plus `app` build if present). | Machines catch secrets, leakage and broken schemas faster than tired humans. |
| **Squash merge only.** Delete the branch after merging. | `main` history stays one-PR-per-commit, so reverts are clean. |
| **Merge windows:** merges happen in the 15 minutes before each gate, unless a fix unblocks someone. | A quiet `main` between gates means fewer surprise conflicts. |
| **After feature freeze (G4, 04:30):** bug fixes only, each with a one-line risk note. | Late features are how demos break. |
| **If `main` breaks:** revert the offending PR first, then debug. | Restore a working demo before anything else. |
| **Never:** force-push, rewrite `main` history, enable auto-merge, or merge with failing CI "just this once". | |

## Branch protection (repo admin: Dhruv)
Only the repo owner can turn these on. Nirvaan has write access, not admin. In GitHub → Settings → Branches → Add branch ruleset for `main`:
- Require a pull request before merging (1 approval, dismiss stale approvals on new commits)
- Require status checks to pass: `guards`
- Block force pushes. Restrict deletions.
- Require linear history (squash only)

Or run this once as the admin:
```bash
gh api -X PUT repos/dhruvsood12/CalHacks/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["guards"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 1, "dismiss_stale_reviews": true},
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```
Also turn on Settings → General → "Allow squash merging" only, and "Automatically delete head branches".

## Sharing things that don't belong in git
| Thing | How |
|---|---|
| Images (5.1 GB) | Nirvaan has the full set. Others run `python3 scripts/fetch_images.py --ids <csv>` or `--split val --per-class 20`. |
| Model weights | A copies `artifacts/<model_version>/` to the serving box (scp) and posts the path in the PR. |
| API keys | Each person uses their own key in their local `.env`. Never share keys in chat. |
| Public URLs (API tunnel, app) | Pinned message in the team chat. Update it if a URL changes. |
