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

# ASSEMBLIES is DERIVED from what the patch set actually touches -- see "deriving the
# assemblies to replace" below. It used to be a hand-maintained list of four, which is
# a silent-failure hole: a patch touching a project outside the list builds green and
# ships an image missing that half of the fix. Patched source, unpatched binary, exit 0.
ASSEMBLIES=()

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
  rm -f "${BASE_DEPS:-}" 2>/dev/null || true
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

# The image is a CLOSED BINDING GRAPH: we replace 4 DLLs, the other ~405 stay and
# bind our assemblies by exact AssemblyVersion. So every version we emit must match
# what the base image already ships, or the runtime throws FileNotFoundException at
# startup (this bit us 2026-09-01: Jellyfin.Api built as 1.0.0.0 vs 26.4.0.0 shipped).
#
# Jellyfin.Api is the ONLY project that does not compile ../SharedVersion.cs, so it
# has no [assembly: AssemblyVersion] and MSBuild defaults it to 1.0.0.0. Every project
# that DOES include SharedVersion.cs sets GenerateAssemblyInfo=false, which makes them
# ignore -p:AssemblyVersion entirely -- so the property below lands on Jellyfin.Api
# (and any other generate-assembly-info project) and cannot disturb the rest.
say "reading required assembly versions from ${BASE_IMAGE}"
BASE_DEPS="$(mktemp)"
docker run --rm --entrypoint cat "$BASE_IMAGE" /usr/lib/jellyfin/bin/jellyfin.deps.json > "$BASE_DEPS"

dep_ver() {  # dep_ver <deps.json> <Assembly.dll> -> assemblyVersion
  python3 - "$1" "$2" <<'PY'
import json, sys
deps = json.load(open(sys.argv[1])); want = sys.argv[2]
for tgt in deps.get("targets", {}).values():
    for info in tgt.values():
        for f, meta in (info.get("runtime") or {}).items():
            if f.split("/")[-1] == want:
                v = (meta or {}).get("assemblyVersion")
                if v:
                    print(v); sys.exit(0)
sys.exit(1)
PY
}

API_VER="$(dep_ver "$BASE_DEPS" Jellyfin.Api.dll)" \
  || { echo "could not read Jellyfin.Api version from the base image"; exit 1; }
echo "  base image ships Jellyfin.Api at ${API_VER}"

say "deriving the assemblies to replace from the patch set"
# Every non-test file a patch touches must land in an assembly we actually ship.
# The mapping is the first path segment (the project directory) -> <project>.dll, and
# every result must exist in the base image's dependency graph. Anything that does not
# map is a hard failure: it means the build would quietly drop that change.
DERIVED="$(
  python3 - "$BASE_DEPS" "$REPO_DIR"/patches/*.patch <<'DERIVE'
import json, re, sys

deps_path, patches = sys.argv[1], sys.argv[2:]

shipped = set()
deps = json.load(open(deps_path))
for tgt in deps.get("targets", {}).values():
    for info in tgt.values():
        for f in (info.get("runtime") or {}):
            shipped.add(f.split("/")[-1])

touched = set()
for path in patches:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"^(?:\+\+\+ b/|--- a/)(.+?)\s*$", line)
            if m and m.group(1) != "/dev/null":
                touched.add(m.group(1))

projects, unmapped = set(), []
for f in sorted(touched):
    # Tests are compiled but never shipped into the image, so they map to nothing.
    if f.startswith("tests/"):
        continue
    proj = f.split("/")[0]
    dll = proj + ".dll"
    if dll in shipped:
        projects.add(dll)
    else:
        unmapped.append(f + " -> " + dll + " (not in the base image)")

if unmapped:
    print("UNMAPPED -- these patched files map to no shippable assembly:", file=sys.stderr)
    for u in unmapped:
        print("  " + u, file=sys.stderr)
    sys.exit(1)

print("\n".join(sorted(projects)))
DERIVE
)" || { echo "ABORTING: a patched file maps to no shippable assembly (see above)."; exit 1; }

mapfile -t ASSEMBLIES <<< "$DERIVED"
[ "${#ASSEMBLIES[@]}" -gt 0 ] || { echo "no assemblies derived from the patch set"; exit 1; }
for a in "${ASSEMBLIES[@]}"; do echo "  will replace $a"; done

say "building (net9 required for 10.11.x)"
"$DOTNET" build Jellyfin.Server/Jellyfin.Server.csproj -c Release --nologo -v q \
  -p:AssemblyVersion="$API_VER" -p:FileVersion="$API_VER"

# Gate: compare EVERY assembly common to both graphs, not just the 4 we replace --
# a version drift in something a replaced DLL references breaks binding just as hard.
say "verifying assembly versions against the base image"
OUR_DEPS="$WORKTREE/Jellyfin.Server/bin/Release/net9.0/jellyfin.deps.json"
[ -f "$OUR_DEPS" ] || { echo "no deps.json at $OUR_DEPS"; exit 1; }
python3 - "$BASE_DEPS" "$OUR_DEPS" <<'PY' || { echo; echo "ABORTING: fix the versions before building an image."; exit 1; }
import json, sys

def versions(path):
    out = {}
    deps = json.load(open(path))
    for tgt in deps.get("targets", {}).values():
        for info in tgt.values():
            for f, meta in (info.get("runtime") or {}).items():
                v = (meta or {}).get("assemblyVersion")
                if v:
                    out.setdefault(f.split("/")[-1], v)
    return out

base, ours = versions(sys.argv[1]), versions(sys.argv[2])
common = sorted(set(base) & set(ours))
bad = [(n, base[n], ours[n]) for n in common if base[n] != ours[n]]
print(f"  compared {len(common)} assemblies present in both")
if bad:
    print(f"  MISMATCH on {len(bad)}:")
    for n, b, o in bad:
        print(f"    {n:<44} base={b:<14} ours={o}")
    sys.exit(1)
print("  all match")
PY

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

# A green compile proves the SOURCE was patched. Only this proves the IMAGE was --
# and since this fork is run regardless of upstream, nothing else ever will.
say "smoke-testing ${OUT_IMAGE}"
"$REPO_DIR/tools/smoke-test.sh" "$OUT_IMAGE" \
  || { echo "ABORTING: the built image does not enforce the auth patch."; exit 1; }

say "done"
echo "Built ${OUT_IMAGE} from ${BASE_TAG} + $(ls -1 "$REPO_DIR"/patches/*.patch 2>/dev/null | wc -l) patch(es),"
echo "replacing: ${ASSEMBLIES[*]}"
echo "Smoke test passed: unauthenticated media endpoints are rejected."
echo "It is NOT running yet. To switch, point the jellyfin service at ${OUT_IMAGE}."
echo "To roll back, point it back at ${BASE_IMAGE}."
