from pathlib import Path
from typing import TYPE_CHECKING

import PySide6
from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStyledItemDelegate,
)

from pywr_editor.style import Color, stylesheet_dict_to_str
from pywr_editor.utils import JumpList, Settings, browse_files

if TYPE_CHECKING:
    from .left_widget import StartScreenLeftWidget


class ListViewDelegate(QStyledItemDelegate):
    title_role: int = 100
    description_role: int = 200
    last_update_role: int = 300
    full_file_role: int = 400

    def sizeHint(
        self,
        option: PySide6.QtWidgets.QStyleOptionViewItem,
        index: PySide6.QtCore.QModelIndex | PySide6.QtCore.QPersistentModelIndex,
    ) -> PySide6.QtCore.QSize:
        """
        Defines the size hint for the item.
        :param option: The option.
        :param index: The item index.
        :return: The item size.
        """
        # noinspection PyTypeHints
        option.rect: QRect

        if not index.isValid():
            return QSize()

        header_text = index.data(self.title_role)
        header_font = QFont()
        header_font.setBold(True)
        header_fm = QFontMetrics(header_font)

        sub_hearder_text = index.data(self.description_role)
        sub_header_font = QFont()
        sub_header_fm = QFontMetrics(sub_header_font)

        header_rect = header_fm.boundingRect(
            0,
            0,
            option.rect.width(),
            0,
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            header_text,
        )
        sub_header_rect = sub_header_fm.boundingRect(
            0,
            0,
            option.rect.width(),
            0,
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            sub_hearder_text,
        )
        return QSize(
            option.rect.width(),
            header_rect.height() + sub_header_rect.height() + 10 + 5,
        )

    def paint(
        self,
        painter: PySide6.QtGui.QPainter,
        option: PySide6.QtWidgets.QStyleOptionViewItem,
        index: PySide6.QtCore.QModelIndex | PySide6.QtCore.QPersistentModelIndex,
    ) -> None:
        """
        Paints the item.
        :param painter: The painter instance.
        :param option: The option.
        :param index: The item index.
        :return: None
        """
        # noinspection PyTypeHints
        option.rect: QRect

        if not index.isValid():
            return

        super().paint(painter, option, index)
        header_text = index.data(self.title_role)
        header_font = QFont()
        header_font.setBold(True)
        header_fm = QFontMetrics(header_font)

        sub_hearder_text = index.data(self.description_role)
        sub_header_font = QFont()
        sub_header_fm = QFontMetrics(sub_header_font)

        last_update_text = index.data(self.last_update_role)
        last_update_fm = QFontMetrics(sub_header_font)

        # bboxes
        header_rect = header_fm.boundingRect(
            option.rect.left() + 5,
            option.rect.top() + 5,
            option.rect.width(),
            0,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            header_text,
        )
        last_update_rect = last_update_fm.boundingRect(
            option.rect.left(),
            option.rect.top() + 5,
            option.rect.width() - 5,
            0,
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            last_update_text,
        )
        sub_header_rect = sub_header_fm.boundingRect(
            header_rect.left(),
            header_rect.bottom() + 5,
            option.rect.width(),
            0,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            sub_hearder_text,
        )

        # text
        painter.setPen(Color("gray", 700).qcolor)
        painter.setFont(header_font)
        painter.drawText(
            header_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            header_text,
        )
        painter.setFont(sub_header_font)
        painter.drawText(
            sub_header_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            sub_hearder_text,
        )
        painter.setPen(Color("gray", 500).qcolor)
        painter.drawText(
            last_update_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            last_update_text,
        )


class RecentFileListWidget(QListWidget):
    def __init__(self, parent: "StartScreenLeftWidget"):
        """
        Initialises the list widget.
        :param parent: The parent.
        """
        super().__init__(parent)

        self.setMinimumWidth(400)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(self.stylesheet)
        self.setItemDelegate(ListViewDelegate())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # load recent projects
        files_info = Settings().get_recent_files()
        # noinspection PyUnresolvedReferences
        self.itemClicked.connect(self.open_file)

        # draw items
        if files_info:
            for fi, file_info in enumerate(files_info):
                item = QListWidgetItem()
                item.setData(ListViewDelegate.title_role, file_info["title"])
                item.setData(
                    ListViewDelegate.last_update_role, file_info["last_updated"]
                )
                item.setData(
                    ListViewDelegate.description_role,
                    Path(file_info["file"]).name,
                )
                item.setData(
                    ListViewDelegate.full_file_role,
                    file_info["file"],
                )
                item.setToolTip(file_info["file"])
                self.addItem(item)
        else:
            self.add_no_item_description()

    def clear(self) -> None:
        """
        Removes the widget items.
        :return: None
        """
        super().clear()
        self.add_no_item_description()
        # clear settings and jump list
        Settings().clear_recent_files()
        JumpList().erase()

    def browse_files(self) -> None:
        """
        Browses for a new file and load it in the editor.
        :return: None
        """
        file = browse_files()
        if file:
            self.close_dialog_and_open_file(file)

    def open_file(self, file: QListWidgetItem | str | None) -> None:
        """
        Opens a model file into the editor.
        :param file: The file to open or the clicked list item.
        :return: None
        """
        if isinstance(file, QListWidgetItem):
            file = file.data(ListViewDelegate.full_file_role)
            self.close_dialog_and_open_file(file)

    def close_dialog_and_open_file(self, file: str) -> None:
        """
        Closes the start screen dialog and opens the main window on the next
        event loop iteration.
        :param file: The file to open.
        :return: None
        """
        # closing the dialog immediately would destroy it (and this widget)
        # while Qt is still processing the mouse event that triggered this
        # slot, which can crash the application - the new window is opened on
        # the next event loop iteration instead.
        # Closing the dialog also leaves no window open until then: Qt's
        # default quitOnLastWindowClosed would otherwise quit the application
        # before the new window gets a chance to open, so it is disabled for
        # this brief gap and restored once the new window is shown.
        app = QApplication.instance()
        app.setQuitOnLastWindowClosed(False)
        self.parent().dialog.close()
        QTimer.singleShot(0, lambda: self.open_main_window(file, app))

    @staticmethod
    def open_main_window(
        file: str, app: PySide6.QtWidgets.QApplication | None = None
    ) -> None:
        """
        Opens the main window on the provided file.
        :param file: The file to open.
        :param app: The application instance, whose quitOnLastWindowClosed
        property is restored once the window is open. Optional.
        :return: None
        """
        from pywr_editor.main_window import MainWindow

        # keep a reference on the class - without it, nothing holds onto this
        # window once this method returns, so it (and, being the only window
        # left, the whole application) could be garbage collected and closed
        # almost immediately. Same pattern as MainWindow.start_screen.
        MainWindow.current_window = MainWindow(file)

        if app is not None:
            app.setQuitOnLastWindowClosed(True)

    def add_no_item_description(self) -> None:
        """
        Adds the no item description.
        :return: None
        """
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        self.setWordWrap(True)
        item.setText(
            "As you use Pywr editor, any recent model will show up here for "
            + "quick access"
        )
        self.addItem(item)

    @property
    def stylesheet(self) -> str:
        """
        Defines the widget stylesheet.
        :return: The stylesheet as string.
        """
        style = {
            "RecentFileListWidget": {
                "background": "transparent",
                "border": "none",
            },
            "RecentFileListWidget:item:selected, RecentFileListWidget:item:hover, QPushButton:item:pressed": {  # noqa: E501
                "border-radius": "4px",
                "background-color": Color("blue", 200).hex,
                "border": f'1px solid {Color("blue", 400).hex}',
            },
            "RecentFileListWidget:item:disabled": {"background-color": "transparent"},
        }

        return stylesheet_dict_to_str(style)
