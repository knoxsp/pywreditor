from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QVBoxLayout, QWidget

from pywr_editor.model import ModelConfig
from pywr_editor.node_shapes import get_node_icon
from pywr_editor.widgets import PushIconButton

from .node_dialog import NodeDialogTitle
from .node_dialog_form import NodeDialogForm

if TYPE_CHECKING:
    from pywr_editor import MainWindow

"""
 Dockable (and undockable) panel showing the configuration of the node the user
 last double-clicked on the schematic. Unlike NodeDialog, this is not modal and
 is owned by the main window for the lifetime of the editor: double-clicking a
 different node replaces its content rather than opening a new window.
"""


class NodeDataPanel(QDockWidget):
    def __init__(self, parent: "MainWindow"):
        """
        Initialises the panel.
        :param parent: The main window.
        """
        super().__init__("Node data", parent)
        self.app = parent
        self.node_name: str | None = None
        self.title: NodeDialogTitle | None = None
        self.form: NodeDialogForm | None = None

        self.setObjectName("node_data_panel")

        self.container = QWidget(self)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self.container)

        # hidden until a node is shown via show_node()
        self.hide()

    def show_node(self, node_name: str) -> None:
        """
        Shows the configuration of the given node in the panel, replacing any
        previously displayed node.
        :param node_name: The name of the node to show.
        :return: None
        """
        model_config: ModelConfig = self.app.model_config
        node_config = model_config.nodes.config(node_name=node_name, as_dict=False)

        self._clear()
        self.node_name = node_name
        self.title = NodeDialogTitle(node_name, get_node_icon(node_config))

        save_button = PushIconButton(icon="msc.save", label="Save", accent=True)
        save_button.setObjectName("save_button")
        save_button.setEnabled(False)
        # noinspection PyUnresolvedReferences
        save_button.clicked.connect(self.on_form_save)

        self.form = NodeDialogForm(
            node_dict=node_config.props,
            model_config=model_config,
            save_button=save_button,
            parent=self,
        )

        button_container = QWidget()
        button_box = QHBoxLayout(button_container)
        button_box.setContentsMargins(0, 0, 0, 0)
        button_box.addStretch()
        button_box.addWidget(save_button)

        self.container_layout.addWidget(self.title)
        self.container_layout.addWidget(self.form)
        self.container_layout.addWidget(button_container)

        self.setWindowTitle(f"Node data - {node_name}")
        self.show()
        self.raise_()

    def on_node_deleted(self, node_name: str) -> None:
        """
        Hides the panel if it is currently showing the deleted node, so that the
        user cannot save stale data for a node that no longer exists.
        :param node_name: The name of the deleted node.
        :return: None
        """
        if self.node_name != node_name:
            return

        self._clear()
        self.node_name = None
        self.setWindowTitle("Node data")
        self.hide()

    @Slot()
    def on_form_save(self) -> None:
        """
        Saves the form and refreshes the panel with the updated node configuration.
        :return: None
        """
        form_data = self.form.save()
        if form_data is not False:
            self.show_node(form_data["name"])

    def _clear(self) -> None:
        """
        Removes the title, form and button box currently shown in the panel.
        :return: None
        """
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.title = None
        self.form = None
