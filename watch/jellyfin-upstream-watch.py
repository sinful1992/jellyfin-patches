#!/usr/bin/env python3
"""Watch upstream Jellyfin for anything that affects our local patch set.

Reports to Discord and never changes anything: adopting a change is always a
human decision. Uses the anonymous GitHub API on purpose -- this account is
blocked by the jellyfin org, and an unauthenticated read is unaffected by that
and needs no token to leak into a public repo.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BOT = "Bloodhound"
PINNED = "12.0"                           # the server release we build from
# The plugin names its release lines after the server major ("12.0/v12.0.3.0"), so
# this follows PINNED and rebaselines itself at a base bump.
INTRO_SKIPPER_LINE = os.environ.get("JF_INTRO_SKIPPER_LINE", PINNED)
STATE = Path(os.environ.get("JF_WATCH_STATE", Path.home() / ".local/state/jellyfin-watch/state.json"))
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Branches to scan. master alone is NOT enough: a 12.z point release -- the most
# likely thing to actually matter, e.g. a security backport -- lands on the release
# branch, and GitHub's commits API defaults to the default branch only.
WATCHED_BRANCHES = ["master", "release-12.z"]

# The patches, in the order build.sh applies them.
PATCH_DIR = Path(os.environ.get("JF_PATCH_DIR", Path.home() / "jellyfin-patches/patches"))
SRC_DIR = Path(os.environ.get("JF_SRC_DIR", Path.home() / "src/jellyfin"))
# Read from the repo's VERSION file, never hardcoded: image tags are immutable per
# release (jellyfin-patched:10.11.11-p1), so a hardcoded tag would either false-alarm
# after every release or, if set to something moving, stop detecting a stock revert.
REPO_ROOT = Path(os.environ.get("JF_REPO_DIR", Path.home() / "jellyfin-patches"))


def _fork_version():
    try:
        return (REPO_ROOT / "VERSION").read_text().strip()
    except OSError:
        return None


GHCR_OWNER = os.environ.get("GHCR_OWNER", "sinful1992")


def _expected_images():
    """Both names are legitimate for the same release.

    build.sh tags locally as jellyfin-patched:<version>; the Actions workflow
    publishes ghcr.io/<owner>/jellyfin-patched:<version>. They are built separately
    so they are not bit-identical (.NET embeds a fresh MVID per build), but both
    pass the same gates and smoke test, and either may legitimately be deployed.
    """
    v = _fork_version()
    if not v:
        return ["jellyfin-patched:10.11.11"]
    return [f"jellyfin-patched:{v}", f"ghcr.io/{GHCR_OWNER}/jellyfin-patched:{v}"]


OUT_IMAGE = os.environ.get("JF_OUT_IMAGE") or _expected_images()[0]
SERIES = os.environ.get("JF_SERIES", "patched/12.0")
PORT_CHECK = Path(os.environ.get("JF_PORT_CHECK", Path.home() / "jellyfin-patches/tools/port-check.py"))

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
    """Track the newest stable AND the newest prerelease.

    /releases/latest EXCLUDES prereleases. That single fact made this watcher
    report "10.11.11 is upstream's latest" through seven v12.0 release candidates
    while the 10.11 line was quietly abandoned -- a check that passes while the
    thing it watches has moved on.
    """
    rels = get("https://api.github.com/repos/jellyfin/jellyfin/releases?per_page=20")
    stable = next((r for r in rels if not r["prerelease"] and not r["draft"]), None)
    pre = next((r for r in rels if r["prerelease"] and not r["draft"]), None)

    if stable:
        tag = stable["tag_name"].lstrip("v")
        if tag != state.get("last_release") and tag != PINNED:
            findings.append(
                f"**Jellyfin {tag} released** (we build from {PINNED})\n"
                f"The port-check below is the cost. Plugins do not gate this: Intro "
                f"Skipper is nice-to-have, and a base bump does not wait for it.\n"
                f"{stable['html_url']}")
        state["last_release"] = tag

    if pre:
        tag = pre["tag_name"].lstrip("v")
        if tag != state.get("last_prerelease"):
            findings.append(
                f"**Prerelease {tag}** is out (we build from {PINNED})\n"
                f"Not a target to run, but it is where the next base comes from -- the "
                f"port-check below says what moving would cost.\n{pre['html_url']}")
        state["last_prerelease"] = tag


def check_paths(state, findings):
    since = state.get("last_commit_scan") or (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    seen = state.setdefault("seen_commits", [])
    for branch in WATCHED_BRANCHES:
        for path in WATCHED_PATHS:
            try:
                commits = get(
                    "https://api.github.com/repos/jellyfin/jellyfin/commits"
                    f"?path={urllib.parse.quote(path)}&sha={urllib.parse.quote(branch)}"
                    f"&since={since}&per_page=10")
            except urllib.error.HTTPError as e:
                findings.append(f"could not scan `{path}` on `{branch}` ({e.code})")
                continue
            for c in commits:
                if c["sha"] in seen:
                    continue
                seen.append(c["sha"])
                subject = c["commit"]["message"].split("\n")[0]
                findings.append(
                    f"**{path.split('/')[-1]}** changed on `{branch}`\n"
                    f"`{c['sha'][:9]}` {subject}")
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


def _ver(s):
    """Sortable tuple from a plugin version. Non-numeric parts sort as 0, which is
    fine: the plugin's own versions are numeric, and a weird one must not crash a
    check that gates nothing."""
    return tuple(int(x) if x.isdigit() else 0 for x in s.lstrip("v").split("."))


def _installed_intro_skipper():
    """What the `jellyfin` container actually HAS, or None if it cannot be read.

    Read from the host side of the /config bind mount, not `docker exec`: it works
    with the container stopped, and the point is to compare upstream against reality
    instead of against what this script happened to remember last. 12.0 keeps plugins
    in `data/plugins`; older layouts used `plugins`.
    """
    r = _run(["docker", "inspect", "--format",
              '{{range .Mounts}}{{.Destination}}\t{{.Source}}\n{{end}}', "jellyfin"], timeout=60)
    if r.returncode != 0:
        return None
    config = next((ln.split("\t", 1)[1] for ln in r.stdout.splitlines()
                   if ln.startswith("/config\t")), None)
    if not config:
        return None
    best = None
    for plugins in (Path(config) / "data/plugins", Path(config) / "plugins"):
        try:
            names = [d.name for d in plugins.iterdir() if d.is_dir()]
        except OSError:
            continue
        for name in names:
            # Jellyfin names the directory "<Plugin Name>_<version>" and can keep
            # several versions side by side; the highest is the one it loads.
            if name.lower().startswith("intro skipper_"):
                v = name.split("_", 1)[1]
                if best is None or _ver(v) > _ver(best):
                    best = v
    return best


def check_intro_skipper(state, findings):
    """Track the release line for OUR server major, not whatever published last.

    The plugin keeps one line per server major -- tags read "12.0/v12.0.3.0" and
    "10.11/v1.10.11.24" -- and /releases/latest returns the newest publish ACROSS
    lines. On 2026-09-10 that announced a 10.11 build, published five minutes later,
    to a server that had moved to 12.0 the day before, while 12.0/v12.0.3.0 went
    unreported and the stored tag regressed to the abandoned line. Same shape as
    /releases/latest hiding the prereleases: a check that passes while the thing it
    watches has moved on.
    """
    # No try/except around this: an HTTPError here (a rate-limit 403, a moved repo)
    # used to return quietly, so the check could be dead for months and look calm.
    # main() turns the exception into a loud ":warning: check failed" instead.
    rels = get("https://api.github.com/repos/intro-skipper/intro-skipper/releases?per_page=100")
    prefix = INTRO_SKIPPER_LINE + "/"
    ours = [r for r in rels
            if r["tag_name"].startswith(prefix) and not r["prerelease"] and not r["draft"]]

    if not ours:
        # Say it out loud rather than going quiet. Right after a base bump the plugin
        # may have no build for our line yet, and silence there is indistinguishable
        # from "up to date" -- which is the failure this whole watcher exists to avoid.
        none_yet = f"(no {INTRO_SKIPPER_LINE} release)"
        if state.get("last_intro_skipper") != none_yet:
            findings.append(
                f"**No Intro Skipper release for the `{INTRO_SKIPPER_LINE}` line** yet\n"
                f"FYI only -- it gates nothing. Reported because this check would "
                f"otherwise be silent, which reads exactly like up to date.")
            state["last_intro_skipper"] = none_yet
        return

    # Newest by published_at, not by list position: the lines are published
    # independently, so list order tells you about the other line as often as ours.
    rel = max(ours, key=lambda r: r["published_at"] or "")
    tag = rel["tag_name"]
    newest = tag.split("/", 1)[-1].lstrip("v")
    state["last_intro_skipper"] = tag

    installed = _installed_intro_skipper()
    if installed is None:
        # Degraded, and saying so. Without the installed version this is back to
        # comparing upstream against this script's own memory, which cannot notice a
        # plugin that was simply never upgraded.
        if state.get("last_intro_skipper_gap") != "unknown":
            findings.append(
                f"**Cannot read the installed Intro Skipper version** -- no readable "
                f"`/config` mount or plugin directory for container `jellyfin`, so the "
                f"newest build on the `{INTRO_SKIPPER_LINE}` line ({newest}) cannot be "
                f"compared against what is running. FYI only; it gates nothing.")
        state["last_intro_skipper_gap"] = "unknown"
        return

    # Keyed on the PAIR, so it posts once per real gap rather than daily, and posts
    # again on its own if either side moves. Nothing to reset by hand.
    gap = f"{installed}->{newest}" if _ver(newest) > _ver(installed) else ""
    if gap != state.get("last_intro_skipper_gap"):
        if gap:
            findings.append(
                f"**Intro Skipper {newest} is out -- `jellyfin` has {installed}** "
                f"(the `{INTRO_SKIPPER_LINE}` line, ours)\n"
                f"FYI only -- it is a nice-to-have, not a gate on anything. Reported so a "
                f"base bump can pick up a matching build if one exists.\n{rel['html_url']}")
        elif state.get("last_intro_skipper_gap") not in (None, "", "unknown"):
            findings.append(
                f"**Intro Skipper is current again** -- nothing newer than {installed} "
                f"on the `{INTRO_SKIPPER_LINE}` line")
    state["last_intro_skipper_gap"] = gap


def _run(cmd, cwd=None, timeout=900):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def check_port(state, findings):
    """Report, per commit, what moving the series to another base would cost.

    The series is commits now, not two hand-written patch files, so this can name
    the commit that conflicts instead of saying "the patch set conflicts". It also
    spots a backport upstream has since absorbed, which must be DROPPED at the bump
    rather than resolved.

    Only posts when the verdict CHANGES, so a standing "3 conflicts" does not become
    daily noise.
    """
    targets = []
    for key in ("last_release", "last_prerelease"):
        tag = state.get(key)
        if tag and tag != PINNED:
            targets.append("v" + tag)
    if not targets:
        return

    r = _run(["git", "fetch", "--tags", "--quiet", "origin"], cwd=SRC_DIR)
    if r.returncode != 0:
        raise RuntimeError(f"git fetch failed: {r.stderr.strip()[:300]}")

    # Never port-check BACKWARDS. After a base bump the newest *prerelease* on record
    # can be older than what we now build from (pinning 12.0 leaves last_prerelease at
    # 12.0-rc7), which would report the cost of moving to a base we have already passed.
    forward = []
    for tag in targets:
        # Resolve first: merge-base exits non-zero for "not an ancestor" AND for "bad
        # revision", so an unfetched or deleted tag would otherwise look like a forward
        # target and then blow up port-check on an unknown ref.
        if _run(["git", "rev-parse", "--verify", "--quiet", tag + "^{commit}"],
                cwd=SRC_DIR).returncode != 0:
            findings.append(f"port-check: upstream tag `{tag}` does not resolve; skipped")
            continue
        anc = _run(["git", "merge-base", "--is-ancestor", tag, "v" + PINNED], cwd=SRC_DIR)
        if anc.returncode != 0:
            forward.append(tag)
    targets = forward
    if not targets:
        return

    r = _run([sys.executable, str(PORT_CHECK), "--src-dir", str(SRC_DIR),
              "--base-tag", "v" + PINNED, "--series", SERIES, *targets], timeout=900)
    report = (r.stdout or r.stderr).strip()
    if not report:
        return

    if report != state.get("last_port_report"):
        findings.append("**Port check** -- what moving off " + PINNED + " would cost\n"
                        "```\n" + report[:1500] + "\n```")
    state["last_port_report"] = report


def check_deployment(state, findings):
    """Confirm the patched build is still the one actually running.

    `jellyfin-patched` is built locally and exists in no registry, so `docker image
    prune -a` or a `docker compose pull` can quietly put the stock image back. A
    watcher that reports on upstream while the local build has vanished is the
    dead-end cascade this setup is supposed to avoid.
    """
    problems = []
    r = _run(["docker", "image", "inspect", OUT_IMAGE], timeout=60)
    if r.returncode != 0:
        problems.append(
            f"image `{OUT_IMAGE}` is GONE (local-only, in no registry). "
            f"Rebuild: `bash ~/jellyfin-patches/build/build.sh`")

    r = _run(["docker", "inspect", "--format", "{{.Config.Image}}", "jellyfin"], timeout=60)
    if r.returncode != 0:
        problems.append("container `jellyfin` not found")
    else:
        running = r.stdout.strip()
        expected = [OUT_IMAGE] if os.environ.get("JF_OUT_IMAGE") else _expected_images()
        if running not in expected:
            if "jellyfin-patched:" in running:
                problems.append(
                    f"container `jellyfin` is running `{running}`, but the repo is at "
                    f"`{OUT_IMAGE}` -- an older release of ours is live. Deploy by editing "
                    f"`image:` in ~/media/docker-compose.yml, or roll VERSION back.")
            else:
                problems.append(
                    f"container `jellyfin` is running `{running}`, not `{OUT_IMAGE}` -- "
                    f"patches are NOT live")

    key = "|".join(problems)
    if key != state.get("last_deploy_state", ""):
        if problems:
            findings.append("**Local patched build drifted**\n" + "\n".join(f"- {p}" for p in problems))
        elif state.get("last_deploy_state"):
            findings.append("**Local patched build is back in place** -- `jellyfin` is running the patched image again")
    state["last_deploy_state"] = key


def main():
    state = load_state()
    findings = []
    errors = []
    for name, fn in (("release", check_release), ("paths", check_paths),
                     ("issues", check_issues), ("intro-skipper", check_intro_skipper),
                     ("port-check", check_port), ("deployment", check_deployment)):
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
