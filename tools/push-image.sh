#!/usr/bin/env bash
# Publish the built image to GHCR.
#
# Why this exists: jellyfin-patched is built locally and, until now, existed in no
# registry at all. A `docker image prune -a` or a stray compose pull removed the only
# copy, leaving rebuild-from-source as the sole recovery path -- on a box where the
# build needs the .NET 9 SDK and ~3 minutes. A registry copy makes recovery a pull.
#
# Needs `write:packages` on the gh token:
#     gh auth refresh -s write:packages,read:packages
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/jellyfin-patches}"
VERSION="${1:-$(cat "$REPO_DIR/VERSION")}"
OWNER="${GHCR_OWNER:-sinful1992}"          # GHCR requires lowercase
LOCAL="jellyfin-patched:${VERSION}"
REMOTE="ghcr.io/${OWNER}/jellyfin-patched:${VERSION}"
PUBLIC="${GHCR_PUBLIC:-1}"

docker image inspect "$LOCAL" >/dev/null 2>&1 \
  || { echo "no local image $LOCAL -- build it first (build/build.sh)"; exit 1; }

if ! gh auth status 2>&1 | grep -q "write:packages"; then
  echo "gh token lacks write:packages. Run this, then re-run me:"
  echo "    gh auth refresh -s write:packages,read:packages"
  exit 1
fi

echo "=== logging in to ghcr.io as ${OWNER} ==="
gh auth token | docker login ghcr.io -u "$OWNER" --password-stdin

echo "=== pushing ${REMOTE} ==="
docker tag "$LOCAL" "$REMOTE"
docker push "$REMOTE"

if [ "$PUBLIC" = "1" ]; then
  # Packages default to private; public matches the repo, which already carries the
  # patches in full. Non-fatal: a failure here costs visibility, not the push.
  gh api --method PATCH "/user/packages/container/jellyfin-patched" \
    -f visibility=public >/dev/null 2>&1 \
    && echo "  package visibility: public" \
    || echo "  (could not set visibility -- set it in the package settings if you want it public)"
fi

echo
echo "pushed: ${REMOTE}"
echo "recovery is now a pull:"
echo "    docker pull ${REMOTE} && docker tag ${REMOTE} ${LOCAL}"
