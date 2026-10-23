from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.model import ModelConfig
from pywr_editor.node_shapes import get_node_icon
from pywr_editor.widgets import PushIconButton

from .node_dialog import NodeDialogTitle
from .node_dialog_form import NodeDialogForm

if TYPE_CHECKING:
    from pywr_editor import MainWindow

"""
 Dockable (and undockable) panel showing the configuration of the node (flow limits,
 cost, ...). Double-click a node on the schematic to show the panel. While the panel
 is visible, clicking on another node shows that node. Unlike NodeDialog, the panel
 is not modal and is owned by the main window for the lifetime of the editor. The
 name, type and style of the node are edited in NodeDialog.

 The panel shows only the configuration part of the node form (NodeDialogForm). The
 rest of the form is kept hidden, so that all the fields are validated and saved
 together and the values that are not shown are preserved.
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
        # the form is tall: scroll it, so that the panel can be docked in a short
        # strip without squeezing the schematic
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(self.container)
        self.setWidget(scroll_area)
        self.setMinimumHeight(120)

        # hidden until a node is shown via show_node()
        self.hide()

    def follow_node(self, node_name: str) -> None:
        """
        Shows the node clicked on the schematic, if the panel is visible. Nothing
        changes when the node is already shown, so that the changes not saved yet in
        the form are not lost by clicking on the same node.
        :param node_name: The name of the selected node.
        :return: None
        """
        if self.isHidden() or node_name == self.node_name:
            return
        self.show_node(node_name)

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

        # the form validates and saves all the fields, so it is kept, hidden, while
        # only its configuration part is shown
        config_parts = [
            part for name, part in self.form.sections.items() if name != "Node"
        ]
        for part in config_parts:
            self.form.area_layout.removeWidget(part)

        button_container = QWidget()
        button_box = QHBoxLayout(button_container)
        button_box.setContentsMargins(0, 0, 0, 0)
        button_box.addStretch()
        button_box.addWidget(save_button)

        self.container_layout.addWidget(self.title)
        for part in config_parts:
            self.container_layout.addWidget(part)
        self.container_layout.addWidget(button_container)
        self.container_layout.addWidget(self.form)
        self.form.hide()

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
