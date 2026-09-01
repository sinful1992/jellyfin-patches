#!/usr/bin/env bash
# Build a patched Jellyfin image: upstream release tag + our patches.
#
# Deliberately does not touch the running container. It builds and tags an image;
# switching to it is a separate, explicit step.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/jellyfin-patches}"
STAGE=""
SRC_DIR="${SRC_DIR:-$HOME/src/jellyfin}"
BASE_TAG="${BASE_TAG:-v10.11.11}"
BASE_IMAGE="${BASE_IMAGE:-lscr.io/linuxserver/jellyfin:10.11.11ubu2604-ls43}"
OUT_IMAGE="${OUT_IMAGE:-jellyfin-patched:10.11.11}"
DOTNET="${DOTNET:-$HOME/.dotnet/dotnet}"

# The four assemblies our patches produce. Kept explicit: copying the whole build
# output over the image would replace files the base image intentionally differs on.
ASSEMBLIES=(
  Jellyfin.Api.dll
  Emby.Server.Implementations.dll
  Jellyfin.Server.Implementations.dll
  MediaBrowser.Controller.dll
)

say() { printf '\n=== %s ===\n' "$*"; }

say "preparing a pristine ${BASE_TAG} worktree"
# Build in a throwaway worktree rather than mutating $SRC_DIR: that clone may hold
# work in progress, and an earlier version of this script silently applied patches
# on top of an already-patched tree because checkout carries uncommitted changes.
cd "$SRC_DIR"
git fetch --tags --quiet origin || true
WORKTREE="$(mktemp -d -t jellyfin-build-XXXXXX)"
git worktree add --detach -q "$WORKTREE" "$BASE_TAG"
cleanup() {
  cd "$SRC_DIR" 2>/dev/null || true
  git worktree remove --force "$WORKTREE" 2>/dev/null || true
  rm -rf "$STAGE" 2>/dev/null || true
}
trap cleanup EXIT
cd "$WORKTREE"

say "applying patches"
for p in "$REPO_DIR"/patches/*.patch; do
  [ -e "$p" ] || continue
  echo "  applying $(basename "$p")"
  git apply --check "$p" || { echo "PATCH FAILED: $p"; echo "Upstream moved; rebase needed."; exit 1; }
  git apply "$p"
done

say "building (net9 required for 10.11.x)"
"$DOTNET" build Jellyfin.Server/Jellyfin.Server.csproj -c Release --nologo -v q

say "collecting patched assemblies"
STAGE="$(mktemp -d)"
mkdir -p "$STAGE/dll"
BIN="$WORKTREE/Jellyfin.Server/bin/Release/net9.0"
for a in "${ASSEMBLIES[@]}"; do
  [ -f "$BIN/$a" ] || { echo "missing build output: $a"; exit 1; }
  cp "$BIN/$a" "$STAGE/dll/"
  echo "  $a"
done
cp "$REPO_DIR/build/Dockerfile" "$STAGE/"

say "building image ${OUT_IMAGE}"
REV="$(cd "$REPO_DIR" && git rev-parse --short HEAD 2>/dev/null || echo local)"
docker build --build-arg "BASE_IMAGE=${BASE_IMAGE}" --build-arg "PATCH_REV=${REV}" \
  -t "$OUT_IMAGE" "$STAGE"

say "done"
echo "Built ${OUT_IMAGE} from ${BASE_TAG} + $(ls -1 "$REPO_DIR"/patches/*.patch 2>/dev/null | wc -l) patch(es)."
echo "It is NOT running yet. To switch, point the jellyfin service at ${OUT_IMAGE}."
echo "To roll back, point it back at ${BASE_IMAGE}."
