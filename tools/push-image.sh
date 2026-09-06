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

# Credential, in order of preference:
#   1. $GHCR_TOKEN
#   2. ~/.config/ghcr-token   (chmod 600; a classic PAT with write:packages)
#   3. the gh token, if it happens to carry write:packages
# The gh route needs `gh auth refresh --hostname github.com -s write:packages,read:packages`,
# which is a device-code flow and wants a real terminal. A PAT avoids that entirely.
TOKEN_FILE="${GHCR_TOKEN_FILE:-$HOME/.config/ghcr-token}"
if [ -n "${GHCR_TOKEN:-}" ]; then
  TOKEN="$GHCR_TOKEN"; SOURCE="\$GHCR_TOKEN"
elif [ -r "$TOKEN_FILE" ]; then
  TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"; SOURCE="$TOKEN_FILE"
elif gh auth status 2>&1 | grep -q "write:packages"; then
  TOKEN="$(gh auth token)"; SOURCE="gh token"
else
  cat <<'MSG'
No credential with write:packages. Either:

  1. Create a classic PAT with the write:packages scope at
       https://github.com/settings/tokens/new?scopes=write:packages,read:packages
     then:
       install -m600 /dev/null ~/.config/ghcr-token
       printf '%s' '<the token>' > ~/.config/ghcr-token

  2. Or grant the scope to gh, in a real terminal:
       gh auth refresh --hostname github.com -s write:packages,read:packages

Then re-run: tools/push-image.sh
MSG
  exit 1
fi

echo "=== logging in to ghcr.io as ${OWNER} (credential: ${SOURCE}) ==="
printf '%s' "$TOKEN" | docker login ghcr.io -u "$OWNER" --password-stdin

echo "=== pushing ${REMOTE} ==="
docker tag "$LOCAL" "$REMOTE"
docker push "$REMOTE"

if [ "$PUBLIC" = "1" ]; then
  # Packages default to private, and visibility CANNOT be changed over the REST API --
  # GET /user/packages/container/<name> works, PATCH 404s; it is a web-UI-only setting.
  # Report the state and the link rather than pretending to have set it.
  vis="$(gh api "/user/packages/container/jellyfin-patched" --jq .visibility 2>/dev/null || echo unknown)"
  echo "  package visibility: ${vis}"
  if [ "$vis" != "public" ]; then
    echo "  to make it public (web UI only):"
    echo "    https://github.com/users/${OWNER}/packages/container/jellyfin-patched/settings"
  fi
fi

echo
echo "pushed: ${REMOTE}"
echo "recovery is now a pull:"
echo "    docker pull ${REMOTE} && docker tag ${REMOTE} ${LOCAL}"
