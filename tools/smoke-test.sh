#!/usr/bin/env bash
# Prove the auth patch is live IN THE SHIPPED BINARY, not merely in the source.
#
# This is the check the whole build leans on: the fork is run regardless of what
# upstream does, so nothing outside this repo will ever catch a dropped hunk. A
# green compile says the source was patched; only this says the image was.
#
# No media and no real config are needed. Authorization runs before the item
# lookup, so a nonexistent item id is enough to tell the two worlds apart:
#
#   patched   -> 401/403  (policy rejects before the lookup)
#   unpatched -> 404/500  (no policy; lookup runs and fails)
#
# Two traps found the hard way, both of which made patched and stock images fail
# IDENTICALLY -- a smoke test that cannot tell them apart is worse than none:
#   1. A fresh server answers 503 to every real endpoint until the startup wizard
#      is completed, so the wizard has to be driven first.
#   2. /System/Info/Public answers 200 while migrations are still running, so it
#      is not a readiness signal. Wait for the wizard endpoint itself.
#
# Runs a throwaway container on a loopback port with an empty config dir. It never
# touches the live jellyfin container or /mnt/data/docker-data/jellyfin.
set -euo pipefail

IMAGE="${1:-${OUT_IMAGE:-jellyfin-patched:10.11.11}}"
PORT="${SMOKE_PORT:-18096}"
DEADLINE="${SMOKE_DEADLINE:-180}"
FAKE_ID="00000000000000000000000000000000"

CONFIG="$(mktemp -d -t jf-smoke-XXXXXX)"
NAME="jf-smoke-$$"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$CONFIG" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== smoke test: $IMAGE ==="
docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:8096" \
  -e PUID=1000 -e PGID=1000 -e TZ=Europe/London \
  -v "$CONFIG:/config" "$IMAGE" >/dev/null

base="http://127.0.0.1:${PORT}"

code_of() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$@" || echo 000; }

wait_for() {  # wait_for <path> <expected-code> <label>
  local path="$1" want="$2" label="$3" i
  echo -n "  waiting for $label"
  for ((i = 0; i < DEADLINE; i++)); do
    if [ "$(code_of "$base$path")" = "$want" ]; then echo " ok"; return 0; fi
    echo -n "."
    command sleep 1
  done
  echo; echo "FAIL: $label never returned $want within ${DEADLINE}s"
  docker logs "$NAME" 2>&1 | tail -20
  return 1
}

wait_for /System/Info/Public 200 "server to listen"
wait_for /Startup/Configuration 200 "startup wizard to come up"

echo -n "  completing startup wizard"
wiz() {  # wiz <path> [json]
  local path="$1" data="${2:-}" code
  if [ -n "$data" ]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST \
      -H 'Content-Type: application/json' -d "$data" "$base$path" || echo 000)"
  else
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST "$base$path" || echo 000)"
  fi
  case "$code" in
    200|204) echo -n "." ;;
    *) echo; echo "FAIL: wizard step $path returned $code"; docker logs "$NAME" 2>&1 | tail -20; exit 1 ;;
  esac
}
wiz /Startup/Configuration '{"UICulture":"en-US","MetadataCountryCode":"GB","PreferredMetadataLanguage":"en"}'
# GET /Startup/User is not a read: it runs IUserManager.InitializeAsync and creates
# the first user. POST /Startup/User returns 404 until it has, so the order matters.
[ "$(code_of "$base/Startup/User")" = "200" ] || { echo; echo "FAIL: GET /Startup/User did not initialise the first user"; exit 1; }
echo -n "."
wiz /Startup/User '{"Name":"smoke","Password":"smoke-test-throwaway"}'
wiz /Startup/RemoteAccess '{"EnableRemoteAccess":true,"EnableAutomaticPortMapping":false}'
wiz /Startup/Complete
echo " done"

fail=0
check() {  # check <label> <path>
  local label="$1" path="$2" code
  code="$(code_of "$base$path")"
  case "$code" in
    401|403) echo "  PASS  $label -> $code (rejected before item lookup)" ;;
    503)     echo "  FAIL  $label -> 503 (server not configured; wizard step regressed)"; fail=1 ;;
    *)       echo "  FAIL  $label -> $code (expected 401/403; patch is NOT live in this image)"; fail=1 ;;
  esac
}

check "unauthenticated video stream" "/Videos/$FAKE_ID/stream"
check "unauthenticated audio stream" "/Audio/$FAKE_ID/stream?static=true"
check "unauthenticated hls segment"  "/Videos/$FAKE_ID/hls/main/0.ts"

if [ "$fail" != "0" ]; then
  echo "SMOKE TEST FAILED for $IMAGE"
  exit 1
fi
echo "  all checks passed -- the auth patch is live in $IMAGE"
