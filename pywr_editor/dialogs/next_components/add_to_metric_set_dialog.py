from typing import TYPE_CHECKING

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next import metric_sets as ms
from pywr_editor.widgets import PushIconButton

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 The dialog to add nodes or parameters to a metric set of a pywr-next model, from the
 schematic, the components tree or the node dialog.
"""

NEW_SET = "New metric set…"


class AddToMetricSetDialog(QDialog):
    def __init__(
        self,
        model: "ModelConfig",
        components: list[tuple[str, str, str | None]],
        parent: QWidget | None = None,
    ):
        """
        Initialises the dialog.
        :param model: The model configuration.
        :param components: What to add, as (kind, name, type): the kind is "Node",
        "VirtualNode" or "Parameter", and the type is the node type (None for a
        parameter).
        :param parent: The parent widget. Optional.
        """
        super().__init__(parent)
        self.app = parent
        self.model = model
        self.components = components
        self.added = 0
        self.set_name = ""
        self.setWindowTitle("Add to a metric set")

        names = [name for _, name, _ in components]
        label = names[0] if len(names) == 1 else f"{len(names)} components"
        self.heading = QLabel(f"Add <b>{label}</b> to a metric set, to output its values.")

        self.sets = QComboBox()
        self.sets.setObjectName("metric_set")
        self.sets.addItems(sorted(model.metric_sets.names, key=str.lower))
        self.sets.addItem(NEW_SET)
        self.new_name = QLineEdit()
        self.new_name.setObjectName("new_metric_set")
        self.new_name.setPlaceholderText("Name of the new metric set")
        # noinspection PyUnresolvedReferences
        self.sets.currentTextChanged.connect(self.on_set_changed)

        self.has_nodes = any(kind != "Parameter" for kind, _, _ in components)
        self.attribute = QComboBox()
        self.attribute.setObjectName("attribute")
        self.attribute.addItem("The usual one for each node", None)
        for attribute in ms.NODE_ATTRIBUTES:
            self.attribute.addItem(attribute, attribute)
        self.attribute.setToolTip(
            "Volume for storage nodes and Outflow for the others, or the same "
            "attribute for all the nodes"
        )

        form = QFormLayout()
        form.addRow("Metric set", self.sets)
        form.addRow("", self.new_name)
        if self.has_nodes:
            form.addRow("Attribute", self.attribute)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.add_button = PushIconButton(icon="msc.add", label="Add", accent=True)
        self.add_button.setObjectName("add_button")
        close_button = PushIconButton(icon="msc.close", label="Cancel")
        # noinspection PyUnresolvedReferences
        self.add_button.clicked.connect(self.apply)
        # noinspection PyUnresolvedReferences
        close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.add_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addLayout(buttons)
        self.setMinimumWidth(420)

        # a model without metric sets starts with a new one
        self.sets.setCurrentIndex(self.sets.count() - 1)
        self.on_set_changed(self.sets.currentText())

    @Slot(str)
    def on_set_changed(self, text: str) -> None:
        creating = text == NEW_SET
        self.new_name.setVisible(creating)
        if creating and not self.new_name.text():
            self.new_name.setText(self.unique_name("Metrics"))

    def unique_name(self, base: str) -> str:
        name, number = base, 1
        while self.model.metric_sets.exists(name):
            number += 1
            name = f"{base} {number}"
        return name

    def metrics(self) -> list[dict]:
        """
        Builds the metrics to add.
        :return: The metric dictionaries.
        """
        chosen = self.attribute.currentData()
        metrics = []
        for kind, name, node_type in self.components:
            if kind == "Parameter":
                metrics.append(ms.parameter_metric(name))
            else:
                attribute = chosen or ms.default_attribute(node_type, kind)
                metrics.append(ms.node_metric(name, attribute, kind))
        return metrics

    @Slot()
    def apply(self) -> bool:
        """
        Adds the metrics to the metric set and closes the dialog.
        :return: True if it worked.
        """
        creating = self.sets.currentText() == NEW_SET
        name = self.new_name.text().strip() if creating else self.sets.currentText()
        if not name:
            self.message.setText("Enter a name for the metric set")
            return False
        if creating and self.model.metric_sets.exists(name):
            self.message.setText(f'A metric set called "{name}" already exists')
            return False
        self.set_name = name
        self.added = ms.add_metrics(self.model, name, self.metrics(), create=creating)
        self.refresh_app()
        self.accept()
        return True

    def refresh_app(self) -> None:
        app = self.app
        while app is not None and not hasattr(app, "components_tree"):
            app = app.parent() if callable(getattr(app, "parent", None)) else None
        if app is None:
            return
        app.components_tree.reload()
        if hasattr(app, "statusBar"):
            noun = "metric" if self.added == 1 else "metrics"
            app.statusBar().showMessage(
                f'Added {self.added} {noun} to the metric set "{self.set_name}"'
                if self.added
                else f'The metric set "{self.set_name}" already had them'
            )


def add_to_metric_set(
    model: "ModelConfig",
    components: list[tuple[str, str, str | None]],
    parent: QWidget | None = None,
) -> AddToMetricSetDialog:
    """
    Opens the dialog to add nodes or parameters to a metric set.
    :param model: The model configuration.
    :param components: What to add, as (kind, name, type).
    :param parent: The parent widget. Optional.
    :return: The dialog, which is shown without blocking.
    """
    dialog = AddToMetricSetDialog(model, components, parent)
    dialog.show()
    return dialog
