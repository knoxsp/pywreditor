import os
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths


class TileCache:
    """
    Stores the downloaded tiles on disk, so that they are not requested again every
    time the editor is opened, as required by the OSM tile usage policy. The cache is
    in the user's cache folder, not in the repository or next to the model.
    """

    max_age: float = 7 * 24 * 3600
    """ The age, in seconds, after which a tile is downloaded again. The tile usage
    policy asks to keep tiles for at least 7 days """
    default_root: Path | None = None
    """ The cache folder to use when none is provided. When None, the folder is
    the "pywr_editor/osm_tiles" folder in the standard cache location """

    def __init__(self, root: Path | str | None = None):
        """
        Initialises the cache.
        :param root: The cache folder. Optional.
        """
        if root is None:
            root = self.default_root
        if root is None:
            location = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.CacheLocation
            )
            root = Path(location) / "pywr_editor" / "osm_tiles"
        self.root = Path(root)

    def path(self, z: int, x: int, y: int) -> Path:
        """
        Returns the path of a tile in the cache.
        :param z: The zoom level.
        :param x: The tile column.
        :param y: The tile row.
        :return: The file path.
        """
        return self.root / str(z) / str(x) / f"{y}.png"

    def read(self, z: int, x: int, y: int, allow_stale: bool = False) -> bytes | None:
        """
        Reads a tile from the cache.
        :param z: The zoom level.
        :param x: The tile column.
        :param y: The tile row.
        :param allow_stale: Whether to return tiles older than max_age. This is used
        when the tile cannot be downloaded again.
        :return: The PNG data or None if the tile is not in the cache or is stale.
        """
        path = self.path(z, x, y)
        try:
            if not allow_stale and time.time() - path.stat().st_mtime > self.max_age:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def write(self, z: int, x: int, y: int, data: bytes) -> None:
        """
        Stores a tile in the cache. Errors (e.g. a read-only or full disk) are
        ignored: the cache is an optimisation.
        :param z: The zoom level.
        :param x: The tile column.
        :param y: The tile row.
        :param data: The PNG data.
        :return: None
        """
        path = self.path(z, x, y)
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(data)
            # atomic, so that a crash does not leave a truncated tile
            os.replace(temp_path, path)
        except OSError:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def remove(self, z: int, x: int, y: int) -> None:
        """
        Removes a tile (e.g. a corrupted one) from the cache.
        :param z: The zoom level.
        :param x: The tile column.
        :param y: The tile row.
        :return: None
        """
        try:
            self.path(z, x, y).unlink(missing_ok=True)
        except OSError:
            pass
