import copy
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next import python_code
from pywr_editor.dialects.next.model import NamedComponents, humanise_type
from pywr_editor.dialects.next.schema import FieldSpec, bundled_schema
from pywr_editor.form import FieldConfig, Form, TextWidget, Validation
from pywr_editor.dialogs.next_components.python_panel import PythonCodePanel
from pywr_editor.form.schema_form import field_configs, introduced_issues
from pywr_editor.widgets import PushIconButton

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 A dialog to list, add, clone, rename, edit and delete the components in a list of a
 pywr-next model, such as the parameters or the tables. The form of a component is
 generated from the bundled schema for its type.
"""


class NextComponentsDialog(QDialog):
    definition: str = ""
    """ The schema definition of the components, such as "Parameter" """
    title: str = ""
    """ The window title, such as "Parameters" """

    def __init__(
        self,
        model: "ModelConfig",
        selected_name: str | None = None,
        parent: QWidget | None = None,
        components: NamedComponents | None = None,
    ):
        """
        Initialises the dialog.
        :param model: The model configuration.
        :param selected_name: The name of the component to show. Optional.
        :param parent: The parent widget. Optional.
        :param components: The list of components. Defaults to the list of the
        network given by components_of().
        """
        super().__init__(parent)
        self.app = parent
        self.model = model
        self.components = components or self.components_of(model)
        self.schema = bundled_schema()
        # a kind of component with one shape (such as the metric sets) has no type
        self.single_type = not self.schema.types(self.definition)
        self.tag = None if self.single_type else self.schema.tag_key(self.definition)
        self.current: str | None = None
        self.form: Form | None = None

        # left: the list of components
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name or type")
        self.filter.setClearButtonEnabled(True)
        # noinspection PyUnresolvedReferences
        self.filter.textChanged.connect(self.apply_filter)
        self.list = QListWidget()
        self.list.setObjectName("components_list")
        # noinspection PyUnresolvedReferences
        self.list.currentItemChanged.connect(self.on_selection_changed)

        self.add_button = PushIconButton(icon="msc.add", label="Add")
        self.clone_button = PushIconButton(icon="msc.copy", label="Clone")
        self.delete_button = PushIconButton(icon="msc.trash", label="Delete")
        # noinspection PyUnresolvedReferences
        self.add_button.clicked.connect(self.on_add)
        # noinspection PyUnresolvedReferences
        self.clone_button.clicked.connect(self.on_clone)
        # noinspection PyUnresolvedReferences
        self.delete_button.clicked.connect(self.on_delete)
        list_buttons = QHBoxLayout()
        list_buttons.addWidget(self.add_button)
        list_buttons.addWidget(self.clone_button)
        list_buttons.addWidget(self.delete_button)

        left = QVBoxLayout()
        left.addWidget(self.filter)
        left.addWidget(self.list)
        left.addLayout(list_buttons)

        # right: the form of the selected component
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 16px; font-weight: bold")
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.form_container = QVBoxLayout()
        self.save_button = PushIconButton(icon="msc.save", label="Save", accent=True)
        self.save_button.setObjectName("save_button")
        self.save_button.setEnabled(False)
        # noinspection PyUnresolvedReferences
        self.save_button.clicked.connect(self.save)
        close_button = PushIconButton(icon="msc.close", label="Close")
        # noinspection PyUnresolvedReferences
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.save_button)
        buttons.addWidget(close_button)

        right = QVBoxLayout()
        right.addWidget(self.heading)
        right.addWidget(self.description)
        right.addLayout(self.form_container, 1)
        right.addLayout(buttons)

        layout = QHBoxLayout(self)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(320)
        layout.addWidget(left_widget)
        layout.addLayout(right, 1)

        self.setWindowTitle(self.title)
        self.setMinimumSize(1000, 700)
        self.reload_list(selected_name)

    @staticmethod
    def components_of(model: "ModelConfig") -> NamedComponents:
        """
        Returns the list of components the dialog edits.
        :param model: The model configuration.
        :return: The components.
        """
        raise NotImplementedError

    def type_of(self, component: dict) -> str | None:
        """
        Returns the type of a component.
        :param component: The component dictionary.
        :return: The type, such as "Constant", or None for a kind of component
        with one shape.
        """
        return None if self.tag is None else component.get(self.tag)

    def reload_list(self, selected_name: str | None = None) -> None:
        """
        Fills the list with the components and selects one.
        :param selected_name: The name of the component to select. Optional.
        :return: None
        """
        self.list.blockSignals(True)
        self.list.clear()
        for name in sorted(self.components.names, key=str.lower):
            component_type = self.type_of(self.components.config(name))
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(humanise_type(component_type) if component_type else "")
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.apply_filter(self.filter.text())

        names = self.components.names
        target = selected_name if selected_name in names else None
        if target is None and self.list.count():
            target = self.list.item(0).data(Qt.ItemDataRole.UserRole)
        self.select(target)

    def select(self, name: str | None) -> None:
        """
        Selects a component in the list and shows its form.
        :param name: The component name. None clears the form.
        :return: None
        """
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self.list.blockSignals(True)
                self.list.setCurrentItem(item)
                self.list.blockSignals(False)
                break
        self.show_component(name)

    @Slot(str)
    def apply_filter(self, text: str) -> None:
        """
        Shows only the components whose name or type contain the text.
        :param text: The text to look for.
        :return: None
        """
        text = text.strip().lower()
        for row in range(self.list.count()):
            item = self.list.item(row)
            haystack = f"{item.text()} {item.toolTip()}".lower()
            item.setHidden(bool(text) and text not in haystack)

    def has_unsaved_changes(self) -> bool:
        return self.form is not None and self.save_button.isEnabled()

    def confirm_discard(self) -> bool:
        """
        Asks whether to discard the unsaved changes of the current component.
        :return: True if there are no changes or they can be discarded.
        """
        if not self.has_unsaved_changes():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f'Discard the changes to "{self.current}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    @Slot(QListWidgetItem, QListWidgetItem)
    def on_selection_changed(self, item: QListWidgetItem, previous) -> None:
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if name == self.current:
            return
        if not self.confirm_discard():
            self.select(self.current)
            return
        self.show_component(name)

    def clear_form(self) -> None:
        if self.form is not None:
            self.form_container.removeWidget(self.form)
            # the form stays visible until it is deleted
            self.form.hide()
            self.form.deleteLater()
            self.form = None

    def show_component(self, name: str | None) -> None:
        """
        Shows the form of a component.
        :param name: The component name. None clears the form.
        :return: None
        """
        self.clear_form()
        self.current = name
        self.save_button.setEnabled(False)
        component = self.components.config(name) if name is not None else None
        has_component = component is not None
        self.clone_button.setEnabled(has_component)
        self.delete_button.setEnabled(has_component)
        if not has_component:
            self.heading.setText(f"No {self.components.kind}s")
            self.description.setText("Click Add to create one.")
            return

        component_type = self.type_of(component)
        meta = component.get("meta") or {}
        values = {k: v for k, v in component.items() if k not in ("meta", self.tag)}
        if self.single_type:
            definition = self.schema.defs[self.definition]
            self.heading.setText(name)
            self.description.setText(
                (definition.get("description") or "").split("\n\n")[0]
            )
            specs = self.schema.object_fields(definition, skip=("meta",))
        else:
            known = component_type in self.schema.types(self.definition)
            self.heading.setText(f"{name} ({humanise_type(component_type)})")
            self.description.setText(
                (self.schema.description(self.definition, component_type) or "")
                if known
                else f"The type {component_type!r} is not in the bundled pywr-next "
                + "schema"
            )
            specs = self.schema.fields(self.definition, component_type) if known else []
        described = {spec.name for spec in specs}
        unknown = {k: v for k, v in values.items() if k not in described}

        fields = {
            "General": [
                FieldConfig(
                    name="name",
                    value=name,
                    allow_empty=False,
                    validate_fun=self.check_name,
                ),
                FieldConfig(
                    name="comment",
                    value=meta.get("comment"),
                    field_type=TextWidget,
                    field_args={"multi_line": True},
                ),
            ],
        }
        if specs:
            fields["Configuration"] = field_configs(specs, values, self.model)
        if unknown:
            fields["Other values"] = field_configs(
                [FieldSpec(name=key, label=key, kind="json") for key in unknown],
                unknown,
            )
        self.form = Form(fields=fields, save_button=self.save_button, parent=self)
        self.form.load_fields()
        self.save_button.setEnabled(False)
        self.form_container.addWidget(self.form)

    def check_name(self, name: str, label: str, value: str) -> Validation:
        """
        Checks that the name is not empty and not used by another component.
        :return: The Validation instance.
        """
        if not isinstance(value, str) or not value.strip():
            return Validation("The name cannot be empty")
        if value != self.current and self.components.exists(value):
            return Validation(f"A {self.components.kind} with this name already exists")
        return Validation()

    @Slot()
    def save(self) -> dict | bool:
        """
        Validates the form and saves the component.
        :return: The new component dictionary, or False if the form does not
        validate.
        """
        if self.form is None or self.current is None:
            return False
        form_data = self.form.validate()
        if form_data is False:
            return False

        old = self.components.config(self.current)
        meta = copy.deepcopy(old.get("meta") or {})
        meta["name"] = form_data.pop("name")
        comment = form_data.pop("comment", None)
        if comment:
            meta["comment"] = comment
        else:
            meta.pop("comment", None)
        component = {"meta": meta, **form_data}
        if self.tag is not None:
            component = {"meta": meta, self.tag: self.type_of(old), **form_data}

        introduced = introduced_issues(
            self.definition,
            None if self.single_type else self.type_of(old),
            old,
            component,
        )
        if introduced:
            QMessageBox.critical(
                self,
                "Cannot save the form",
                "The schema does not accept the result:\n\n"
                + "\n".join(issue.message for issue in introduced[:5]),
            )
            return False

        self.components.update(self.current, component)
        self.after_change(f'Saved {self.components.kind} "{meta["name"]}"')
        self.reload_list(meta["name"])
        return component

    def unique_name(self, base: str) -> str:
        """
        Returns a name not used by another component.
        :param base: The preferred name.
        :return: The name, with a number appended if needed.
        """
        name, number = base, 1
        while self.components.exists(name):
            number += 1
            name = f"{base} {number}"
        return name

    def ask_type(self) -> str | None:
        """
        Asks for the type of a new component.
        :return: The type or None if cancelled.
        """
        types = [t for t in self.schema.types(self.definition) if t != "Placeholder"]
        labels = [humanise_type(t) for t in types]
        label, ok = QInputDialog.getItem(
            self, f"New {self.components.kind}", "Type", labels, 0, False
        )
        return types[labels.index(label)] if ok and label in labels else None

    def new_component(self, component_type: str | None, name: str) -> dict:
        """
        Returns a new component with the required fields left for the user to fill.
        :param component_type: The component type, None for a kind of component
        with one shape.
        :param name: The component name.
        :return: The component dictionary.
        """
        if self.tag is None:
            return {"meta": {"name": name}}
        return {"meta": {"name": name}, self.tag: component_type}

    @Slot()
    def on_add(self) -> None:
        if not self.confirm_discard():
            return
        if self.single_type:
            component_type = None
            name = self.unique_name(f"New {self.components.kind}")
        else:
            component_type = self.ask_type()
            if component_type is None:
                return
            name = self.unique_name(f"New {humanise_type(component_type).lower()}")
        self.components.add(self.new_component(component_type, name))
        self.after_change(f'Added {self.components.kind} "{name}"')
        self.reload_list(name)

    @Slot()
    def on_clone(self) -> None:
        if self.current is None or not self.confirm_discard():
            return
        component = copy.deepcopy(self.components.config(self.current))
        name = self.unique_name(f"{self.current} copy")
        component.setdefault("meta", {})["name"] = name
        self.components.add(component)
        self.after_change(f'Added {self.components.kind} "{name}"')
        self.reload_list(name)

    @Slot()
    def on_delete(self) -> None:
        if self.current is None:
            return
        name = self.current
        references = self.components.references(name)
        message = f'Delete the {self.components.kind} "{name}"?'
        if references:
            owners = sorted(
                {f"{k} {n}" for k, n in (r.owner or ("", "") for r in references)}
            )
            message += (
                f"\n\nIt is used {len(references)} times, by: "
                + ", ".join(o.strip() for o in owners if o.strip())
                + ". These references will be left unresolved."
            )
        answer = QMessageBox.question(
            self,
            f"Delete {self.components.kind}",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.components.delete(name)
        self.after_change(f'Deleted {self.components.kind} "{name}"')
        self.save_button.setEnabled(False)
        self.reload_list()

    def after_change(self, message: str) -> None:
        """
        Refreshes the main window after a change.
        :param message: The status bar message.
        :return: None
        """
        app = self.app
        if app is None:
            return
        if hasattr(app, "components_tree"):
            app.components_tree.reload()
        if hasattr(app, "schematic"):
            app.schematic.reload()
        if hasattr(app, "statusBar"):
            app.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:
        if not self.confirm_discard():
            event.ignore()
            return
        super().closeEvent(event)


class NextTablesDialog(NextComponentsDialog):
    definition = "DataTable"
    title = "Tables"

    @staticmethod
    def components_of(model: "ModelConfig") -> NamedComponents:
        return model.tables


class NextTimeSeriesDialog(NextComponentsDialog):
    definition = "TimeSeries"
    title = "Time series"

    @staticmethod
    def components_of(model: "ModelConfig") -> NamedComponents:
        return model.time_series


class NextMetricSetsDialog(NextComponentsDialog):
    definition = "MetricSet"
    title = "Metric sets"

    @staticmethod
    def components_of(model: "ModelConfig") -> NamedComponents:
        return model.metric_sets


class NextOutputsDialog(NextComponentsDialog):
    definition = "Output"
    title = "Outputs"

    @staticmethod
    def components_of(model: "ModelConfig") -> NamedComponents:
        return model.outputs


class NextParametersDialog(NextComponentsDialog):
    """
    The parameters dialog. A "Python" parameter also shows the code it calls, which
    is edited in its Python file next to the model (see python_code.py).
    """

    definition = "Parameter"
    title = "Parameters"
    code_fields = ("source", "object", "args", "kwargs", "metrics", "indices")
    """ The fields of a Python parameter that change what the checks look at """

    @staticmethod
    def components_of(model: "ModelConfig") -> NamedComponents:
        return model.parameters

    def __init__(self, *args, **kwargs):
        self.panel: PythonCodePanel | None = None
        super().__init__(*args, **kwargs)

    def form_values(self) -> dict:
        """
        Returns the current values of the fields of the form that describe the code
        of a Python parameter, without validating the form.
        :return: The values by field name.
        """
        values = {}
        if self.form is not None:
            for name in (*self.code_fields, "return_type"):
                field = self.form.find_field(name)
                if field is not None:
                    values[name] = field.value()
        return values

    def clear_form(self) -> None:
        if self.panel is not None:
            self.form_container.removeWidget(self.panel)
            self.panel.hide()
            self.panel.deleteLater()
            self.panel = None
        super().clear_form()

    def show_component(self, name: str | None) -> None:
        super().show_component(name)
        component = self.components.config(name) if name is not None else None
        if self.form is None or component is None or self.type_of(component) != "Python":
            return
        self.panel = PythonCodePanel(self.model, self.form_values, self)
        self.panel.setObjectName("python_panel")
        self.form_container.addWidget(self.panel, 2)
        for field_name in self.code_fields:
            field = self.form.find_field(field_name)
            if field is not None:
                # noinspection PyUnresolvedReferences
                field.widget.field_value_changed.connect(self.panel.schedule_check)
        # noinspection PyUnresolvedReferences
        self.panel.changed.connect(self.on_code_changed)
        self.panel.refresh()
        self.save_button.setEnabled(self.panel.dirty)

    @Slot()
    def on_code_changed(self) -> None:
        self.save_button.setEnabled(True)

    @Slot()
    def save(self) -> dict | bool:
        """
        Saves the code of a Python parameter in its file, then the parameter.
        :return: The new component dictionary, or False if the form does not
        validate or the file cannot be written.
        """
        if self.panel is not None and self.form is not None:
            if self.form.validate() is False:
                return False
            if not self.panel.save():
                return False
        return super().save()

    def new_component(self, component_type: str | None, name: str) -> dict:
        """
        Returns a new parameter. A Python parameter calls a new function of the
        Python file of the model, which is created with a few lines of code.
        """
        component = super().new_component(component_type, name)
        model_file = self.model.json_file
        if component_type == "Python" and model_file:
            file = python_code.module_file(model_file)
            function = python_code.python_identifier(name)
            component["source"] = {"type": "Path", "path": file.name}
            component["object"] = {"type": "Function", "function": function}
            try:
                text = file.read_text(encoding="utf-8") if file.is_file() else ""
                if python_code.find_object(text, "Function", function) is None:
                    code = python_code.starter_code("Function", function)
                    file.write_text(
                        python_code.splice(text, None, code)[0], encoding="utf-8"
                    )
            except OSError:
                pass
        return component


def open_local_parameters(
    model: "ModelConfig", node_name: str, parent: QWidget | None = None
) -> NextParametersDialog:
    """
    Opens the parameters dialog for the local parameters of a node.
    :param model: The model configuration.
    :param node_name: The node name.
    :param parent: The parent widget. Optional.
    :return: The dialog.
    """
    node = model.nodes.config(node_name)
    components = NamedComponents(model, "parameters", "local parameter", owner=node)
    dialog = NextParametersDialog(model=model, parent=parent, components=components)
    dialog.setWindowTitle(f"Local parameters of {node_name}")
    dialog.show()
    return dialog
