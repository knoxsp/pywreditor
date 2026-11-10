import pytest
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from pywr_editor.dialects.v1.schema_check import check_component
from pywr_editor.dialogs import (
    NodeDialog,
    ParametersDialog,
    ScenariosDialog,
    TablesDialog,
)
from pywr_editor.form import FieldConfig, Form, FormField, TextWidget
from pywr_editor.model import ModelConfig
from tests.utils import resolve_model_path


def messages(issues) -> list[str]:
    return [issue.message for issue in issues]


class TestCheckComponent:
    def test_what_the_schema_rejects_is_an_error(self):
        node = {"name": "n", "type": "output", "position": {"schematic": "bad"}}
        errors, warnings = check_component("node", None, node)
        assert messages(errors) == ['"schematic" must be a list']
        assert errors[0].path == ("position", "schematic")

    def test_a_required_property_is_named(self):
        errors, _ = check_component("scenario", None, {"name": "s"})
        assert messages(errors) == ['"size" is required']
        errors, _ = check_component("scenario", None, {"name": "s", "size": -1})
        assert messages(errors) == ['"size" must be at least 0']

    def test_only_what_the_edit_introduced_is_reported(self):
        old = {"name": "n", "type": "output", "position": {"schematic": "bad"}}
        new = {**old, "comment": "a comment"}
        assert check_component("node", old, new) == ([], [])
        valid = {"name": "n", "type": "output"}
        errors, _ = check_component("node", valid, {**valid, "tags": "bad"})
        assert messages(errors) == ['"tags" must be an object']

    def test_a_problem_only_the_strict_schema_finds_is_a_warning(self):
        """
        The standard schema reads a core node that does not match its type as a custom
        node, so it cannot be sure that the component is wrong.
        """
        node = {"name": "n", "type": "output", "max_flow": [1, 2]}
        errors, warnings = check_component("node", None, node)
        assert errors == []
        assert [w.path for w in warnings] == [("max_flow",)]

    def test_a_custom_node_is_not_reported(self):
        node = {"name": "n", "type": "MyOwnNode", "anything": [1, 2]}
        assert check_component("node", None, node) == ([], [])

    def test_a_warning_is_not_repeated_for_an_error(self):
        node = {"name": "n", "type": "link", "position": {"schematic": "bad"}}
        errors, warnings = check_component("node", None, node)
        assert errors and [w.path for w in warnings if w.path == errors[0].path] == []

    def test_a_component_without_a_type_is_not_checked(self):
        assert check_component("node", None, {"name": "n"}) == ([], [])
        assert check_component("parameter", None, {"value": "abc"}) == ([], [])

    def test_a_valid_parameter_and_table(self):
        assert check_component("parameter", None, {"type": "constant", "value": 3}) == ([], [])
        errors, warnings = check_component(
            "parameter", None, {"type": "constant", "value": "abc"}
        )
        assert errors == [] and messages(warnings) == ['"value" must be a number']


@pytest.fixture(autouse=True)
def boxes(monkeypatch):
    shown = []
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical",
        staticmethod(lambda *args: shown.append(args[-1])),
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a: QMessageBox.StandardButton.Yes)
    )
    return shown


class SchemaForm(Form):
    """A form that edits a component the schema describes."""

    def __init__(self, kind: str, component, values: dict, parent=None):
        self.schema_kind = kind
        self.component = component
        fields = [FieldConfig(name=k, label=k, value=v, field_type=TextWidget) for k, v in values.items()]
        super().__init__(fields={"F": fields}, save_button=QPushButton(), parent=parent)
        self.load_fields()

    def schema_component(self, form_data):
        return None, self.component(form_data)


def field(form: Form, name: str) -> FormField:
    return next(f for f in form.findChildren(FormField) if f.objectName() == name)


def test_an_error_stops_the_form_and_is_shown_under_the_field(qtbot, boxes):
    form = SchemaForm(
        "scenario",
        lambda data: {"name": data["name"], "size": int(data["size"])},
        {"name": "s", "size": "-1"},
    )
    qtbot.addWidget(form)
    form.save_button.setEnabled(True)  # as after a change
    assert form.validate() is False
    assert field(form, "size").message.property("message_type") == "error"
    assert field(form, "size").message.text() == '"size" must be at least 0'
    assert boxes and "The schema does not accept the values" in boxes[0]
    # the form was not saved: the save button is still enabled
    assert form.save_button.isEnabled() is True


def test_a_warning_is_shown_and_the_form_is_saved(qtbot, boxes):
    form = SchemaForm(
        "node",
        lambda data: {"name": data["name"], "type": "output", "max_flow": [1, 2]},
        {"name": "n", "max_flow": "x"},
    )
    qtbot.addWidget(form)
    assert form.validate() == {"name": "n", "max_flow": "x"}
    assert field(form, "max_flow").message.property("message_type") == "warning"
    assert boxes == []


def test_a_form_without_a_schema_kind_is_not_checked(qtbot):
    form = Form(fields={"F": [FieldConfig(name="a", label="a", value="x", field_type=TextWidget)]}, save_button=QPushButton())
    qtbot.addWidget(form)
    form.load_fields()
    assert form.schema_kind is None
    assert form.validate() == {"a": "x"}


def has_schema_box(boxes) -> bool:
    return any("The schema does not accept" in str(box) for box in boxes)


def test_a_node_saved_without_changes(qtbot, boxes):
    dialog = NodeDialog(
        model_config=ModelConfig(resolve_model_path("model_1.json")), node_name="Reservoir"
    )
    qtbot.addWidget(dialog)
    assert dialog.form.schema_kind == "node"
    assert dialog.form.validate() is not False
    assert not has_schema_box(boxes)
    # the stored node keeps its position and the schema is checked with it
    old, new = dialog.form.schema_component(dialog.form.validate())
    assert new["type"] == "storage" or new["type"] == dialog.form.node_obj.key
    assert old["name"] == "Reservoir"


def test_a_parameter_saved_without_changes(qtbot, boxes):
    dialog = ParametersDialog(ModelConfig(resolve_model_path("model_1.json")), "param1")
    qtbot.addWidget(dialog)
    form = dialog.pages.currentWidget().form
    assert form.schema_kind == "parameter"
    data = form.validate()
    assert data is not False
    old, new = form.schema_component(data)
    assert "name" not in new and old is not None
    assert not has_schema_box(boxes)


def test_a_table_saved_without_changes(qtbot, boxes):
    model = ModelConfig(resolve_model_path("model_dialog_parameter_line_edit_widget.json"))
    dialog = TablesDialog(model, selected_name="tableA")
    qtbot.addWidget(dialog)
    form = dialog.pages.currentWidget().form
    assert form.schema_kind == "table"
    assert form.validate() is not False
    assert not has_schema_box(boxes)


def test_a_scenario_keeps_its_name_in_the_component(qtbot, boxes):
    model = ModelConfig(resolve_model_path("model_1.json"))
    assert model.scenarios.names, "the model has no scenario"
    name = model.scenarios.names[0]
    dialog = ScenariosDialog(model, selected_name=name)
    qtbot.addWidget(dialog)
    form = dialog.pages.currentWidget().form
    assert form.schema_kind == "scenario"
    data = form.validate()
    assert data is not False
    old, new = form.schema_component(data)
    assert new["name"] == name and "options" not in new
    assert not has_schema_box(boxes)
