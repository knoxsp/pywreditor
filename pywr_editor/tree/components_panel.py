from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from .components_tree import ComponentsTree


class ComponentsPanel(QWidget):
    def __init__(self, tree: ComponentsTree, parent: QWidget | None = None):
        """
        Initialises the panel with a search entry above the components tree. The
        entry filters the nodes, parameters, recorders, tables and scenarios.
        :param tree: The components tree.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.tree = tree

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search nodes, parameters, recorders...")
        self.search.setToolTip(
            "Show only the components whose name or value contains the text. "
            "Press Escape to clear"
        )
        self.search.setClearButtonEnabled(True)
        self.status = QLabel()
        self.status.setStyleSheet("color: gray; padding: 0 4px")
        self.status.hide()

        # filtering a large model on every key press is wasteful
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.apply_filter)
        # noinspection PyUnresolvedReferences
        self.search.textChanged.connect(self.timer.start)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.search)
        layout.addWidget(self.status)
        layout.addWidget(self.tree, 1)

    @Slot()
    def apply_filter(self) -> None:
        text = self.search.text()
        matches = self.tree.filter_items(text)
        if text.strip():
            self.status.setText(
                f"{matches} match{'es' if matches != 1 else ''}"
                if matches
                else "No matches"
            )
            self.status.show()
        else:
            self.status.hide()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.search.text():
            self.search.clear()
            event.accept()
            return
        super().keyPressEvent(event)
