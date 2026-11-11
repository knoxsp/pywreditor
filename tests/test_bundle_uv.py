import hashlib
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bundle_uv  # noqa: E402
from pywr_editor import environments  # noqa: E402


def tar_with(name: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def zip_with(name: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


class TestArchiveTarget:
    @pytest.mark.parametrize(
        "system, machine, expected",
        [
            ("win32", "AMD64", "x86_64-pc-windows-msvc.zip"),
            ("win32", "ARM64", "aarch64-pc-windows-msvc.zip"),
            ("linux", "x86_64", "x86_64-unknown-linux-gnu.tar.gz"),
            ("linux", "aarch64", "aarch64-unknown-linux-gnu.tar.gz"),
            ("darwin", "x86_64", "x86_64-apple-darwin.tar.gz"),
            ("darwin", "arm64", "aarch64-apple-darwin.tar.gz"),
        ],
    )
    def test_every_platform_has_a_pinned_archive(self, system, machine, expected):
        target = bundle_uv.archive_target(system, machine)
        assert target == expected
        # a pinned SHA-256 is 64 hexadecimal characters
        checksum = bundle_uv.UV_ARCHIVES[target]
        assert len(checksum) == 64 and int(checksum, 16) >= 0

    def test_unknown_system(self):
        with pytest.raises(bundle_uv.UvDownloadError, match="no uv build"):
            bundle_uv.archive_target("freebsd13", "x86_64")


class TestVerify:
    def test_accepts_the_right_checksum(self):
        data = b"uv"
        bundle_uv.verify(data, hashlib.sha256(data).hexdigest())

    def test_refuses_a_changed_file(self):
        with pytest.raises(bundle_uv.UvDownloadError, match="checksum"):
            bundle_uv.verify(b"changed", hashlib.sha256(b"uv").hexdigest())


class TestExtract:
    def test_tar_archive_puts_an_executable_file(self, tmp_path):
        data = tar_with("uv-x86_64-unknown-linux-gnu/uv", b"binary")
        path = bundle_uv.extract_uv(data, "x86_64-unknown-linux-gnu.tar.gz", tmp_path)
        assert path == tmp_path / "uv"
        assert path.read_bytes() == b"binary"
        assert path.stat().st_mode & 0o100

    def test_zip_archive(self, tmp_path):
        data = zip_with("uv.exe", b"binary")
        path = bundle_uv.extract_uv(data, "x86_64-pc-windows-msvc.zip", tmp_path)
        assert path == tmp_path / "uv.exe"
        assert path.read_bytes() == b"binary"

    def test_archive_without_uv(self, tmp_path):
        data = tar_with("uv-x/README", b"text")
        with pytest.raises(bundle_uv.UvDownloadError, match="not in"):
            bundle_uv.extract_uv(data, "x86_64-unknown-linux-gnu.tar.gz", tmp_path)


class TestBundledUvIsFound:
    def test_find_uv_prefers_the_copy_next_to_the_application(
        self, tmp_path, monkeypatch
    ):
        """The PyInstaller bundle puts uv next to the executable (main.spec)."""
        name = "uv.exe" if sys.platform == "win32" else "uv"
        (tmp_path / name).write_bytes(b"binary")
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert environments.find_uv() == str(tmp_path / name)

    def test_the_build_files_bundle_uv(self):
        spec = (ROOT / "main.spec").read_text()
        assert 'binaries.append((str(uv_executable), "."))' in spec
        # the Windows installer lists its files one by one
        assert 'dist\\main\\uv.exe' in (ROOT / "windows_setup.iss").read_text()
        assert "## uv" in (ROOT / "LEGAL NOTICES.md").read_text()


@pytest.mark.skipif(
    sys.platform != "linux" or "PYWR_EDITOR_NETWORK_TESTS" not in __import__("os").environ,
    reason="Downloads uv: set PYWR_EDITOR_NETWORK_TESTS=1 (Linux)",
)
def test_download_is_the_pinned_version(tmp_path):
    path = bundle_uv.bundle_uv(tmp_path)
    result = subprocess.run([str(path), "--version"], capture_output=True, text=True)
    assert bundle_uv.UV_VERSION in result.stdout
