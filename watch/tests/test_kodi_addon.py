"""check_kodi_addon (task 151): fake upstream + our copy as local git repos, no network.
Run: python3 -m unittest discover -s watch/tests  (from the repo root)."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)
    return subprocess.run(["git", *args[:0], "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True).stdout.strip()


def commit(repo, files, msg):
    for name, text in files.items():
        p = Path(repo, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(repo, "add", "-A")
    return git(repo, "commit", "-q", "-m", msg)


class KodiAddonCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.up, self.ours = t / "upstream", t / "ours"
        self.up.mkdir()
        git(self.up, "init", "-q", "-b", "master")
        commit(self.up, {"jellyfin_kodi/player.py": "a\n", "jellyfin_kodi/views.py": "v\n",
                         "resources/language/de/strings.po": "x\n"}, "base")
        self.base = commit(self.up, {"README.md": "r\n"}, "base 2")
        git(t, "clone", "-q", str(self.up), str(self.ours))
        git(self.ours, "checkout", "-q", "-b", "dev")
        commit(self.ours, {"jellyfin_kodi/player.py": "a\nours\n", "tests/test_x.py": "t\n",
                           "CHANGELOG.md": "c\n"}, "our fixes")
        env = {"JF_REPO_DIR": str(ROOT), "JF_WATCH_STATE": str(t / "state.json"),
               "KODI_UPSTREAM_URL": str(self.up), "KODI_OURS_URL": str(self.ours),
               "KODI_SRC_DIR": str(t / "mirror.git"), "DISCORD_WEBHOOK_URL": ""}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        spec = importlib.util.spec_from_file_location("watch", ROOT / "watch/jellyfin-upstream-watch.py")
        self.w = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.w)
        self.releases = [{"tag_name": "v2.2.0", "html_url": "u"}]
        self.w.get = lambda url: self.releases

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_check(self, state):
        findings = []
        self.w.check_kodi_addon(state, findings)
        return findings

    def test_first_run_reports_nothing_new_and_records_head(self):
        state = {}
        self.assertEqual(self.run_check(state), [])
        self.assertEqual(state["kodi_last_upstream"], self.base)
        self.assertEqual(state["kodi_last_release"], "v2.2.0")

    def test_flags_commit_touching_a_file_we_changed(self):
        state = {}
        self.run_check(state)
        commit(self.up, {"resources/language/de/strings.po": "y\n"}, "Translated using Weblate")
        commit(self.up, {"jellyfin_kodi/player.py": "b\n"}, "fix player seek")
        commit(self.up, {"jellyfin_kodi/views.py": "w\n"}, "views tweak")
        out = self.run_check(state)
        self.assertEqual(len(out), 1)
        text = out[0]
        self.assertIn("3 new upstream commit(s)", text)
        self.assertIn("(1 translation-only)", text)
        self.assertIn("fix player seek -- touches ours: jellyfin_kodi/player.py", text)
        self.assertIn("Other (1)", text)
        self.assertIn("views tweak", text)
        self.assertNotIn("Weblate", text)

    def _merge_pr(self, files, msg):
        git(self.up, "checkout", "-q", "-b", "pr")
        commit(self.up, files, msg)
        git(self.up, "checkout", "-q", "master")
        commit(self.up, {"unrelated.txt": msg}, "keep master moving")  # forces a real merge commit
        sha = git(self.up, "merge", "-q", "--no-ff", "-m", "Merge pull request: " + msg, "pr")
        git(self.up, "branch", "-q", "-D", "pr")
        return sha

    def test_translation_pr_merge_is_quiet(self):
        """ada #11274: a merge commit lists no files with `git show`; it must count by its PR."""
        state = {}
        self.run_check(state)
        git(self.up, "checkout", "-q", "-b", "pr")
        commit(self.up, {"resources/language/de/strings.po": "z\n"}, "Translated using Weblate")
        git(self.up, "checkout", "-q", "master")
        git(self.up, "merge", "-q", "--no-ff", "-m", "Merge pull request: weblate", "pr")
        git(self.up, "branch", "-q", "-D", "pr")
        self.assertEqual(self.run_check(state), [])
        self.assertEqual(state["kodi_quiet_pending"], 1)

    def test_pr_merge_touching_our_file_is_flagged_once(self):
        state = {}
        self.run_check(state)
        self._merge_pr({"jellyfin_kodi/player.py": "pr\n"}, "player fix")
        out = self.run_check(state)[0]
        self.assertIn("Merge pull request: player fix -- touches ours: jellyfin_kodi/player.py", out)
        self.assertEqual(out.count("player fix"), 1)  # the PR's own commit is not listed again

    def test_rate_limited_release_call_moves_no_state(self):
        state = {}
        self.run_check(state)
        commit(self.up, {"jellyfin_kodi/views.py": "w\n"}, "views tweak")

        def limited(url):
            raise RuntimeError("HTTP 403 rate limit")

        self.w.get = limited
        with self.assertRaises(RuntimeError):
            self.run_check(state)
        self.assertEqual(state["kodi_last_upstream"], self.base)
        self.w.get = lambda url: self.releases
        self.assertIn("views tweak", self.run_check(state)[0])

    def test_our_own_files_are_not_flagged(self):
        state = {}
        self.run_check(state)
        commit(self.up, {"tests/test_x.py": "upstream test\n", "CHANGELOG.md": "u\n"}, "upstream tests")
        out = self.run_check(state)
        self.assertNotIn("touches ours", out[0])

    def test_translation_only_is_quiet_then_counted_in_next_post(self):
        state = {}
        self.run_check(state)
        commit(self.up, {"resources/language/de/strings.po": "y\n"}, "Translated using Weblate")
        self.assertEqual(self.run_check(state), [])
        self.assertEqual(self.run_check(state), [])  # nothing new: pending kept
        self.assertEqual(state["kodi_quiet_pending"], 1)
        commit(self.up, {"jellyfin_kodi/views.py": "w\n"}, "views tweak")
        out = self.run_check(state)
        self.assertIn("Plus 1 translation-only since the last post.", out[0])
        self.assertNotIn("kodi_quiet_pending", state)

    def test_second_run_without_changes_is_silent(self):
        state = {}
        self.run_check(state)
        commit(self.up, {"jellyfin_kodi/views.py": "w\n"}, "views tweak")
        self.run_check(state)
        self.assertEqual(self.run_check(state), [])

    def test_new_release_reported_once(self):
        state = {}
        self.run_check(state)
        self.releases = [{"tag_name": "v2.3.0", "html_url": "https://x/v2.3.0"}, {"tag_name": "v2.2.0"}]
        out = self.run_check(state)
        self.assertEqual(len(out), 1)
        self.assertIn("released `v2.3.0` (was `v2.2.0`)", out[0])
        self.assertEqual(self.run_check(state), [])

    def test_draft_release_ignored(self):
        state = {}
        self.run_check(state)
        self.releases = [{"tag_name": "v9", "draft": True}, {"tag_name": "v2.2.0"}]
        self.assertEqual(self.run_check(state), [])

    def test_base_follows_a_merge_of_newer_upstream(self):
        state = {}
        self.run_check(state)
        newer = commit(self.up, {"jellyfin_kodi/views.py": "w\n"}, "views tweak")
        git(self.ours, "pull", "-q", "--no-rebase", "--no-edit", str(self.up), "master")
        commit(self.up, {"jellyfin_kodi/player.py": "c\n"}, "another player fix")
        self.releases = [{"tag_name": "v2.3.0"}]
        out = self.run_check(state)
        self.assertIn(f"based on `{newer[:9]}`", "\n".join(out))

    def test_upstream_unreachable_raises_and_keeps_state(self):
        state = {}
        self.run_check(state)
        self.w.KODI_UPSTREAM_URL = str(Path(self.tmp.name) / "missing")
        with self.assertRaises(RuntimeError):
            self.run_check(state)
        self.assertEqual(state["kodi_last_upstream"], self.base)

    def test_many_other_commits_are_capped(self):
        state = {}
        self.run_check(state)
        for i in range(13):
            commit(self.up, {f"other/f{i}.py": "x\n"}, f"other {i}")
        out = self.run_check(state)[0]
        self.assertIn("... and 3 more", out)

    def test_main_runs_the_check(self):
        self.assertIn("check_kodi_addon", (ROOT / "watch/jellyfin-upstream-watch.py").read_text().split("def main")[1])


if __name__ == "__main__":
    unittest.main()
