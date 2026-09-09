#!/usr/bin/env bash
# Regenerate patches/ from the series branch.
#
# patches/ is BUILD OUTPUT. The source of truth is the commit series on
# $SERIES in $SRC_DIR. Never hand-edit a file in patches/ -- edit the commit
# (git rebase -i) and re-run this.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/jellyfin-patches}"
SRC_DIR="${SRC_DIR:-$HOME/src/jellyfin}"
BASE_TAG="${BASE_TAG:-v12.0}"
SERIES="${SERIES:-patched/12.0}"

cd "$SRC_DIR"
git rev-parse --verify --quiet "$SERIES" >/dev/null || { echo "no such branch: $SERIES"; exit 1; }
git merge-base --is-ancestor "$BASE_TAG" "$SERIES" \
  || { echo "$SERIES is not based on $BASE_TAG -- rebase it first"; exit 1; }

# A dirty series worktree means uncommitted work would silently not reach the
# patches. That is the failure the series model exists to prevent.
if [ -n "$(git status --porcelain)" ] && [ "$(git branch --show-current)" = "$SERIES" ]; then
  echo "$SRC_DIR has uncommitted changes on $SERIES -- commit or stash them first"; exit 1
fi

rm -f "$REPO_DIR"/patches/*.patch
git format-patch --quiet --no-signature --zero-commit --no-numbered \
  -o "$REPO_DIR/patches" "$BASE_TAG..$SERIES"

n=$(ls -1 "$REPO_DIR"/patches/*.patch 2>/dev/null | wc -l)
echo "regenerated $n patch(es) from $BASE_TAG..$SERIES"
ls -1 "$REPO_DIR"/patches/ | sed 's/^/  /'
