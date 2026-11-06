import json

import pytest

from pywr_editor.dialects.next.schema import FieldSpec, NextSchema, bundled_schema
from pywr_editor.form import Form
from pywr_editor.form.schema_form import (
    EnumWidget,
    JsonWidget,
    NumberListWidget,
    OptionalIntegerWidget,
    field_configs,
)
from tests.utils import model_path

KINDS = {
    "Node": "nodes",
    "Parameter": "parameters",
    "VirtualNode": "virtual_nodes",
    "Output": "outputs",
    "DataTable": "tables",
    "TimeSeries": "time_series",
}
""" The schema definitions of the kinds of components, with their network list """


@pytest.fixture(autouse=True)
def no_error_box(monkeypatch):
    """
    A form that does not validate shows a modal message box, which would block the
    test.
    """
    messages = []
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical",
        staticmethod(lambda *args: messages.append(args[-1])),
    )
    return messages


def make_form(qtbot, definition: str, type_name: str, values: dict) -> Form:
    specs = bundled_schema().fields(definition, type_name)
    form = Form({"Fields": field_configs(specs, values)})
    qtbot.addWidget(form)
    form.load_fields()
    return form


def components() -> list:
    """
    The components of the pywr-next test models, with their kind.
    """
    items = []
    for file in sorted((model_path() / "pywr_next").glob("*.json")):
        network = json.loads(file.read_text()).get("network")
        if not isinstance(network, dict):
            continue
        for definition, key in KINDS.items():
            for i, component in enumerate(network.get(key) or []):
                items.append(
                    pytest.param(definition, component, id=f"{file.stem}-{key}-{i}")
                )
    return items


@pytest.mark.parametrize(
    "definition, type_name",
    [(d, t) for d in KINDS for t in bundled_schema().types(d)],
)
def test_every_type_has_a_form(qtbot, definition, type_name):
    """
    Tests that a form can be generated for every type of component in the schema.
    """
    if not bundled_schema().fields(definition, type_name):
        pytest.skip("The type has no fields")
    form = make_form(qtbot, definition, type_name, {})
    assert form.loaded_


@pytest.mark.parametrize("definition, component", components())
def test_round_trip(qtbot, definition, component):
    """
    Tests that the form of each component of the pywr-next test models returns the
    component unchanged.
    """
    schema = bundled_schema()
    tag = schema.tag_key(definition)
    values = {k: v for k, v in component.items() if k not in ("meta", tag)}
    form = make_form(qtbot, definition, component[tag], values)
    assert form.validate() == values


class TestSchema:
    def test_tag_keys(self):
        schema = bundled_schema()
        assert schema.tag_key("Node") == "type"
        assert schema.tag_key("DataTable") == "format"
        assert "Reservoir" in schema.types("Node")
        assert "CSV" in schema.types("Output")

    def test_reservoir_fields(self):
        """
        Tests the description of the fields of a node.
        """
        fields = {f.name: f for f in bundled_schema().fields("Node", "Reservoir")}
        assert "type" not in fields and "meta" not in fields
        assert fields["max_volume"].kind == "ref"
        assert fields["max_volume"].ref == "Metric"
        assert fields["max_volume"].required is False
        assert fields["initial_volume"].required is True
        assert fields["outflow_node_type"].kind == "enum"
        assert fields["outflow_node_type"].options == ("OutputNode", "LinkNode")
        # the required fields come first
        names = list(fields)
        assert names.index("initial_volume") < names.index("max_volume")

    def test_field_kinds(self):
        """
        Tests how property schemas are described.
        """
        schema = NextSchema({"$defs": {"Colour": {"enum": ["red", "blue"]}}})
        spec = schema.field_spec
        assert spec("a", {"type": ["number", "null"]}, True).kind == "number"
        assert spec("a", {"type": ["number", "null"]}, True).required is False
        assert spec("a", {"type": "integer", "minimum": 1}, True).minimum == 1
        assert spec(
            "a", {"type": "array", "items": {"type": "number"}}, False
        ).kind == ("number_list")
        nullable_enum = {"anyOf": [{"$ref": "#/$defs/Colour"}, {"type": "null"}]}
        assert spec("colour", nullable_enum, False).options == ("red", "blue")
        assert spec("a", {"type": "object"}, False).kind == "json"
        assert spec("max_flow", {}, False).label == "Max flow"


class TestWidgets:
    @staticmethod
    def form(qtbot, spec: FieldSpec, values: dict) -> Form:
        form = Form({"Fields": field_configs([spec], values)})
        qtbot.addWidget(form)
        form.load_fields()
        return form

    def test_json(self, qtbot):
        form = self.form(qtbot, FieldSpec("data", "Data", "json"), {"data": {"a": 1}})
        widget: JsonWidget = form.find_field("data").widget
        assert form.validate() == {"data": {"a": 1}}
        widget.text.setPlainText("{not json")
        assert form.validate() is False
        widget.text.setPlainText("")
        assert form.validate() == {}

    def test_enum(self, qtbot):
        spec = FieldSpec("colour", "Colour", "enum", options=("red", "blue"))
        form = self.form(qtbot, spec, {})
        widget: EnumWidget = form.find_field("colour").widget
        assert form.validate() == {}
        widget.combo_box.setCurrentText("blue")
        assert form.validate() == {"colour": "blue"}

    def test_required_enum(self, qtbot):
        spec = FieldSpec("colour", "Colour", "enum", required=True, options=("red",))
        assert self.form(qtbot, spec, {}).validate() == {"colour": "red"}

    def test_integer(self, qtbot):
        spec = FieldSpec("days", "Days", "integer", minimum=1)
        form = self.form(qtbot, spec, {})
        widget: OptionalIntegerWidget = form.find_field("days").widget
        assert form.validate() == {}
        widget.line_edit.setText("0")
        assert form.validate() is False
        widget.line_edit.setText("x")
        assert form.validate() is False
        widget.line_edit.setText("3")
        assert form.validate() == {"days": 3}

    def test_number_list(self, qtbot):
        form = self.form(qtbot, FieldSpec("v", "V", "number_list"), {"v": [1, 2.5]})
        widget: NumberListWidget = form.find_field("v").widget
        assert widget.line_edit.text() == "1, 2.5"
        assert form.validate() == {"v": [1, 2.5]}
        widget.line_edit.setText("1, a")
        assert form.validate() is False

    def test_unset_boolean_is_not_saved(self, qtbot):
        spec = FieldSpec("flag", "Flag", "boolean")
        assert self.form(qtbot, spec, {}).validate() == {}
        assert self.form(qtbot, spec, {"flag": False}).validate() == {"flag": False}
