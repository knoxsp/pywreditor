from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest


def png_bytes(color: str = "#336699", size: int = 256) -> bytes:
    """
    Creates a PNG image.
    :param color: The fill colour.
    :param size: The image width and height.
    :return: The PNG data.
    """
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class FakeReply(QObject):
    """
    A network reply that stays pending until complete() is called.
    """

    finished = Signal()

    def __init__(self, request: QNetworkRequest):
        super().__init__()
        self.request = request
        self.aborted = False
        self._error = QNetworkReply.NetworkError.NoError
        self._data = b""

    def url(self):
        return self.request.url()

    def abort(self) -> None:
        self.aborted = True

    def error(self) -> QNetworkReply.NetworkError:
        return self._error

    def readAll(self) -> QByteArray:
        return QByteArray(self._data)

    def complete(self, data: bytes | None = None, error: bool = False) -> None:
        """
        Completes the request.
        :param data: The response body. Optional.
        :param error: Whether the request failed.
        :return: None
        """
        self._data = data if data is not None else b""
        if error:
            self._error = QNetworkReply.NetworkError.ConnectionRefusedError
        self.finished.emit()


class FakeNetwork:
    """
    Replaces QNetworkAccessManager. Requests are recorded and stay pending, so tests
    never access the network.
    """

    def __init__(self):
        self.replies: list[FakeReply] = []

    def get(self, request: QNetworkRequest) -> FakeReply:
        reply = FakeReply(request)
        self.replies.append(reply)
        return reply

    @property
    def urls(self) -> list[str]:
        """
        The URLs of the requests.
        """
        return [reply.request.url().toString() for reply in self.replies]
