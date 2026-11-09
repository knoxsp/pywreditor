import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

"""
 Python environments that the editor installs and manages to run models with a pywr
 version other than the one it bundles. pywr v1 and pywr-next both install a package
 called "pywr", so pywr-next cannot be installed next to the editor: it gets its own
 environment, created with uv (https://docs.astral.sh/uv/) after the user agrees.

 The environments are in the user data folder:
   - Windows: %LOCALAPPDATA%\\pywr-editor\\envs
   - macOS: ~/Library/Application Support/pywr-editor/envs
   - Linux: $XDG_DATA_HOME/pywr-editor/envs (~/.local/share/pywr-editor/envs)
 Each environment has a marker file recording what was installed.
"""

MARKER_FILE = "pywr-editor-env.json"
""" The file in an environment recording what the editor installed """
PYTHON_VERSION = "3.12"
""" The Python version of the environments, which uv downloads if needed """
EXTRAS = ("pandas", "excel")
""" The optional parts of pywr-next that the editor installs. Models read their time
series with pandas, and tables and time series from Excel files; polars and HDF files
are not installed """
ENVS_DIR_VARIABLE = "PYWR_EDITOR_ENVS_DIR"
""" An environment variable to store the environments somewhere else """


def envs_root() -> Path:
    """
    Returns the folder with the environments managed by the editor.
    :return: The folder path. It may not exist yet.
    """
    custom = os.environ.get(ENVS_DIR_VARIABLE)
    if custom:
        return Path(custom)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "pywr-editor" / "envs"


def pinned_pywr_next_version() -> str:
    """
    Returns the pywr-next version the editor is built for, which is the version of
    its bundled schema.
    :return: The version, such as "2.0.0rc1".
    """
    from pywr_editor.dialects.next.validation import schema_info

    return schema_info()["pywr_version"]


def python_executable(env_dir: Path) -> Path:
    """
    Returns the Python interpreter of an environment.
    :param env_dir: The environment folder.
    :return: The interpreter path.
    """
    if sys.platform == "win32":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def find_uv() -> str | None:
    """
    Finds the uv executable: bundled with the editor, or installed on the computer.
    :return: The path to uv, or None if it is not available.
    """
    name = "uv.exe" if sys.platform == "win32" else "uv"
    bundle_dirs = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
    for folder in bundle_dirs:
        candidate = folder / name
        if str(folder) and candidate.is_file():
            return str(candidate)
    return shutil.which("uv")


@dataclass(frozen=True)
class PywrEnvironment:
    """An environment with a version of pywr."""

    pywr_version: str
    """ The version of pywr to install, such as "2.0.0rc1" """
    root: Path | None = None
    """ The folder with the environments. Defaults to envs_root() """

    @property
    def path(self) -> Path:
        """
        The folder of the environment.
        """
        return (self.root or envs_root()) / f"pywr-{self.pywr_version}"

    @property
    def python(self) -> Path:
        """
        The Python interpreter of the environment.
        """
        return python_executable(self.path)

    @property
    def marker(self) -> Path:
        return self.path / MARKER_FILE

    def is_installed(self) -> bool:
        """
        Checks whether the environment was installed by the editor and is complete.
        :return: True if the environment can be used.
        """
        info = self.info()
        return (
            info is not None
            and info.get("pywr_version") == self.pywr_version
            and info.get("extras") == list(EXTRAS)
            and self.python.is_file()
        )

    def info(self) -> dict | None:
        """
        Returns what was recorded when the environment was installed.
        :return: The recorded information, or None if it is not installed.
        """
        try:
            return json.loads(self.marker.read_text())
        except (OSError, ValueError):
            return None

    def install_commands(self, uv: str) -> list[list[str]]:
        """
        Returns the commands that install the environment.
        :param uv: The path to uv.
        :return: The commands, each a list of arguments.
        """
        return [
            [uv, "venv", "--python", PYTHON_VERSION, str(self.path)],
            [
                uv,
                "pip",
                "install",
                "--python",
                str(self.python),
                f"pywr[{','.join(EXTRAS)}]=={self.pywr_version}",
            ],
        ]

    def mark_installed(self) -> None:
        """
        Records that the environment was installed, once the commands succeeded.
        :return: None
        """
        self.marker.write_text(
            json.dumps(
                {
                    "pywr_version": self.pywr_version,
                    "python_version": PYTHON_VERSION,
                    "extras": list(EXTRAS),
                    "installed_on": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            )
        )

    def remove(self) -> None:
        """
        Deletes the environment.
        :return: None
        """
        if self.path.exists():
            shutil.rmtree(self.path)


def pywr_next_environment(root: Path | None = None) -> PywrEnvironment:
    """
    Returns the environment with the pywr-next version the editor is built for.
    :param root: The folder with the environments. Defaults to envs_root().
    :return: The environment, which may not be installed yet.
    """
    return PywrEnvironment(pinned_pywr_next_version(), root)


def installed_environments(root: Path | None = None) -> list[PywrEnvironment]:
    """
    Lists the environments the editor installed.
    :param root: The folder with the environments. Defaults to envs_root().
    :return: The installed environments.
    """
    folder = root or envs_root()
    if not folder.is_dir():
        return []
    environments = []
    for child in sorted(folder.iterdir()):
        if child.is_dir() and child.name.startswith("pywr-"):
            environment = PywrEnvironment(child.name.removeprefix("pywr-"), folder)
            if environment.is_installed():
                environments.append(environment)
    return environments
