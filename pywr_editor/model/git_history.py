import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pywr_editor.model.change_log import Change, diff
from pywr_editor.model.sidecar import merge_editor_data, sidecar_path

"""
 Reads the git history of a model, if the model file is in a git repository.

 The history is read with the git command, so the editor needs git to be installed.
 The model is compared the way the editor sees it: the model and its sidecar (see
 sidecar.py) at a commit are merged, and compared with the same data of the previous
 commit using the diff of the change log. This shows what changed in the model rather
 than which lines of the JSON file changed.

 Git is only changed when the user asks to restore a version or to stash the changes.
 Both leave the work recoverable: restoring replaces the files only when the files have
 no uncommitted changes, and the changes are stashed first, including the files git
 does not track.
"""

MAX_COMMITS = 100
""" The number of commits to list """
GIT_TIMEOUT = 20
""" The seconds git can take to run a command """
STASH_MARKER = "pywr-editor"
""" The stashes created by the editor start with this text, followed by the model file
name, to tell them from the stashes of the other files """

_FIELD = "\x1f"
_RECORD = "\x1e"


class GitError(Exception):
    """Raised when git cannot do what is asked. The message is shown to the user."""


@dataclass(frozen=True)
class Commit:
    hash: str
    short_hash: str
    author: str
    date: datetime
    subject: str


@dataclass(frozen=True)
class Stash:
    hash: str
    date: datetime
    message: str
    """ The note given when the changes were stashed """


def git_available() -> bool:
    """Returns True if the git command is installed."""
    return shutil.which("git") is not None


class GitHistory:
    def __init__(self, json_file: str | os.PathLike, repo_root: Path):
        """
        Initialises the class. Use GitHistory.find() to create it.
        :param json_file: The path to the model file.
        :param repo_root: The root folder of the git repository.
        """
        self.json_file = Path(json_file).resolve()
        self.repo_root = repo_root
        self.model_path = self.json_file.relative_to(repo_root).as_posix()
        """ The path of the model in the repository """
        self.sidecar_file = sidecar_path(self.json_file)
        self.sidecar_path = self.sidecar_file.relative_to(repo_root).as_posix()
        """ The path of the sidecar in the repository """

    @staticmethod
    def find(json_file: str | os.PathLike | None) -> "GitHistory | None":
        """
        Finds the repository of a model.
        :param json_file: The path to the model file.
        :return: The instance, or None if the model is not in a git repository or git
        is not installed.
        """
        if not json_file or not git_available():
            return None
        folder = Path(json_file).resolve().parent
        if not folder.is_dir():
            return None
        try:
            root = GitHistory._run(folder, "rev-parse", "--show-toplevel").strip()
            return GitHistory(json_file, Path(root).resolve())
        except (GitError, ValueError):
            return None

    @staticmethod
    def _run(
        folder: Path, *args: str, binary: bool = False, check: bool = True
    ) -> str | bytes:
        """
        Runs a git command.
        :param folder: The folder where the command is run.
        :param args: The git arguments.
        :param binary: Whether to return the output as bytes.
        :param check: Whether to raise an error if git fails.
        :return: The output of the command, or an empty output if it failed and check
        is False.
        """
        # the paths are given to git as they are, and the output does not depend on the
        # language of the user
        env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
        try:
            result = subprocess.run(
                ["git", "--literal-pathspecs", "-C", str(folder), *args],
                capture_output=True,
                timeout=GIT_TIMEOUT,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitError(f"git cannot be run: {error}") from error
        if result.returncode != 0:
            if check:
                message = result.stderr.decode("utf-8", "replace").strip()
                raise GitError(message or f"git {args[0]} failed")
            return b"" if binary else ""
        return result.stdout if binary else result.stdout.decode("utf-8", "replace")

    def _git(self, *args: str, binary: bool = False, check: bool = True):
        return self._run(self.repo_root, *args, binary=binary, check=check)

    @property
    def _paths(self) -> list[str]:
        """The files of the model in the repository, that exist or are tracked."""
        paths = [self.model_path]
        tracked = self._git("ls-files", "--", self.sidecar_path, check=False).strip()
        if tracked or self.sidecar_file.exists():
            paths.append(self.sidecar_path)
        return paths

    # ---- reading the history

    def commits(self, limit: int = MAX_COMMITS) -> list[Commit]:
        """
        Returns the latest commits changing the model or its sidecar, newest first.
        :param limit: The maximum number of commits.
        :return: The commits. The list is empty if the repository has no commits.
        """
        fmt = _FIELD.join(["%H", "%h", "%an", "%aI", "%s"]) + _RECORD
        # git fails if the repository has no commits yet
        if not self._git("rev-parse", "--verify", "-q", "HEAD", check=False).strip():
            return []
        output = self._git(
            "log", f"-n{int(limit)}", f"--format={fmt}", "--", *self._paths
        )
        commits = []
        for record in output.split(_RECORD):
            fields = record.strip("\n").split(_FIELD)
            if len(fields) != 5:
                continue
            commits.append(
                Commit(
                    hash=fields[0],
                    short_hash=fields[1],
                    author=fields[2],
                    date=datetime.fromisoformat(fields[3]),
                    subject=fields[4],
                )
            )
        return commits

    def _exists(self, revision: str, path: str) -> bool:
        """Returns True if the file exists in the commit."""
        try:
            self._git("cat-file", "-e", f"{revision}:{path}")
            return True
        except GitError:
            return False

    def _blob(self, revision: str, path: str) -> bytes | None:
        """
        Returns a file at a commit.
        :return: The content, or None if the file does not exist in the commit.
        """
        if not self._exists(revision, path):
            return None
        return self._git("show", f"{revision}:{path}", binary=True)

    @staticmethod
    def _parse(model: bytes, sidecar: bytes | None, label: str) -> dict:
        """
        Parses a model and merges its sidecar.
        :param model: The content of the model file.
        :param sidecar: The content of the sidecar, if any.
        :param label: What the data is, for the error message.
        :return: The model as the editor sees it.
        """
        try:
            data = json.loads(model)
            if not isinstance(data, dict):
                raise ValueError("the model must be a dictionary")
        except ValueError as error:
            raise GitError(f"The model in {label} cannot be read: {error}") from error
        if sidecar:
            # a sidecar that cannot be read is ignored, as the editor does
            try:
                editor_data = json.loads(sidecar)
                if isinstance(editor_data, dict):
                    merge_editor_data(data, editor_data)
            except ValueError:
                pass
        return data

    def model_at(self, revision: str) -> dict | None:
        """
        Returns the model at a commit, as the editor sees it.
        :param revision: The commit hash or reference.
        :return: The model dictionary, or None if the model is not in the commit.
        """
        model = self._blob(revision, self.model_path)
        if model is None:
            return None
        sidecar = self._blob(revision, self.sidecar_path)
        return self._parse(model, sidecar, f"commit {revision[:7]}")

    def working_model(self) -> dict | None:
        """
        Returns the model saved on disk, as the editor sees it.
        :return: The model dictionary, or None if the file does not exist.
        """
        if not self.json_file.exists():
            return None
        sidecar = self.sidecar_file.read_bytes() if self.sidecar_file.exists() else None
        return self._parse(self.json_file.read_bytes(), sidecar, "the working tree")

    def commit_changes(self, commit: Commit) -> list[Change]:
        """
        Returns what a commit changed in the model.
        :param commit: The commit.
        :return: The changes. For the first commit, the whole model is added.
        """
        parent = self.model_at(f"{commit.hash}^") if self._has_parent(commit) else None
        new = self.model_at(commit.hash)
        return list(diff(parent or {}, new or {}))

    def _has_parent(self, commit: Commit) -> bool:
        return bool(
            self._git("rev-parse", "--verify", "-q", f"{commit.hash}^", check=False)
        )

    def uncommitted_changes(self) -> list[Change]:
        """
        Returns what changed in the model saved on disk since the last commit.
        :return: The changes. Empty if the model is the same as in the commit.
        """
        head = None
        if self._git("rev-parse", "--verify", "-q", "HEAD", check=False).strip():
            head = self.model_at("HEAD")
        return list(diff(head or {}, self.working_model() or {}))

    def has_uncommitted_files(self) -> bool:
        """
        Returns True if the model file or its sidecar is not the same as in the last
        commit (including files that git does not track yet).
        """
        status = self._git(
            "status", "--porcelain", "--untracked-files=all", "--", *self._paths
        )
        return bool(status.strip())

    # ---- changing the files

    def restore(self, revision: str) -> None:
        """
        Replaces the model and its sidecar with the files of a commit. The files are
        not added to git: the restored version shows as an uncommitted change.
        :param revision: The commit hash.
        :return: None
        """
        if self.has_uncommitted_files():
            raise GitError(
                "The model has uncommitted changes that would be lost. Stash them first"
            )
        model = self._blob(revision, self.model_path)
        if model is None:
            raise GitError("The model does not exist in this commit")
        sidecar = self._blob(revision, self.sidecar_path)

        self.json_file.write_bytes(model)
        if sidecar is not None:
            self.sidecar_file.parent.mkdir(exist_ok=True)
            self.sidecar_file.write_bytes(sidecar)
        elif self.sidecar_file.exists():
            # the commit has no editor data
            self.sidecar_file.unlink()

    def stashes(self) -> list[Stash]:
        """
        Returns the stashes created by the editor for this model, newest first.
        """
        prefix = self._stash_prefix
        fmt = _FIELD.join(["%H", "%aI", "%s"]) + _RECORD
        output = self._git("stash", "list", f"--format={fmt}", check=False)
        stashes = []
        for record in output.split(_RECORD):
            fields = record.strip("\n").split(_FIELD)
            if len(fields) != 3 or prefix not in fields[2]:
                continue
            note = fields[2].split(prefix, 1)[1].strip()
            stashes.append(
                Stash(
                    hash=fields[0], date=datetime.fromisoformat(fields[1]), message=note
                )
            )
        return stashes

    @property
    def _stash_prefix(self) -> str:
        return f"{STASH_MARKER}: {self.json_file.name} |"

    def stash(self, note: str = "") -> None:
        """
        Puts the uncommitted changes of the model and its sidecar in a stash, which
        returns the files to their state in the last commit.
        :param note: A description of the stash.
        :return: None
        """
        if not self.has_uncommitted_files():
            raise GitError("There are no uncommitted changes to stash")
        message = f"{self._stash_prefix} {note.strip() or 'changes'}"
        self._git(
            "stash", "push", "--include-untracked", "-m", message, "--", *self._paths
        )

    def _stash_ref(self, stash: Stash) -> str:
        """Finds the current reference of a stash, which changes with new stashes."""
        output = self._git("stash", "list", "--format=%H", check=False)
        for index, commit_hash in enumerate(output.split()):
            if commit_hash == stash.hash:
                return f"stash@{{{index}}}"
        raise GitError("The stash does not exist anymore")

    def apply_stash(self, stash: Stash) -> None:
        """
        Applies a stash to the model files. The stash is kept.
        :param stash: The stash.
        :return: None
        """
        if self.has_uncommitted_files():
            raise GitError(
                "The model has uncommitted changes. Stash them or commit them before "
                "applying another stash"
            )
        try:
            self._git("stash", "apply", self._stash_ref(stash))
        except GitError as error:
            # the stash can conflict with the model, which then has conflict markers
            # and cannot be opened. The files had no changes before the stash was
            # applied (see above), so the files are returned to the last commit
            self._discard_changes()
            raise GitError(
                "The stash cannot be applied to the current version of the model, "
                "and the model was left as it was.\n\n"
                f"{error}"
            ) from error

    def _discard_changes(self) -> None:
        """
        Returns the model and its sidecar to the last commit. Files that are not in
        the last commit are removed. This must only be used when the files had no
        changes to keep.
        """
        for path, file in (
            (self.model_path, self.json_file),
            (self.sidecar_path, self.sidecar_file),
        ):
            if self._exists("HEAD", path):
                # also solves the conflicts
                self._git("checkout", "HEAD", "--", path, check=False)
            else:
                self._git("rm", "-q", "-f", "--cached", "--", path, check=False)
                if file.exists():
                    file.unlink()

    def drop_stash(self, stash: Stash) -> None:
        """
        Deletes a stash.
        :param stash: The stash.
        :return: None
        """
        self._git("stash", "drop", self._stash_ref(stash))
