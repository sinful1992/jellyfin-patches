#!/usr/bin/env python3
"""Watch upstream Jellyfin for anything that affects our local patch set.

Reports to Discord and never changes anything: adopting a change is always a
human decision. Uses the anonymous GitHub API on purpose -- this account is
blocked by the jellyfin org, and an unauthenticated read is unaffected by that
and needs no token to leak into a public repo.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT = "Bloodhound"
PINNED = "10.11.11"                       # the server release we build from
STATE = Path(os.environ.get("JF_WATCH_STATE", Path.home() / ".local/state/jellyfin-watch/state.json"))
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Files our patches touch. An upstream commit here means a rebase may conflict,
# or that upstream fixed it themselves and we can drop a patch.
WATCHED_PATHS = [
    "Jellyfin.Api/Controllers/AudioController.cs",
    "Jellyfin.Api/Controllers/VideosController.cs",
    "Jellyfin.Api/Controllers/VideoAttachmentsController.cs",
    "Jellyfin.Api/Controllers/SubtitleController.cs",
    "Jellyfin.Api/Controllers/HlsSegmentController.cs",
    "Emby.Server.Implementations/Library/UserDataManager.cs",
    "Emby.Server.Implementations/Dto/DtoService.cs",
    "MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs",
]

# Issues our patches correspond to. Closed upstream => our patch may be redundant.
WATCHED_ISSUES = {
    13983: "GetAttachment unauthenticated",
    13984: "Video streams unauthenticated",
    13985: "Subtitle endpoints unauthenticated",
    13986: "Audio endpoints unauthenticated",
    14981: "Favorites lost during playback",
    2547:  "Subtitles out of sync when resuming",
}

# A browser UA is required: Discord 403s urllib's default, and GitHub throttles it.
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def post(content):
    if not WEBHOOK:
        print("DISCORD_WEBHOOK_URL not set; would have posted:\n" + content, file=sys.stderr)
        return
    body = json.dumps({"username": BOT, "content": content}).encode()
    req = urllib.request.Request(
        WEBHOOK, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=30).read()


def check_release(state, findings):
    rel = get("https://api.github.com/repos/jellyfin/jellyfin/releases/latest")
    tag = rel["tag_name"].lstrip("v")
    if tag != state.get("last_release") and tag != PINNED:
        findings.append(
            f"**Jellyfin {tag} released** (we build from {PINNED})\n"
            f"Rebasing means bumping Intro Skipper to match, they move together.\n{rel['html_url']}")
    state["last_release"] = tag


def check_paths(state, findings):
    since = state.get("last_commit_scan") or (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    seen = state.setdefault("seen_commits", [])
    for path in WATCHED_PATHS:
        try:
            commits = get(
                "https://api.github.com/repos/jellyfin/jellyfin/commits"
                f"?path={urllib.parse.quote(path)}&since={since}&per_page=10")
        except urllib.error.HTTPError as e:
            findings.append(f"could not scan `{path}` ({e.code})")
            continue
        for c in commits:
            if c["sha"] in seen:
                continue
            seen.append(c["sha"])
            subject = c["commit"]["message"].split("\n")[0]
            findings.append(f"**{path.split('/')[-1]}** changed upstream\n`{c['sha'][:9]}` {subject}")
        time.sleep(1)  # stay well inside the anonymous rate limit
    state["seen_commits"] = seen[-200:]
    state["last_commit_scan"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check_issues(state, findings):
    states = state.setdefault("issue_states", {})
    for num, label in WATCHED_ISSUES.items():
        try:
            issue = get(f"https://api.github.com/repos/jellyfin/jellyfin/issues/{num}")
        except urllib.error.HTTPError:
            continue
        prev = states.get(str(num))
        if prev and prev != issue["state"] and issue["state"] == "closed":
            findings.append(
                f"**Issue #{num} closed upstream** -- {label}\n"
                f"Our patch for this may now be redundant.\n{issue['html_url']}")
        states[str(num)] = issue["state"]
        time.sleep(1)


def check_intro_skipper(state, findings):
    try:
        rel = get("https://api.github.com/repos/intro-skipper/intro-skipper/releases/latest")
    except urllib.error.HTTPError:
        return
    tag = rel["tag_name"]
    if tag != state.get("last_intro_skipper"):
        if state.get("last_intro_skipper"):
            findings.append(
                f"**Intro Skipper {tag}** released\n"
                f"It is what pins us to {PINNED}; a build targeting a newer server "
                f"is what opens the upgrade path.\n{rel['html_url']}")
        state["last_intro_skipper"] = tag


def main():
    state = load_state()
    findings = []
    errors = []
    for name, fn in (("release", check_release), ("paths", check_paths),
                     ("issues", check_issues), ("intro-skipper", check_intro_skipper)):
        try:
            fn(state, findings)
        except Exception as exc:  # a broken check must be loud, never silent
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_error"] = errors or None
    save_state(state)

    if errors:
        post(":warning: **jellyfin-watch check failed**\n" + "\n".join(f"- {e}" for e in errors))
    if findings:
        post(":eyes: **Upstream Jellyfin changes affecting our patches**\n\n" + "\n\n".join(findings))
    elif not errors:
        print("no changes")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
