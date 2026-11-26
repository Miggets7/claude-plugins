from pathlib import Path

from byrt_release import gitops
from byrt_release.project import ReleaseError

from tests.helpers import GitRepoTest, git


class PreflightTest(GitRepoTest):
    def test_clean_synced_repo_returns_head(self):
        self.assertEqual(gitops.preflight(self.repo), git(self.repo, "rev-parse", "HEAD"))

    def test_refuses_dirty_tree(self):
        (self.repo / "README.md").write_text("changed\n")

        with self.assertRaisesRegex(ReleaseError, "uncommitted"):
            gitops.preflight(self.repo)

    def test_refuses_untracked_file(self):
        (self.repo / "new.txt").write_text("x\n")

        with self.assertRaisesRegex(ReleaseError, "new.txt"):
            gitops.preflight(self.repo)

    def test_refuses_wrong_branch(self):
        git(self.repo, "checkout", "--quiet", "-b", "feature")

        with self.assertRaisesRegex(ReleaseError, "main"):
            gitops.preflight(self.repo)

    def test_refuses_unpushed_commit(self):
        self.commit_file("a.txt", "a\n", "Local only")

        with self.assertRaisesRegex(ReleaseError, "origin/main"):
            gitops.preflight(self.repo)

    def test_refuses_when_behind_origin(self):
        self.commit_file("a.txt", "a\n", "Pushed")
        git(self.repo, "push", "--quiet")
        git(self.repo, "reset", "--quiet", "--hard", "HEAD~1")

        with self.assertRaisesRegex(ReleaseError, "origin/main"):
            gitops.preflight(self.repo)


class HistoryTest(GitRepoTest):
    def test_previous_tag_is_per_platform(self):
        git(self.repo, "tag", "android-1.1-3")
        self.commit_file("a.txt", "a\n", "Add a")
        git(self.repo, "tag", "ios-1.22-4")
        self.commit_file("b.txt", "b\n", "Add b")

        self.assertEqual(gitops.previous_tag(self.repo, "android"), "android-1.1-3")
        self.assertEqual(gitops.previous_tag(self.repo, "ios"), "ios-1.22-4")

    def test_previous_tag_is_none_without_tags(self):
        self.assertIsNone(gitops.previous_tag(self.repo, "android"))

    def test_commits_since_two_bases_deduplicates_and_skips_merges(self):
        git(self.repo, "tag", "android-1.1-3")
        self.commit_file("a.txt", "a\n", "Add a\n\nBody of a")
        git(self.repo, "tag", "ios-1.22-4")
        git(self.repo, "checkout", "--quiet", "-b", "side")
        self.commit_file("b.txt", "b\n", "Add b")
        git(self.repo, "checkout", "--quiet", "main")
        git(self.repo, "merge", "--quiet", "--no-ff", "-m", "Merge side", "side")

        commits = gitops.commits_since(self.repo, ["android-1.1-3", "ios-1.22-4"])

        self.assertEqual(sorted(commits), ["Add a\n\nBody of a", "Add b"])

    def test_commits_since_head_is_empty(self):
        self.assertEqual(gitops.commits_since(self.repo, ["HEAD"]), [])

    def test_unknown_base_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "no-such-ref"):
            gitops.commits_since(self.repo, ["no-such-ref"])


class WorkingTreeTest(GitRepoTest):
    def test_changed_paths_lists_modified_and_untracked_files(self):
        (self.repo / "README.md").write_text("changed\n")
        (self.repo / "metadata/ios/en-US").mkdir(parents=True)
        (self.repo / "metadata/ios/en-US/release_notes.txt").write_text("new\n")

        self.assertEqual(
            gitops.changed_paths(self.repo),
            {Path("README.md"), Path("metadata/ios/en-US/release_notes.txt")},
        )

    def test_restore_reverts_tracked_and_deletes_untracked(self):
        (self.repo / "README.md").write_text("changed\n")
        (self.repo / "new.txt").write_text("x\n")

        gitops.restore(self.repo, {Path("README.md"), Path("new.txt")})

        self.assertEqual((self.repo / "README.md").read_text(), "demo\n")
        self.assertFalse((self.repo / "new.txt").exists())
        self.assertEqual(gitops.changed_paths(self.repo), set())

    def test_commit_takes_only_the_given_paths(self):
        (self.repo / "README.md").write_text("changed\n")
        (self.repo / "other.txt").write_text("x\n")

        gitops.commit(self.repo, {Path("README.md")}, "Release Android 1.2 (4)")

        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "Release Android 1.2 (4)")
        self.assertEqual(gitops.changed_paths(self.repo), {Path("other.txt")})

    def test_push_sends_branch_and_tags(self):
        head = self.commit_file("a.txt", "a\n", "Add a")
        gitops.tag(self.repo, "android-1.2-4")

        gitops.push(self.repo, ["android-1.2-4"])

        self.assertEqual(self.remote_sha("main"), head)
        self.assertEqual(self.remote_sha("android-1.2-4"), head)
