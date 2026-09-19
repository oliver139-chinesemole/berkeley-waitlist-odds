#!/usr/bin/env bash
# Create the orphan `data` branch that .github/workflows/scrape.yml appends snapshots to.
#
#   scripts/bootstrap_data_branch.sh [remote]      # default remote: origin
#
# Layout of the new branch (docs/DESIGN_A2.md section 2):
#   README.md, snapshots/.gitkeep, catalog/.gitkeep
#
# Idempotent: exits 0 without changes when `data` already exists on the remote.
# The branch is built in a temporary git worktree, so the current checkout and
# its branch are never touched. Refuses to run when tracked files have
# uncommitted changes.
set -euo pipefail

remote="${1:-origin}"
branch="data"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "error: working tree has uncommitted changes to tracked files; commit or stash them first" >&2
  exit 1
fi

original_ref="$(git symbolic-ref --short -q HEAD || git rev-parse HEAD)"

git fetch --quiet --prune "$remote"

if git ls-remote --exit-code --heads "$remote" "$branch" >/dev/null 2>&1; then
  echo "branch '$branch' already exists on $remote; nothing to do"
  exit 0
fi

if git show-ref --verify --quiet "refs/heads/$branch"; then
  echo "local branch '$branch' exists but is not on $remote; pushing it"
  git push -u "$remote" "$branch"
  exit 0
fi

worktree="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-data.XXXXXX")"
cleanup() {
  git worktree remove --force "$worktree" >/dev/null 2>&1 || true
  rm -rf "$worktree"
}
trap cleanup EXIT

echo "building orphan branch '$branch' in a temporary worktree"
git worktree add --quiet --detach "$worktree" HEAD
(
  cd "$worktree"
  git checkout --quiet --orphan "$branch"
  git rm -r -f -q --cached . >/dev/null
  find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  printf '%s\n' \
    "# data branch: append-only snapshots, see main/docs/DESIGN_A2.md" \
    "" \
    "Written only by .github/workflows/scrape.yml. Never commit here by hand." \
    "" \
    '- `snapshots/date=YYYY-MM-DD/HHMM-baseline.parquet` and `HHMM-delta.parquet`' \
    '- `catalog/<term_id>/sections.json` (classes_site section list, refreshed at most daily)' \
    '- `status.json` (last run summary)' \
    > README.md
  mkdir -p snapshots catalog
  : > snapshots/.gitkeep
  : > catalog/.gitkeep
  git add README.md snapshots/.gitkeep catalog/.gitkeep
  git -c user.name="${GIT_AUTHOR_NAME:-$(git config user.name || echo bootstrap)}" \
      -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo bootstrap@localhost)}" \
      commit --quiet -m "bootstrap data branch"
  git push -u "$remote" "$branch"
)

now_ref="$(git symbolic-ref --short -q HEAD || git rev-parse HEAD)"
echo "created and pushed '$branch' to $remote"
echo "current checkout: $now_ref (unchanged from $original_ref)"
