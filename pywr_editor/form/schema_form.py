import json
from typing import TYPE_CHECKING, Any, Type

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit

from pywr_editor.dialects.next.references import (
    existing_names,
    unresolved,
    value_references,
)
from pywr_editor.dialects.next.schema import FieldSpec, bundled_schema
from pywr_editor.form.field_config import FieldConfig
from pywr_editor.form.form_widget import FormWidget
from pywr_editor.form.validation import Validation
from pywr_editor.form.widgets.boolean_widget import BooleanWidget
from pywr_editor.form.widgets.float_widget import FloatWidget
from pywr_editor.form.widgets.metric_widget import MetricWidget
from pywr_editor.form.widgets.text_widget import TextWidget
from pywr_editor.model.schema_check import (
    SchemaChecker,
    SchemaIssue,
    missing_file_message,
    new_issues,
)

if TYPE_CHECKING:
    from pywr_editor.form import FormField
    from pywr_editor.model import ModelConfig

"""
 Builds form fields from the description of the properties of a pywr-next component
 (see dialects/next/schema.py). The widget of a field is chosen:
   1. by the name of the schema definition of the value, from REF_WIDGETS (for
      example a "Metric" value gets the widget that edits metrics);
   2. otherwise by the kind of value (number, enum, list of numbers...);
   3. otherwise the value is edited as JSON, so that every property can be edited
      even before it has a dedicated widget.
"""


class JsonWidget(FormWidget):
    """Edits any value as JSON text."""

    def __init__(self, name: str, value: Any, parent: "FormField"):
        super().__init__(name, value, parent)
        self.text = QPlainTextEdit()
        self.text.setObjectName(f"{name}_json")
        self.text.setMaximumHeight(120)
        if value is not None:
            self.text.setPlainText(json.dumps(value, indent=2))
        self.field_value_changed: Signal = self.text.textChanged

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text)

    def get_value(self) -> Any:
        """
        Returns the parsed value.
        :return: The value, None if the field is empty, or the text when it is not
        valid JSON (the validation then fails).
        """
        text = self.text.toPlainText().strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def validate(self, name: str, label: str, value: Any) -> Validation:
        """
        Checks that the text is valid JSON.
        :return: The Validation instance.
        """
        text = self.text.toPlainText().strip()
        if text:
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                return Validation(f"The value is not valid JSON: {error.msg}")
        return Validation()


class EnumWidget(FormWidget):
    """Picks one of the allowed strings. An optional field can be left empty."""

    def __init__(
        self,
        name: str,
        value: str | None,
        parent: "FormField",
        options: tuple[str, ...] = (),
        required: bool = False,
    ):
        super().__init__(name, value, parent)
        self.combo_box = QComboBox()
        self.combo_box.setObjectName(f"{name}_combo_box")
        if not required:
            self.combo_box.addItem("")
        self.combo_box.addItems(list(options))
        if isinstance(value, str):
            if value not in options:
                # keep a value the schema does not know, so it is not lost
                self.combo_box.addItem(value)
            self.combo_box.setCurrentText(value)
        self.field_value_changed: Signal = self.combo_box.currentTextChanged

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo_box)
        layout.addStretch()

    def get_value(self) -> str | None:
        """
        Returns the selected value.
        :return: The value or None if nothing is selected.
        """
        return self.combo_box.currentText() or None


class OptionalIntegerWidget(FormWidget):
    """An integer that can be left empty, unlike a spin box."""

    def __init__(
        self,
        name: str,
        value: int | None,
        parent: "FormField",
        min_value: int | None = None,
    ):
        super().__init__(name, value, parent)
        self.min_value = min_value
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName(f"{name}_line_edit")
        self.line_edit.setMaximumWidth(100)
        if isinstance(value, int) and not isinstance(value, bool):
            self.line_edit.setText(str(value))
        self.field_value_changed: Signal = self.line_edit.textChanged

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line_edit)
        layout.addStretch()

    def get_value(self) -> int | str | None:
        """
        Returns the integer.
        :return: The integer, None if empty, or the text if it is not an integer.
        """
        text = self.line_edit.text().strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return text

    def validate(self, name: str, label: str, value: Any) -> Validation:
        """
        Checks that the value is an integer above the minimum.
        :return: The Validation instance.
        """
        if isinstance(value, str):
            return Validation("The value must be an integer")
        if value is not None and self.min_value is not None and value < self.min_value:
            return Validation(f"The value must be at least {self.min_value}")
        return Validation()


class NumberListWidget(FormWidget):
    """A list of numbers written as comma-separated values."""

    def __init__(self, name: str, value: list | None, parent: "FormField"):
        super().__init__(name, value, parent)
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName(f"{name}_line_edit")
        if isinstance(value, list):
            self.line_edit.setText(", ".join(str(v) for v in value))
        self.field_value_changed: Signal = self.line_edit.textChanged

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line_edit)

    def get_value(self) -> list[float] | str | None:
        """
        Returns the numbers.
        :return: The list, None if empty, or the text if a value is not a number.
        """
        text = self.line_edit.text().strip()
        if not text:
            return None
        try:
            return [
                int(v) if v.strip().lstrip("-").isdigit() else float(v)
                for v in text.split(",")
            ]
        except ValueError:
            return text

    def validate(self, name: str, label: str, value: Any) -> Validation:
        """
        Checks that all the values are numbers.
        :return: The Validation instance.
        """
        if isinstance(value, str):
            return Validation("The values must be numbers separated by commas")
        return Validation()


class NamePickerWidget(FormWidget):
    """A name of another component, picked from the model or typed."""

    def __init__(
        self, name: str, value: str | None, parent: "FormField", names: list[str]
    ):
        super().__init__(name, value, parent)
        self.combo_box = QComboBox()
        self.combo_box.setObjectName(f"{name}_combo_box")
        self.combo_box.setEditable(True)
        self.combo_box.addItems([""] + names)
        self.combo_box.setCurrentText(value if isinstance(value, str) else "")
        self.field_value_changed: Signal = self.combo_box.currentTextChanged

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo_box)

    def get_value(self) -> str | None:
        """
        Returns the name.
        :return: The name or None if empty.
        """
        return self.combo_box.currentText().strip() or None


NAME_PICKERS = {"metric_set": "metric_sets", "table": "tables"}
""" The string properties naming another component, with the network list """

REF_WIDGETS: dict[str, Type[FormWidget]] = {
    "Metric": MetricWidget,
    "IndexMetric": MetricWidget,
}
""" The widget editing the values of a schema definition, by definition name """


def register_ref_widget(ref: str, widget: Type[FormWidget]) -> None:
    """
    Sets the widget used for the values of a schema definition.
    :param ref: The definition name, such as "Metric".
    :param widget: The widget class. It is created with the field name, value and
    parent field, plus a "spec" argument with the FieldSpec and a "model_config"
    argument with the model (or None).
    :return: None
    """
    REF_WIDGETS[ref] = widget


FILE_FIELDS = ("url", "path")
""" The string properties of the tables and time series that name a data file """


def schema_checker() -> SchemaChecker:
    """
    Returns the checker of the values against the bundled schema.
    :return: The checker.
    """
    return SchemaChecker(bundled_schema().defs)


def schema_validation(spec: FieldSpec, model_config: "ModelConfig | None" = None):
    """
    Builds the validation of a field, which refuses a value that the bundled schema
    rejects, and warns about a value that the schema accepts but pywr-next cannot use
    because a component or a file it names is not there.
    :param spec: The description of the property.
    :param model_config: The model, to look for the components and the folder of the
    model. Optional.
    :return: The function for the "validate_fun" key of a form field.
    """

    def validate(name: str, label: str, value: Any) -> Validation:
        # an empty value is checked by the field (it cannot be empty if it is required)
        if value is None or value == "" or spec.schema is None:
            return Validation()
        issues = schema_checker().check(spec.schema, value)
        if issues:
            return Validation(issues[0].message)
        return Validation(warning_message=_warning(spec, value, model_config))

    return validate


def _warning(spec: FieldSpec, value: Any, model_config: "ModelConfig | None") -> str | None:
    if model_config is None:
        return None
    if spec.name == "metric_set":
        # a name, or a list of names, of metric sets
        names = [value] if isinstance(value, str) else value
        references = [
            ("metric set", name)
            for name in (names if isinstance(names, list) else [])
            if isinstance(name, str)
        ]
    elif spec.kind == "string" and spec.name in NAME_PICKERS:
        references = [("table", value)] if isinstance(value, str) else []
    elif spec.kind == "string" and spec.name in FILE_FIELDS:
        return missing_file_message(value, model_config.json_file)
    elif spec.kind in ("ref", "json", "number_list") and isinstance(value, (dict, list)):
        references = value_references(value)
    else:
        return None
    missing = unresolved(references, existing_names(model_config.json))
    if not missing:
        return None
    listed = ", ".join(f'{kind} "{name}"' for kind, name in missing[:3])
    more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
    return f"The model has no {listed}{more}"


def field_config(
    spec: FieldSpec, values: dict, model_config: "ModelConfig | None" = None
) -> FieldConfig:
    """
    Builds the configuration of the form field of a property.
    :param spec: The description of the property.
    :param values: The current values of the component.
    :param model_config: The model, for the widgets that list its components.
    :return: The field configuration.
    """
    value = values.get(spec.name)
    config = FieldConfig(
        name=spec.name,
        label=spec.label,
        value=value,
        allow_empty=not spec.required,
    )
    if spec.description:
        config["help_text"] = spec.description
    config["validate_fun"] = schema_validation(spec, model_config)

    if spec.kind == "ref" and spec.ref in REF_WIDGETS:
        config["field_type"] = REF_WIDGETS[spec.ref]
        config["field_args"] = {"spec": spec, "model_config": model_config}
    elif spec.kind == "ref" and bundled_schema().types(spec.ref):
        # a choice between types, such as an initial volume that is "Absolute" or
        # "Proportional": the metric widget edits any such choice
        config["field_type"] = MetricWidget
        config["field_args"] = {"spec": spec, "model_config": model_config}
    elif spec.kind == "enum":
        config["field_type"] = EnumWidget
        config["field_args"] = {"options": spec.options, "required": spec.required}
    elif spec.kind == "number":
        config["field_type"] = FloatWidget
        if spec.minimum is not None:
            config["field_args"] = {"min_value": spec.minimum}
    elif spec.kind == "integer":
        config["field_type"] = OptionalIntegerWidget
        if spec.minimum is not None:
            config["field_args"] = {"min_value": spec.minimum}
    elif spec.kind == "boolean":
        config["field_type"] = BooleanWidget
        if spec.name not in values:
            # a switch cannot be empty: do not save an unset flag
            config["default_value"] = bool(spec.default)
    elif spec.kind == "string" and spec.name in NAME_PICKERS and model_config:
        from pywr_editor.form.widgets.metric_widget import network_names

        config["field_type"] = NamePickerWidget
        config["field_args"] = {
            "names": network_names(model_config, NAME_PICKERS[spec.name])
        }
    elif spec.kind == "string":
        config["field_type"] = TextWidget
    elif spec.kind == "number_list":
        config["field_type"] = NumberListWidget
    else:
        config["field_type"] = JsonWidget
    if spec.kind in ("ref", "json"):
        # an empty object can be meaningful, such as "spill": {} that adds a spill
        # with the default settings
        config["keep_empty"] = True
    return config


def field_configs(
    specs: list[FieldSpec], values: dict, model_config: "ModelConfig | None" = None
) -> list[FieldConfig]:
    """
    Builds the form fields of a component.
    :param specs: The descriptions of the component properties.
    :param values: The current values of the component.
    :param model_config: The model, for the widgets that list its components.
    :return: The field configurations, in the order of the descriptions.
    """
    return [field_config(spec, values, model_config) for spec in specs]


def introduced_issues(
    definition: str, type_name: str | None, old: dict | None, new: dict
) -> list[SchemaIssue]:
    """
    Checks a component that was edited in a form against the schema of its type, as
    a last check after the form accepted every field. A problem the component already
    had is not reported, so a component with a value the form does not edit can still
    be saved: only what this edit adds is.
    :param definition: The schema definition of the kind of component, such as "Node".
    :param type_name: The type of the component, None for a kind with one shape.
    :param old: The component before the edit. None for a new component.
    :param new: The component after the edit.
    :return: The problems the edit introduced, none if the type is not in the schema.
    """
    schema = bundled_schema().component_schema(definition, type_name)
    if schema is None:
        return []
    checker = schema_checker()
    before = checker.check(schema, old) if old else []
    return new_issues(before, checker.check(schema, new))
