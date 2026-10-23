import time
from typing import Callable, Iterable

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .tile_cache import TileCache
from .tile_source import USER_AGENT, tile_url

TileKey = tuple[int, int, int]
""" The (zoom, column, row) of a tile """


class TileFetcher(QObject):
    """
    Loads tiles from memory, the disk cache or the tile server. Downloads are
    asynchronous and queued, with a small number of concurrent connections as required
    by the OSM tile usage policy. The tiles that are no longer needed (e.g. after
    panning away) are dropped from the queue and aborted - see retain().
    """

    tile_ready = Signal(int, int, int, QPixmap)
    """ Signal emitted when a tile was downloaded. The arguments are z, x, y and the
    tile """

    max_concurrent: int = 2
    """ The maximum number of connections to the tile server """
    memory_size: int = 256
    """ The maximum number of tiles kept in memory """
    retry_delay: float = 60.0
    """ The seconds to wait before requesting a tile that could not be downloaded """
    timeout: int = 15_000
    """ The request timeout in milliseconds """
    network_factory: Callable[[], QNetworkAccessManager] = QNetworkAccessManager
    """ Creates the network access manager when one is not provided to the
    constructor. Tests replace this to avoid any network access """

    def __init__(
        self,
        cache: TileCache | None = None,
        network: QNetworkAccessManager | None = None,
        parent: QObject | None = None,
    ):
        """
        Initialises the fetcher.
        :param cache: The disk cache. Optional.
        :param network: The network access manager. Optional.
        :param parent: The parent object.
        """
        super().__init__(parent)
        self.cache = cache if cache is not None else TileCache()
        self.network = network if network is not None else self.network_factory()
        self.memory: dict[TileKey, QPixmap] = {}
        """ Recently used tiles, oldest first """
        self.queue: list[TileKey] = []
        """ The tiles waiting to be downloaded """
        self.replies: dict[QObject, TileKey] = {}
        """ The pending downloads """
        self.failed: dict[TileKey, float] = {}
        """ The time at which each tile could not be downloaded """

    def get(self, key: TileKey) -> QPixmap | None:
        """
        Returns a tile if it is available without a download, otherwise queues it
        and returns None. The tile_ready signal is emitted when it is downloaded.
        :param key: The (z, x, y) tile.
        :return: The pixmap or None.
        """
        pixmap = self.memory.pop(key, None)
        if pixmap is not None:
            self.memory[key] = pixmap  # most recently used
            return pixmap

        data = self.cache.read(*key)
        if data is not None:
            pixmap = self._to_pixmap(data)
            if pixmap is not None:
                self._remember(key, pixmap)
                return pixmap
            self.cache.remove(*key)  # corrupted

        self._enqueue(key)
        return None

    def retain(self, keys: Iterable[TileKey]) -> None:
        """
        Drops the queued and pending downloads of the tiles that are not needed
        anymore.
        :param keys: The tiles that are still needed.
        :return: None
        """
        keep = set(keys)
        self.queue = [key for key in self.queue if key in keep]
        for reply, key in list(self.replies.items()):
            if key not in keep:
                del self.replies[reply]
                reply.abort()
                reply.deleteLater()
        self._start_next()

    def _enqueue(self, key: TileKey) -> None:
        """
        Queues a tile for download, unless it is already queued, pending or failed
        recently.
        :param key: The (z, x, y) tile.
        :return: None
        """
        failed_at = self.failed.get(key)
        if failed_at is not None:
            if time.monotonic() - failed_at < self.retry_delay:
                return
            del self.failed[key]
        if key in self.queue or key in self.replies.values():
            return

        self.queue.append(key)
        self._start_next()

    def _start_next(self) -> None:
        """
        Starts the queued downloads, up to the maximum number of connections.
        :return: None
        """
        while self.queue and len(self.replies) < self.max_concurrent:
            key = self.queue.pop(0)
            reply = self._start(key)
            self.replies[reply] = key
            reply.finished.connect(self._on_finished)

    def _start(self, key: TileKey) -> QNetworkReply:
        """
        Requests a tile from the server.
        :param key: The (z, x, y) tile.
        :return: The reply.
        """
        request = QNetworkRequest(QUrl(tile_url(*key)))
        # the tile server requires a User-Agent that identifies the application
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(self.timeout)
        return self.network.get(request)

    @Slot()
    def _on_finished(self) -> None:
        """
        Handles a completed download.
        :return: None
        """
        reply = self.sender()
        key = self.replies.pop(reply, None)
        if key is None:  # aborted
            return

        data = None
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = bytes(reply.readAll())
        reply.deleteLater()

        pixmap = self._to_pixmap(data) if data else None
        if pixmap is not None:
            self.cache.write(*key, data)
        else:
            # use an old tile rather than showing nothing
            self.failed[key] = time.monotonic()
            stale = self.cache.read(*key, allow_stale=True)
            pixmap = self._to_pixmap(stale) if stale else None

        if pixmap is not None:
            self._remember(key, pixmap)
            self.tile_ready.emit(*key, pixmap)
        self._start_next()

    def _remember(self, key: TileKey, pixmap: QPixmap) -> None:
        """
        Keeps a tile in memory, dropping the least recently used ones.
        :param key: The (z, x, y) tile.
        :param pixmap: The tile.
        :return: None
        """
        self.memory[key] = pixmap
        while len(self.memory) > self.memory_size:
            del self.memory[next(iter(self.memory))]

    @staticmethod
    def _to_pixmap(data: bytes) -> QPixmap | None:
        """
        Decodes a tile.
        :param data: The PNG data.
        :return: The pixmap or None if the data is not a valid image.
        """
        pixmap = QPixmap()
        if pixmap.loadFromData(data) and not pixmap.isNull():
            return pixmap
        return None
