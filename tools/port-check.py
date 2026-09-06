#!/usr/bin/env python3
"""Report what it would cost to move the patch series onto another upstream tag.

The series is maintained as commits, not as hand-written patch files, so this can
ask the question that actually matters -- "does each change still apply, and is any
of it already upstream?" -- per commit rather than for the patch set as a lump.

Two verdicts per commit:
  clean      -- cherry-picks onto the target with no conflict
  CONFLICTS  -- needs hand resolution, with the conflicting files named
  redundant  -- the target already contains it (matched by the -x trailer), so the
                commit must be DROPPED at the bump or it will conflict as a duplicate

Runs entirely in a throwaway worktree; never touches the series branch or $SRC_DIR's
working tree.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHERRY_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{7,40})\)")


def git(*args, cwd, check=False):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def series_commits(src, base, series):
    out = git("rev-list", "--reverse", f"{base}..{series}", cwd=src, check=True).stdout
    return [c for c in out.split() if c]


def contains(src, tag, sha):
    """Is <sha> an ancestor of <tag>? Cheap answer to 'is this already upstream?'"""
    r = git("merge-base", "--is-ancestor", sha, tag, cwd=src)
    return r.returncode == 0


def check_target(src, base, series, target):
    lines = []
    conflicts = redundant = 0

    commits = series_commits(src, base, series)
    wt = Path(tempfile.mkdtemp(prefix="jf-portcheck-"))
    r = git("worktree", "add", "--detach", "-q", str(wt), target, cwd=src)
    if r.returncode != 0:
        shutil.rmtree(wt, ignore_errors=True)
        return [f"could not create a worktree at {target}: {r.stderr.strip()[:200]}"], 1, 0

    try:
        for sha in commits:
            subject = git("log", "-1", "--format=%s", sha, cwd=src).stdout.strip()
            body = git("log", "-1", "--format=%B", sha, cwd=src).stdout

            # A backport whose upstream commit is already in the target is not a
            # conflict to resolve -- it is a commit to delete.
            m = CHERRY_RE.search(body)
            if m and contains(src, target, m.group(1)):
                redundant += 1
                lines.append(f"  DROP       {subject[:68]}  (already in {target})")
                continue

            r = git("cherry-pick", "-x", "--no-rerere-autoupdate", sha, cwd=wt)
            if r.returncode == 0:
                lines.append(f"  clean      {subject[:68]}")
            else:
                conflicts += 1
                files = git("diff", "--name-only", "--diff-filter=U", cwd=wt).stdout.split()
                where = ", ".join(f.split("/")[-1] for f in files[:3]) or "unknown"
                lines.append(f"  CONFLICTS  {subject[:68]}  [{where}]")
                git("cherry-pick", "--abort", cwd=wt)
    finally:
        git("worktree", "remove", "--force", str(wt), cwd=src)
        shutil.rmtree(wt, ignore_errors=True)

    return lines, conflicts, redundant


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+", help="upstream tags to test, e.g. v12.0-rc7")
    ap.add_argument("--src-dir", default=str(Path.home() / "src/jellyfin"))
    ap.add_argument("--base-tag", default="v10.11.11")
    ap.add_argument("--series", default="patched/10.11.11")
    ap.add_argument("--quiet-if-clean", action="store_true",
                    help="print nothing for a target that needs no hand work")
    a = ap.parse_args()

    src = a.src_dir
    worst = 0
    for target in a.targets:
        if git("rev-parse", "--verify", "--quiet", f"{target}^{{commit}}", cwd=src).returncode != 0:
            print(f"{target}: unknown tag (fetch first)")
            worst = max(worst, 2)
            continue
        lines, conflicts, redundant = check_target(src, a.base_tag, a.series, target)
        if conflicts:
            verdict = f"{conflicts} commit(s) need hand resolution"
            worst = max(worst, 1)
        else:
            verdict = "the whole series ports cleanly"
        if redundant:
            verdict += f"; {redundant} to drop as upstream now has them"
        if conflicts or redundant or not a.quiet_if_clean:
            print(f"{a.series} -> {target}: {verdict}")
            print("\n".join(lines))
    return worst


if __name__ == "__main__":
    sys.exit(main())
