import copy
from typing import TYPE_CHECKING, Union

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout

from pywr_editor.dialects.next.schema import bundled_schema
from pywr_editor.form import FieldConfig, Form, TextWidget, Validation
from pywr_editor.form.schema_form import field_configs, introduced_issues
from pywr_editor.model import ModelConfig
from pywr_editor.node_shapes import get_node_icon
from pywr_editor.widgets import PushIconButton

from .node_dialog import NodeDialogTitle

if TYPE_CHECKING:
    from pywr_editor import MainWindow

"""
 The dialog to edit a pywr-next node. Its fields are generated from the bundled
 pywr-next schema for the node type (see form/schema_form.py); the name and comment
 are edited here and stored in the node's "meta", with its position and tags.
"""

LOCAL_PARAMETERS_KEY = "parameters"
""" The node key with the local parameters """


class NextNodeDialog(QDialog):
    def __init__(
        self,
        node_name: str,
        model_config: ModelConfig,
        parent: Union[QWindow, "MainWindow", None] = None,
    ):
        """
        Initialises the dialog.
        :param node_name: The name of the node to edit.
        :param model_config: The ModelConfig instance of a pywr-next model.
        :param parent: The parent widget. Default to None.
        """
        super().__init__(parent)
        self.app = parent
        self.model_config = model_config
        self.node = model_config.nodes.config(node_name=node_name, as_dict=False)
        self.node_name = node_name
        self.node_type = self.node.props.get("type")

        self.title = NodeDialogTitle(node_name, get_node_icon(self.node))
        schema = bundled_schema()
        known_type = self.node_type in schema.types("Node")
        description = schema.description("Node", self.node_type) if known_type else None
        self.description = QLabel(
            description
            or f"The type {self.node_type!r} is not in the bundled pywr-next schema"
        )
        self.description.setWordWrap(True)

        self.save_button = PushIconButton(icon="msc.save", label="Save", accent=True)
        self.save_button.setObjectName("save_button")
        # noinspection PyUnresolvedReferences
        self.save_button.clicked.connect(self.on_form_save)
        close_button = PushIconButton(icon="msc.close", label="Close")
        # noinspection PyUnresolvedReferences
        close_button.clicked.connect(self.reject)
        button_box = QHBoxLayout()
        button_box.addStretch()
        button_box.addWidget(self.save_button)
        button_box.addWidget(close_button)

        values = {k: v for k, v in self.node.props.items() if k not in ("meta", "type")}
        specs = schema.fields("Node", self.node_type) if known_type else []
        config_specs = [s for s in specs if s.name != LOCAL_PARAMETERS_KEY]
        local_specs = [s for s in specs if s.name == LOCAL_PARAMETERS_KEY]
        # a key the schema does not describe is kept, and edited as JSON
        described = {spec.name for spec in specs}
        unknown = {k: v for k, v in values.items() if k not in described}

        fields = {
            "Node": [
                FieldConfig(
                    name="name",
                    value=node_name,
                    allow_empty=False,
                    validate_fun=self.check_name,
                ),
                FieldConfig(
                    name="comment",
                    value=self.node.comment,
                    field_type=TextWidget,
                    field_args={"multi_line": True},
                ),
            ],
        }
        if config_specs:
            fields["Configuration"] = field_configs(config_specs, values, model_config)
        if unknown:
            from pywr_editor.dialects.next.schema import FieldSpec

            fields["Other values"] = field_configs(
                [FieldSpec(name=key, label=key, kind="json") for key in unknown],
                unknown,
            )

        self.form = Form(fields=fields, save_button=self.save_button, parent=self)
        self.form.load_fields()
        self.save_button.setEnabled(False)

        # the local parameters are edited in the parameters dialog
        local_box = QHBoxLayout()
        self.local_parameters_label = QLabel()
        self.local_parameters_button = PushIconButton(
            icon="msc.symbol-variable", label="Edit local parameters"
        )
        # noinspection PyUnresolvedReferences
        self.local_parameters_button.clicked.connect(self.on_edit_local_parameters)
        local_box.addWidget(self.local_parameters_label)
        local_box.addStretch()
        local_box.addWidget(self.local_parameters_button)
        self.local_parameters_button.setVisible(bool(local_specs))
        self.local_parameters_label.setVisible(bool(local_specs))
        self.update_local_parameters_label()

        # the metric sets that output the node
        metrics_box = QHBoxLayout()
        self.metric_sets_label = QLabel()
        self.metric_sets_label.setObjectName("metric_sets_label")
        self.metric_sets_label.setWordWrap(True)
        self.metric_sets_button = PushIconButton(
            icon="msc.graph", label="Add to metric set..."
        )
        self.metric_sets_button.setObjectName("metric_sets_button")
        # noinspection PyUnresolvedReferences
        self.metric_sets_button.clicked.connect(self.on_add_to_metric_set)
        metrics_box.addWidget(self.metric_sets_label, 1)
        metrics_box.addWidget(self.metric_sets_button)
        self.update_metric_sets_label()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        layout.addWidget(self.form)
        layout.addLayout(local_box)
        layout.addLayout(metrics_box)
        layout.addLayout(button_box)

        self.setWindowTitle(f"Edit node - {node_name}")
        self.setMinimumSize(750, 650)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def update_metric_sets_label(self) -> None:
        """
        Shows the metric sets that have a metric for the node.
        :return: None
        """
        from pywr_editor.dialects.next import metric_sets

        sets = metric_sets.sets_containing(self.model_config, "Node", self.node_name)
        self.metric_sets_label.setText(
            "Metric sets: " + metric_sets.describe_sets(sets)
            if sets
            else "Not in any metric set, so its values are not output"
        )

    @Slot()
    def on_add_to_metric_set(self) -> None:
        """
        Opens the dialog to add the node to a metric set.
        :return: None
        """
        from pywr_editor.dialogs.next_components.add_to_metric_set_dialog import (
            add_to_metric_set,
        )

        dialog = add_to_metric_set(
            self.model_config, [("Node", self.node_name, self.node_type)], self
        )
        # noinspection PyUnresolvedReferences
        dialog.finished.connect(self.update_metric_sets_label)

    def update_local_parameters_label(self) -> None:
        """
        Shows how many local parameters the node has.
        :return: None
        """
        node = self.model_config.nodes.config(self.node_name) or {}
        count = len(node.get(LOCAL_PARAMETERS_KEY) or [])
        self.local_parameters_label.setText(f"Local parameters: {count}")

    @Slot()
    def on_edit_local_parameters(self) -> None:
        """
        Opens the parameters dialog with the local parameters of the node.
        :return: None
        """
        from pywr_editor.dialogs.next_components.components_dialog import (
            open_local_parameters,
        )

        dialog = open_local_parameters(self.model_config, self.node_name, self)
        # noinspection PyUnresolvedReferences
        dialog.finished.connect(self.update_local_parameters_label)

    def check_name(self, name: str, label: str, value: str) -> Validation:
        """
        Checks that the name is not used by another node or virtual node.
        :param name: The field name.
        :param label: The field label.
        :param value: The node name.
        :return: The Validation instance.
        """
        if not isinstance(value, str) or not value.strip():
            return Validation("The name cannot be empty")
        if value != self.node_name and (
            value in self.model_config.nodes.names
            or value in self.model_config.virtual_nodes.names
        ):
            return Validation("A node with this name already exists")
        return Validation()

    def node_dict(self, form_data: dict) -> dict:
        """
        Builds the new node dictionary from the form values.
        :param form_data: The values returned by the form.
        :return: The node dictionary.
        """
        meta = copy.deepcopy(self.node.props.get("meta", {}))
        meta["name"] = form_data.pop("name")
        comment = form_data.pop("comment", None)
        if comment:
            meta["comment"] = comment
        else:
            meta.pop("comment", None)
        node = {"meta": meta, "type": self.node_type, **form_data}
        # keep the local parameters as they are now in the model: they are edited
        # in the parameters dialog
        current = self.model_config.nodes.config(self.node_name) or {}
        if LOCAL_PARAMETERS_KEY in current:
            node[LOCAL_PARAMETERS_KEY] = current[LOCAL_PARAMETERS_KEY]
        return node

    @Slot()
    def on_form_save(self) -> None:
        """
        Saves the node and closes the dialog.
        :return: None
        """
        if self.save():
            self.close()

    def save(self) -> dict | bool:
        """
        Validates the form and saves the node.
        :return: The new node dictionary, or False if the form does not validate.
        """
        form_data = self.form.validate()
        if form_data is False:
            return False

        node = self.node_dict(form_data)
        introduced = introduced_issues("Node", self.node_type, self.node.props, node)
        if introduced:
            QMessageBox.critical(
                self,
                "Cannot save the form",
                "The schema does not accept the result:\n\n"
                + "\n".join(issue.message for issue in introduced[:5]),
            )
            return False
        new_name = node["meta"]["name"]
        if new_name != self.node_name:
            # renames the edges and the references to the node too
            self.model_config.nodes.rename(self.node_name, new_name)
            self.title.update_name(new_name)
            self.node_name = new_name
        self.model_config.nodes.update(node)

        app = self.app
        if app is not None:
            if hasattr(app, "schematic"):
                app.schematic.reload()
            if hasattr(app, "components_tree"):
                app.components_tree.reload()
            if hasattr(app, "statusBar"):
                app.statusBar().showMessage(f'Updated node "{new_name}"')
        return node
