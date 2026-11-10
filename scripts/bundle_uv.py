"""
 Downloads the uv executable to bundle with the editor (#45). The editor installs the
 pywr-next environment with uv (see pywr_editor/environments.py, find_uv()), and a
 user of the installer may not have it. The version is pinned and the download is
 checked against the SHA-256 of the release, written here: a changed file is refused.

 To update uv: change UV_VERSION, copy the new checksums from the files
 "uv-<target>.<ext>.sha256" next to the release assets
 (https://github.com/astral-sh/uv/releases) and run the tests in
 tests/test_bundle_uv.py.
"""
import hashlib
import io
import platform
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

UV_VERSION = "0.13.7"

UV_ARCHIVES = {
    "x86_64-pc-windows-msvc.zip": "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021",
    "aarch64-pc-windows-msvc.zip": "505d9e65e7692bac3ddf98c66754aa26c5050c409c184af30a881a0a72cc85e3",
    "x86_64-unknown-linux-gnu.tar.gz": "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83",
    "aarch64-unknown-linux-gnu.tar.gz": "71279f8d3c67241e807b9d8db872d1bf541579fb9f08b7d1eb1682196d1e57dc",
    "x86_64-apple-darwin.tar.gz": "20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7",
    "aarch64-apple-darwin.tar.gz": "81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731",
}
""" The SHA-256 of each uv release archive, by target """

DOWNLOAD_URL = "https://github.com/astral-sh/uv/releases/download/{version}/uv-{target}"


class UvDownloadError(Exception):
    """The uv archive cannot be used."""


def archive_target(system: str | None = None, machine: str | None = None) -> str:
    """
    Gets the name of the uv archive (without the "uv-" prefix) for a computer.
    :param system: The operating system as sys.platform gives it. Default: this one.
    :param machine: The processor as platform.machine() gives it. Default: this one.
    :return: The key of UV_ARCHIVES.
    """
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if system == "win32":
        target = f"{arch}-pc-windows-msvc.zip"
    elif system == "darwin":
        target = f"{arch}-apple-darwin.tar.gz"
    elif system.startswith("linux"):
        target = f"{arch}-unknown-linux-gnu.tar.gz"
    else:
        raise UvDownloadError(f"There is no uv build for {system}")
    if target not in UV_ARCHIVES:
        raise UvDownloadError(f"There is no uv build for {system} on {machine}")
    return target


def verify(data: bytes, expected: str) -> None:
    """
    Checks the SHA-256 of a downloaded archive.
    :param data: The archive.
    :param expected: The SHA-256 it must have.
    :raises UvDownloadError: If it is different.
    """
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise UvDownloadError(
            f"The checksum of the uv download is {actual}, expected {expected}"
        )


def extract_uv(data: bytes, target: str, folder: Path) -> Path:
    """
    Extracts the uv executable from an archive.
    :param data: The archive.
    :param target: The key of UV_ARCHIVES the archive is for.
    :param folder: Where the executable is written.
    :return: The path to the executable.
    """
    name = "uv.exe" if target.endswith(".zip") else "uv"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / name
    if target.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [n for n in archive.namelist() if Path(n).name == name]
            if not members:
                raise UvDownloadError(f"{name} is not in the uv archive")
            out.write_bytes(archive.read(members[0]))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = [
                m for m in archive.getmembers() if m.isfile() and Path(m.name).name == name
            ]
            if not members:
                raise UvDownloadError(f"{name} is not in the uv archive")
            extracted = archive.extractfile(members[0])
            assert extracted is not None
            out.write_bytes(extracted.read())
    out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return out


def bundle_uv(folder: Path, target: str | None = None) -> Path:
    """
    Downloads uv, checks it and puts the executable in a folder.
    :param folder: The folder for the executable.
    :param target: The key of UV_ARCHIVES. Default: the one of this computer.
    :return: The path to the executable.
    """
    target = target or archive_target()
    url = DOWNLOAD_URL.format(version=UV_VERSION, target=target)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        data = response.read()
    verify(data, UV_ARCHIVES[target])
    return extract_uv(data, target, folder)
