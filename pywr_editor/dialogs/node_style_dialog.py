from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.model.constants import MAX_NODE_SIZE, MIN_NODE_SIZE, UNCHANGED
from pywr_editor.style import Color

COLOR_CHOICES = [
    "red",
    "orange",
    "amber",
    "green",
    "teal",
    "blue",
    "violet",
    "pink",
    "gray",
]
""" The colours offered in the dialog """

KEEP, DEFAULT, SET = 0, 1, 2


class StyleRow(QWidget):
    """
    A row to keep, reset or set a style property: a choice and, when the property
    is set, its value.
    """

    def __init__(self, default_label: str, value_widget: QWidget):
        """
        Initialises the row.
        :param default_label: The label of the choice removing the property.
        :param value_widget: The widget with the value.
        """
        super().__init__()
        self.mode = QComboBox()
        self.mode.addItem("Keep current", KEEP)
        self.mode.addItem(default_label, DEFAULT)
        self.mode.addItem("Set to...", SET)
        self.value_widget = value_widget
        self.value_widget.setEnabled(False)
        # noinspection PyUnresolvedReferences
        self.mode.currentIndexChanged.connect(
            lambda: self.value_widget.setEnabled(self.mode.currentData() == SET)
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mode)
        layout.addWidget(self.value_widget)

    @property
    def choice(self) -> int:
        return self.mode.currentData()


class NodeStyleDialog(QDialog):
    def __init__(
        self,
        title: str,
        description: str,
        default_label: str,
        color: str | None = None,
        size: float | None = None,
        parent: QWidget | None = None,
    ):
        """
        Initialises the modal to change the colour and size of nodes or node types.
        :param title: The window title.
        :param description: A text describing what is changed.
        :param default_label: The label of the choice removing a style (for
        example the node type style).
        :param color: The colour to show when this is set. Optional.
        :param size: The size factor to show when this is set. Optional.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        self.color_field = QComboBox()
        for name in COLOR_CHOICES:
            pixmap = QPixmap(14, 14)
            pixmap.fill(Color(name, 500).qcolor)
            self.color_field.addItem(QIcon(pixmap), name.title(), name)
        if color in COLOR_CHOICES:
            self.color_field.setCurrentIndex(COLOR_CHOICES.index(color))

        self.size_field = QDoubleSpinBox()
        self.size_field.setRange(MIN_NODE_SIZE, MAX_NODE_SIZE)
        self.size_field.setSingleStep(0.25)
        self.size_field.setDecimals(2)
        self.size_field.setPrefix("x ")
        self.size_field.setValue(size if size is not None else 1.0)

        self.color_row = StyleRow(default_label, self.color_field)
        self.size_row = StyleRow(default_label, self.size_field)
        if color is not None:
            self.color_row.mode.setCurrentIndex(SET)
        if size is not None:
            self.size_row.mode.setCurrentIndex(SET)

        form = QFormLayout()
        form.addRow("Colour", self.color_row)
        form.addRow("Size", self.size_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)

        label = QLabel(description)
        label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def color(self) -> str | None | object:
        """
        The chosen colour.
        :return: The colour name, None to remove it or UNCHANGED.
        """
        return self._value(self.color_row, self.color_field.currentData())

    @property
    def size(self) -> float | None | object:
        """
        The chosen size factor.
        :return: The factor, None to remove it or UNCHANGED.
        """
        return self._value(self.size_row, float(self.size_field.value()))

    @staticmethod
    def _value(row: StyleRow, value):
        if row.choice == SET:
            return value
        return None if row.choice == DEFAULT else UNCHANGED
