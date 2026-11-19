import json
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next.schema import FieldSpec, bundled_schema
from pywr_editor.dialects.next.validation import component_name
from pywr_editor.form.form_widget import FormWidget
from pywr_editor.form.validation import Validation

if TYPE_CHECKING:
    from pywr_editor.form import FormField
    from pywr_editor.model import ModelConfig

"""
 Edits a pywr-next metric: a literal value, or a reference to a parameter, a node
 attribute, a table value, a time series... The types of metric and their fields are
 read from the bundled schema ("Metric", or "IndexMetric" for index values), so the
 widget follows the pywr-next version the editor bundles. It also edits any other
 choice between types described by the schema (for example the initial volume of a
 storage, "Absolute" or "Proportional").
"""

PICKERS = {
    ("Node", "name"): "nodes",
    ("LocalParameter", "node"): "nodes",
    ("VirtualNode", "name"): "virtual_nodes",
    ("Parameter", "name"): "parameters",
    ("TimeSeries", "name"): "time_series",
    ("Table", "table"): "tables",
}
""" The fields that name a component, with the network list of the components """


def network_names(model_config: "ModelConfig | None", key: str) -> list[str]:
    """
    Returns the names of the components in a list of the network.
    :param model_config: The model configuration. Optional.
    :param key: The list, such as "parameters".
    :return: The names.
    """
    if model_config is None:
        return []
    network = model_config.json.get("network")
    items = network.get(key) if isinstance(network, dict) else None
    if not isinstance(items, list):
        return []
    return [n for n in (component_name(item) for item in items) if n is not None]


class _FieldEditor:
    """The editor of one field of a metric."""

    def __init__(self, spec: FieldSpec, value: Any, names: list[str]):
        self.spec = spec
        if spec.kind == "enum":
            self.widget = QComboBox()
            if not spec.required:
                self.widget.addItem("")
            self.widget.addItems(list(spec.options))
            if isinstance(value, str):
                if value not in spec.options:
                    self.widget.addItem(value)
                self.widget.setCurrentText(value)
            self.changed = self.widget.currentTextChanged
        elif spec.kind == "string":
            # a name, picked from the model components when there are some
            self.widget = QComboBox()
            self.widget.setEditable(True)
            self.widget.addItems([""] + names)
            self.widget.setCurrentText(value if isinstance(value, str) else "")
            self.changed = self.widget.currentTextChanged
        else:
            self.widget = QLineEdit()
            if value is not None:
                text = value if isinstance(value, str) else json.dumps(value)
                if spec.kind in ("number", "integer"):
                    text = str(value)
                self.widget.setText(text)
            self.changed = self.widget.textChanged
        self.widget.setObjectName(f"metric_{spec.name}")

    def text(self) -> str:
        if isinstance(self.widget, QComboBox):
            return self.widget.currentText().strip()
        return self.widget.text().strip()

    def value(self) -> Any:
        """
        Returns the value of the field.
        :return: The value, None when empty, or the text when it cannot be read.
        """
        text = self.text()
        if not text:
            return None
        if self.spec.kind == "number":
            try:
                number = float(text)
                return (
                    int(number) if number.is_integer() and "." not in text else number
                )
            except ValueError:
                return text
        if self.spec.kind == "integer":
            try:
                return int(text)
            except ValueError:
                return text
        if self.spec.kind in ("string", "enum"):
            return text
        # a nested value. A plain string (such as a column name) is not JSON
        if text[0] in '[{"':
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return text

    def error(self) -> str | None:
        """
        Checks the value of the field.
        :return: The error message or None if the value is valid.
        """
        value = self.value()
        label = self.spec.label.lower()
        if value is None:
            return f"The {label} is required" if self.spec.required else None
        if self.spec.kind in ("number", "integer") and isinstance(value, str):
            kind = "a number" if self.spec.kind == "number" else "an integer"
            return f"The {label} must be {kind}"
        if self.spec.kind in ("ref", "json") and self.text()[0] in "[{":
            try:
                json.loads(self.text())
            except json.JSONDecodeError:
                return f"The {label} is not valid JSON"
        return None


class MetricWidget(FormWidget):
    value_changed = Signal()

    def __init__(
        self,
        name: str,
        value: dict | None,
        parent: "FormField",
        spec: FieldSpec | None = None,
        model_config: "ModelConfig | None" = None,
    ):
        """
        Initialises the widget.
        :param name: The field name.
        :param value: The metric, such as {"type": "Literal", "value": 1}.
        :param parent: The parent field.
        :param spec: The description of the field. Its "ref" is the schema
        definition of the metric ("Metric" by default).
        :param model_config: The model, to list the components a metric can name.
        """
        super().__init__(name, value, parent)
        self.field_value_changed: Signal = self.value_changed
        self.definition = spec.ref if spec is not None and spec.ref else "Metric"
        self.model_config = model_config
        self.schema = bundled_schema()
        self.original = value if isinstance(value, dict) else None
        self.editors: dict[str, _FieldEditor] = {}

        self.type_combo = QComboBox()
        self.type_combo.setObjectName(f"{name}_metric_type")
        self.type_combo.addItem("", None)
        for type_name in self.schema.types(self.definition):
            self.type_combo.addItem(self._type_label(type_name), type_name)

        self.fields_widget = QWidget()
        self.fields_layout = QFormLayout(self.fields_widget)
        self.fields_layout.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(self.type_combo)
        top.addStretch()
        layout.addLayout(top)
        layout.addWidget(self.fields_widget)

        current = self.original.get("type") if self.original else None
        if current is not None and self.type_combo.findData(current) == -1:
            # keep a type the schema does not know, so it is not lost
            self.type_combo.addItem(str(current), current)
        self.type_combo.setCurrentIndex(max(self.type_combo.findData(current), 0))
        self._show_fields()
        # noinspection PyUnresolvedReferences
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

    @staticmethod
    def _type_label(type_name: str) -> str:
        from pywr_editor.dialects.next.model import humanise_type

        return humanise_type(type_name)

    @property
    def metric_type(self) -> str | None:
        """
        The selected type of metric.
        :return: The type or None if the metric is not set.
        """
        return self.type_combo.currentData()

    def _on_type_changed(self) -> None:
        self._show_fields()
        self.value_changed.emit()

    def _show_fields(self) -> None:
        while self.fields_layout.rowCount():
            self.fields_layout.removeRow(0)
        self.editors = {}
        metric_type = self.metric_type
        if metric_type is None or metric_type not in self.schema.types(self.definition):
            return
        # the values of the metric are kept only when its type is unchanged
        values = (
            self.original
            if self.original and self.original.get("type") == metric_type
            else {}
        )
        for spec in self.schema.fields(self.definition, metric_type):
            key = PICKERS.get((metric_type, spec.name))
            names = network_names(self.model_config, key) if key else []
            editor = _FieldEditor(spec, values.get(spec.name), names)
            editor.changed.connect(lambda *_: self.value_changed.emit())
            self.editors[spec.name] = editor
            label = QLabel(spec.label)
            if spec.description:
                label.setToolTip(spec.description)
            self.fields_layout.addRow(label, editor.widget)

    def get_value(self) -> dict | None:
        """
        Returns the metric.
        :return: The metric dictionary, or None if no type is selected.
        """
        metric_type = self.metric_type
        if metric_type is None:
            return None
        if not self.editors and self.original and self.original["type"] == metric_type:
            # a type the schema does not describe is returned as it was
            return self.original
        metric = {"type": metric_type}
        for key, editor in self.editors.items():
            value = editor.value()
            if value is not None:
                metric[key] = value
        # keep the keys of the original metric the schema does not describe
        if self.original and self.original.get("type") == metric_type:
            for key, value in self.original.items():
                if key not in metric and key not in self.editors:
                    metric[key] = value
        return metric

    def validate(self, name: str, label: str, value: Any) -> Validation:
        """
        Checks the fields of the metric.
        :return: The Validation instance.
        """
        for editor in self.editors.values():
            error = editor.error()
            if error is not None:
                return Validation(error)
        return Validation()
