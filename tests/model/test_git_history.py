import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pywr_editor.model.change_log import ADDED, CHANGED, REMOVED
from pywr_editor.model.git_history import GitError, GitHistory

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is missing")


def git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": __import__("os").environ["PATH"],
        "HOME": str(repo),
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


def write(repo: Path, nodes: list[dict], sidecar: dict | None = None) -> None:
    model = {"metadata": {"title": "t"}, "nodes": nodes, "edges": []}
    (repo / "sub").mkdir(exist_ok=True)
    (repo / "sub" / "model.json").write_text(json.dumps(model, indent=2))
    folder = repo / "sub" / ".pywr-editor"
    if sidecar is None:
        shutil.rmtree(folder, ignore_errors=True)
        return
    folder.mkdir(exist_ok=True)
    (folder / "model.json.json").write_text(
        json.dumps({"model": "model.json", "version": 1, **sidecar})
    )


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, [{"name": "A", "type": "input", "max_flow": 1}])
    commit(tmp_path, "first")
    write(tmp_path, [{"name": "A", "type": "input", "max_flow": 5}])
    commit(tmp_path, "raise flow")
    write(
        tmp_path,
        [{"name": "A", "type": "input", "max_flow": 5}],
        sidecar={"shapes": [{"id": "s1", "type": "text"}]},
    )
    commit(tmp_path, "add a shape")
    return tmp_path


def history(repo: Path) -> GitHistory:
    found = GitHistory.find(repo / "sub" / "model.json")
    assert found is not None
    return found


class TestGitHistory:
    def test_not_a_repository(self, tmp_path):
        (tmp_path / "model.json").write_text("{}")
        # the temporary folder could be inside a repository on some machines
        found = GitHistory.find(tmp_path / "model.json")
        assert found is None or found.repo_root != tmp_path

    def test_missing_file(self):
        assert GitHistory.find(None) is None
        assert GitHistory.find("/non/existing/model.json") is None

    def test_commits(self, repo):
        commits = history(repo).commits()
        assert [c.subject for c in commits] == ["add a shape", "raise flow", "first"]
        assert commits[0].author == "Tester"
        assert len(commits[0].hash) == 40

    def test_commit_limit(self, repo):
        assert len(history(repo).commits(limit=2)) == 2

    def test_no_commits(self, tmp_path):
        git(tmp_path, "init", "-q")
        write(tmp_path, [])
        found = history(tmp_path)
        assert found.commits() == []
        assert found.uncommitted_changes()  # all added, as nothing is committed

    def test_commit_changes_are_semantic(self, repo):
        commits = history(repo).commits()
        changes = history(repo).commit_changes(commits[1])
        assert [(c.kind, c.path_text) for c in changes] == [
            (CHANGED, 'nodes["A"].max_flow')
        ]
        assert (changes[0].old, changes[0].new) == (1, 5)

        # the change to the sidecar is in the data of the editor
        changes = history(repo).commit_changes(commits[0])
        assert [(c.kind, c.path_text) for c in changes] == [(ADDED, "pywr_editor")]

        # the first commit adds everything
        first = history(repo).commit_changes(commits[2])
        assert all(c.kind == ADDED for c in first)

    def test_uncommitted_changes(self, repo):
        found = history(repo)
        assert not found.has_uncommitted_files()
        assert found.uncommitted_changes() == []
        write(repo, [], sidecar={"shapes": [{"id": "s1", "type": "text"}]})
        assert found.has_uncommitted_files()
        assert [(c.kind, c.path_text) for c in found.uncommitted_changes()] == [
            (REMOVED, 'nodes["A"]')
        ]

    def test_restore_requires_clean_files(self, repo):
        found = history(repo)
        write(repo, [], sidecar=None)
        with pytest.raises(GitError, match="Stash"):
            found.restore(found.commits()[2].hash)

    def test_restore(self, repo):
        found = history(repo)
        first = found.commits()[2]
        found.restore(first.hash)
        model = json.loads((repo / "sub" / "model.json").read_text())
        assert model["nodes"][0]["max_flow"] == 1
        # the first commit has no sidecar
        assert not (repo / "sub" / ".pywr-editor" / "model.json.json").exists()
        # the restored version is an uncommitted change, and nothing is staged
        assert found.has_uncommitted_files()
        assert git(repo, "diff", "--cached", "--name-only").strip() == ""
        assert len(found.commits()) == 3

    def test_stash_and_apply(self, repo):
        found = history(repo)
        assert found.stashes() == []
        with pytest.raises(GitError, match="no uncommitted"):
            found.stash("nothing")

        # a change in the model and a sidecar that git does not track
        write(
            repo,
            [{"name": "A", "type": "input", "max_flow": 9}],
            sidecar={"shapes": [{"id": "new"}]},
        )
        found.stash("experiment")
        assert not found.has_uncommitted_files()
        model = json.loads((repo / "sub" / "model.json").read_text())
        assert model["nodes"][0]["max_flow"] == 5

        stashes = found.stashes()
        assert [s.message for s in stashes] == ["experiment"]
        found.apply_stash(stashes[0])
        model = json.loads((repo / "sub" / "model.json").read_text())
        assert model["nodes"][0]["max_flow"] == 9
        # the stash is kept until it is deleted
        assert len(found.stashes()) == 1
        with pytest.raises(GitError, match="uncommitted"):
            found.apply_stash(stashes[0])

        found.drop_stash(stashes[0])
        assert found.stashes() == []

    def test_stash_of_untracked_sidecar_is_recoverable(self, repo):
        found = history(repo)
        # remove the sidecar from the repository, keep an edited file on disk
        git(repo, "rm", "-q", "--cached", "-r", "sub/.pywr-editor")
        git(repo, "commit", "-q", "-m", "untrack sidecar")
        found.stash("sidecar only")
        assert not (repo / "sub" / ".pywr-editor" / "model.json.json").exists()
        found.apply_stash(found.stashes()[0])
        assert (repo / "sub" / ".pywr-editor" / "model.json.json").exists()

    def test_other_stashes_are_ignored(self, repo):
        found = history(repo)
        write(repo, [{"name": "A", "type": "input", "max_flow": 7}])
        git(repo, "stash", "push", "-m", "someone else")
        assert found.stashes() == []

    def test_stash_names_are_found_after_new_stashes(self, repo):
        found = history(repo)
        write(
            repo,
            [{"name": "A", "type": "input", "max_flow": 7}],
            sidecar={"shapes": [{"id": "s1", "type": "text"}]},
        )
        found.stash("one")
        write(
            repo,
            [{"name": "A", "type": "input", "max_flow": 8}],
            sidecar={"shapes": [{"id": "s1", "type": "text"}]},
        )
        found.stash("two")
        first = [s for s in found.stashes() if s.message == "one"][0]
        found.drop_stash(first)
        assert [s.message for s in found.stashes()] == ["two"]


class TestConflictingStash:
    def test_conflict_leaves_the_model_as_it_was(self, repo):
        found = history(repo)
        file = repo / "sub" / "model.json"
        sidecar = {"shapes": [{"id": "s1", "type": "text"}]}

        # stash a change of the flow, then commit another change of the same line
        write(repo, [{"name": "A", "type": "input", "max_flow": 100}], sidecar=sidecar)
        found.stash("hundred")
        write(repo, [{"name": "A", "type": "input", "max_flow": 200}], sidecar=sidecar)
        commit(repo, "two hundred")
        committed = file.read_text()

        with pytest.raises(GitError, match="left as it was"):
            found.apply_stash(found.stashes()[0])

        # no conflict markers, nothing left to commit, and the stash is kept
        assert file.read_text() == committed
        assert "<<<<<<<" not in file.read_text()
        assert not found.has_uncommitted_files()
        assert git(repo, "diff", "--cached", "--name-only").strip() == ""
        assert [s.message for s in found.stashes()] == ["hundred"]

    def test_conflict_removes_files_created_by_the_stash(self, repo):
        found = history(repo)
        # the commit has a sidecar: remove it from the repository, then stash a new one
        git(repo, "rm", "-q", "-r", "sub/.pywr-editor")
        git(repo, "commit", "-q", "-m", "no sidecar")
        write(
            repo,
            [{"name": "A", "type": "input", "max_flow": 100}],
            sidecar={"shapes": [{"id": "n"}]},
        )
        found.stash("with sidecar")
        write(repo, [{"name": "A", "type": "input", "max_flow": 200}])
        git(repo, "commit", "-qam", "two hundred")

        with pytest.raises(GitError):
            found.apply_stash(found.stashes()[0])
        assert not (repo / "sub" / ".pywr-editor" / "model.json.json").exists()
        assert not found.has_uncommitted_files()
