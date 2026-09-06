#!/usr/bin/env python3
"""Cut a release of the fork.

A release here is not "upstream shipped something". It is: this exact patch series,
built onto this exact base image digest, proven by the gates, and recorded so the
same image can be rebuilt later or rolled back to.

  tools/release.py                 # prepare 10.11.11-p<next>: build, manifest, changelog, tag
  tools/release.py --version 10.11.12-p1
  tools/release.py --publish       # ...and push the tag + create the GitHub release

Nothing is pushed without --publish.

Versioning: <upstream base>-p<N>. The base is what we build from; N counts releases
of the fork on that base and resets when the base moves. The server's AssemblyVersion
is NOT this -- it stays at the upstream version because the image is a closed binding
graph, and plugins bind against it.

Changelog matching is by commit SUBJECT, not patch-id. patch-id --stable is recorded
and is reliable for spotting a CHANGED commit within one base, but it is not stable
across a base bump: the same change cherry-picked onto a different base hashes
differently, because patch-id covers context lines. Measured, not assumed.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = Path.home() / "src/jellyfin"
RELEASES = REPO / "releases"
CHANGELOG = REPO / "CHANGELOG.md"
CHERRY_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{7,40})\)")


def run(*args, cwd=REPO, check=True, capture=True):
    r = subprocess.run(args, cwd=cwd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(args)}\n{(r.stderr or r.stdout or '').strip()[:800]}")
    return r


def git(*args, cwd=REPO, check=True):
    return run("git", *args, cwd=cwd, check=check).stdout.strip()


def next_version(current):
    m = re.match(r"^(.*)-p(\d+)$", current)
    if not m:
        sys.exit(f"VERSION {current!r} is not <base>-p<N>; pass --version explicitly")
    return f"{m.group(1)}-p{int(m.group(2)) + 1}"


def series_entries(base_tag, series):
    """One record per commit in the series: what this release actually contains."""
    out = []
    for sha in git("rev-list", "--reverse", f"{base_tag}..{series}", cwd=SRC).split():
        subject = git("log", "-1", "--format=%s", sha, cwd=SRC)
        body = git("log", "-1", "--format=%B", sha, cwd=SRC)
        show = subprocess.run(["git", "show", sha], cwd=SRC, capture_output=True, text=True).stdout
        pid = subprocess.run(["git", "patch-id", "--stable"], input=show,
                             capture_output=True, text=True).stdout.split()
        m = CHERRY_RE.search(body)
        out.append({
            "sha": sha,
            "subject": subject,
            "patch_id": pid[0] if pid else None,
            "backport_of": m.group(1) if m else None,
        })
    return out


def load_previous(version):
    manifests = sorted(RELEASES.glob("*.json")) if RELEASES.is_dir() else []
    prev = [m for m in manifests if m.stem != version]
    if not prev:
        return None
    return json.loads(prev[-1].read_text())


def changelog_entry(man, prev):
    """Diff two releases by subject; patch-id only distinguishes 'changed'."""
    lines = [f"## {man['version']} — {man['released']}", ""]
    lines.append(f"Base `{man['base_tag']}` · image `{man['image']}`")
    lines.append(f"Built on `{man['base_image']}`")
    lines.append("")

    now = {c["subject"]: c for c in man["series"]}
    was = {c["subject"]: c for c in (prev or {}).get("series", [])}

    added = [s for s in now if s not in was]
    removed = [s for s in was if s not in now]
    changed = [s for s in now if s in was and now[s]["patch_id"] != was[s]["patch_id"]]

    if prev is None:
        lines.append(f"First recorded release. Contains {len(now)} change(s):")
        lines += [f"- {s}" for s in now]
        lines.append("")
    else:
        for title, items in (("Added", added), ("Changed", changed), ("Removed", removed)):
            if items:
                lines.append(f"### {title}")
                for s in items:
                    entry = now.get(s) or was[s]
                    up = entry.get("backport_of")
                    lines.append(f"- {s}" + (f" (upstream `{up[:9]}`)" if up else ""))
                lines.append("")
        if not (added or changed or removed):
            lines.append("No change to the patch series; rebuilt for tooling or base reasons.")
            lines.append("")
        lines.append(f"<details><summary>Contains {len(now)} change(s)</summary>")
        lines.append("")
        lines += [f"- {s}" for s in now]
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if man.get("tooling"):
        lines.append("### Tooling")
        lines += [f"- {t}" for t in man["tooling"]]
        lines.append("")
    lines.append(f"Assemblies replaced: {', '.join(man['assemblies'])}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version")
    ap.add_argument("--publish", action="store_true",
                    help="push the tag, create the GitHub release, and push the image to GHCR")
    ap.add_argument("--skip-build", action="store_true", help="manifest/changelog only (for testing)")
    a = ap.parse_args()

    base_tag = "v" + Path(REPO / "VERSION").read_text().strip().split("-p")[0]
    base_image = (REPO / "BASE_IMAGE").read_text().strip()
    series = "patched/10.11.11"
    version = a.version or next_version((REPO / "VERSION").read_text().strip())

    # The series must already be what patches/ says, or the release records a lie.
    run(str(REPO / "tools/regen-patches.sh"))
    dirty_patches = git("status", "--porcelain", "--", "patches")
    if dirty_patches:
        sys.exit("patches/ is out of date with the series -- commit the regenerated "
                 f"patches first:\n{dirty_patches}")

    prev_tag = git("describe", "--tags", "--abbrev=0", check=False) or None
    tooling = []
    if prev_tag:
        tooling = [l for l in git("log", "--format=%s", f"{prev_tag}..HEAD").splitlines() if l]

    (REPO / "VERSION").write_text(version + "\n")
    image = f"jellyfin-patched:{version}"

    if not a.skip_build:
        print(f"=== building {image} (gates + smoke test) ===")
        r = subprocess.run([str(REPO / "build/build.sh")], cwd=REPO)
        if r.returncode != 0:
            (REPO / "VERSION").write_text(version.rsplit("-p", 1)[0] + "-p" +
                                          str(int(version.rsplit("-p", 1)[1]) - 1) + "\n")
            sys.exit("build failed -- VERSION rolled back, nothing released")

    entries = series_entries(base_tag, series)
    assemblies = sorted({
        f.split("/")[0] + ".dll"
        for p in sorted((REPO / "patches").glob("*.patch"))
        for f in re.findall(r"^\+\+\+ b/(.+?)\s*$", p.read_text(errors="replace"), re.M)
        if not f.startswith("tests/")
    })

    man = {
        "version": version,
        "released": date.today().isoformat(),
        "base_tag": base_tag,
        "base_image": base_image,
        "image": image,
        "series_branch": series,
        "series": entries,
        "assemblies": assemblies,
        "tooling": tooling,
        "repo_commit": git("rev-parse", "HEAD"),
    }
    RELEASES.mkdir(exist_ok=True)
    (RELEASES / f"{version}.json").write_text(json.dumps(man, indent=2) + "\n")

    entry = changelog_entry(man, load_previous(version))
    header = "# Changelog\n\nReleases of the local Jellyfin fork. Each entry is one built,\ngated and smoke-tested image.\n\n"
    old = CHANGELOG.read_text() if CHANGELOG.exists() else header
    if not old.startswith("# Changelog"):
        old = header + old
    body = old[len(header):] if old.startswith(header) else old.split("\n\n", 1)[-1]
    CHANGELOG.write_text(header + entry + "\n" + body.lstrip("\n"))

    # Everything, not just the release files: a change to build/ or tools/ is part of
    # what this release IS. Committing a subset would tag a tree that was never built.
    staged = git("status", "--porcelain")
    if staged:
        print("\nreleasing with these repo changes:")
        print("\n".join("  " + l for l in staged.splitlines()))
    git("add", "-A")
    git("commit", "-q", "-m", f"Release {version}\n\n" + entry.split("\n\n", 1)[-1][:1200])
    git("tag", "-a", f"v{version}", "-m", f"Release {version}")
    print(f"\n=== prepared release v{version} ===")
    print(f"  image     {image}")
    print(f"  manifest  releases/{version}.json")
    print(f"  changelog CHANGELOG.md")
    print(f"  tag       v{version} (local)")

    if a.publish:
        print("\n=== publishing ===")
        run("git", "push", "origin", "HEAD", capture=False)
        run("git", "push", "origin", f"v{version}", capture=False)
        notes = REPO / f".release-notes-{version}.md"
        notes.write_text(entry)
        assets = [str(p) for p in sorted((REPO / "patches").glob("*.patch"))]
        assets.append(str(RELEASES / f"{version}.json"))
        run("gh", "release", "create", f"v{version}", "--title", f"{version}",
            "--notes-file", str(notes), *assets, capture=False)
        notes.unlink(missing_ok=True)
        print(f"published: https://github.com/sinful1992/jellyfin-patches/releases/tag/v{version}")

        # The image is published by .github/workflows/release.yml, which the tag push
        # above triggers. Doing it from here with a PAT is what left the package
        # account-scoped, unlinked and private; GITHUB_TOKEN in Actions publishes a
        # package that belongs to the repo and inherits its visibility.
        print("image build + publish runs in Actions (triggered by the tag):")
        print("  gh run watch  |  gh run list --workflow=release.yml")
    else:
        print("\nNot pushed. To publish:")
        print(f"  tools/release.py --version {version} --publish   (re-runs) "
              f"or: git push origin main v{version} && gh release create v{version} "
              f"--notes-file <(sed -n '/^## {version}/,/^## /p' CHANGELOG.md) patches/*.patch")


if __name__ == "__main__":
    sys.exit(main())
