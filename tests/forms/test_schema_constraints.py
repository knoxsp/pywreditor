import json
from typing import Any

import pytest

from pywr_editor.dialects.next.schema import FieldSpec, bundled_schema
from pywr_editor.form import Form, FormField
from pywr_editor.form.schema_form import (
    field_configs,
    introduced_issues,
    schema_validation,
)
from pywr_editor.model import ModelConfig

KINDS = ("Node", "Parameter", "VirtualNode", "Output", "DataTable", "TimeSeries")


@pytest.fixture(autouse=True)
def no_error_box(monkeypatch):
    """A form that does not validate shows a modal message box."""
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical", staticmethod(lambda *args: None)
    )


def constrained_specs() -> list:
    """
    The properties of the components in the schema with a constraint that the forms
    must enforce, with the keyword and a value that breaks it and one that does not.
    """
    schema = bundled_schema()
    cases = []
    for definition in KINDS:
        for type_name in schema.types(definition):
            for spec in schema.fields(definition, type_name):
                resolved = schema.resolve(spec.schema) if spec.schema else {}
                name = f"{definition}.{type_name}.{spec.name}"
                valid_type = resolved.get("type")
                if "minimum" in resolved:
                    cases.append((name, spec, "minimum", resolved["minimum"] - 1, resolved["minimum"]))
                if "exclusiveMinimum" in resolved:
                    cases.append((name, spec, "exclusiveMinimum", resolved["exclusiveMinimum"], resolved["exclusiveMinimum"] + 1))
                if "maximum" in resolved:
                    cases.append((name, spec, "maximum", resolved["maximum"] + 1, resolved["maximum"]))
                if "exclusiveMaximum" in resolved:
                    cases.append((name, spec, "exclusiveMaximum", resolved["exclusiveMaximum"], resolved["exclusiveMaximum"] - 1))
                if "minItems" in resolved:
                    n = resolved["minItems"]
                    cases.append((name, spec, "minItems", [0] * (n - 1), None))
                if "maxItems" in resolved:
                    n = resolved["maxItems"]
                    cases.append((name, spec, "maxItems", [0] * (n + 1), None))
                if isinstance(resolved.get("enum"), list) and resolved["enum"]:
                    cases.append((name, spec, "enum", "__not_an_option__", resolved["enum"][0]))
                if spec.kind == "enum":
                    cases.append((name, spec, "enum", "__not_an_option__", spec.options[0]))
                wrong = {
                    "array": "text", "object": "text", "string": 5, "number": "text",
                    "integer": "text", "boolean": "text",
                }
                is_enum = "enum" in resolved or spec.kind == "enum"
                if isinstance(valid_type, str) and valid_type in wrong and not is_enum:
                    good = {"array": [], "object": None, "string": "a", "number": 1, "integer": 1, "boolean": True}[valid_type]
                    # a list that must have items is not valid when empty
                    if valid_type == "array" and "minItems" in resolved:
                        good = None
                    cases.append((name, spec, "type", wrong[valid_type], good))
    return [pytest.param(spec, kw, bad, good, id=f"{name}-{kw}") for name, spec, kw, bad, good in cases]


CASES = constrained_specs()


def test_the_schema_has_the_constraints_the_forms_are_tested_for():
    """
    Guards the generated cases: if a new pywr-next schema stops using one of these
    keywords on a form field, or starts using another one, this is noticed.
    """
    keywords = {case.values[1] for case in CASES}
    assert {"type", "enum", "minimum", "maximum", "minItems", "maxItems"} <= keywords
    assert keywords <= {
        "type", "enum", "minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum",
        "minItems", "maxItems",
    }


@pytest.mark.parametrize("spec, keyword, bad, good", CASES)
def test_a_value_that_breaks_the_schema_is_refused(spec, keyword, bad, good):
    """
    Tests that the validation of every constrained field refuses a value that breaks
    the constraint, with a message that says what is wrong, and accepts one that does
    not.
    """
    validate = schema_validation(spec)
    refused = validate(spec.name, spec.label, bad)
    assert refused.validation is False, f"{bad!r} was accepted"
    assert refused.error_message and "{" not in refused.error_message
    if good is not None:  # (a value of a type with required properties is not tried)
        assert validate(spec.name, spec.label, good).validation is True


def make_form(qtbot, definition: str, type_name: str, values: dict, model=None) -> Form:
    specs = bundled_schema().fields(definition, type_name)
    form = Form({"Fields": field_configs(specs, values, model)})
    qtbot.addWidget(form)
    form.load_fields()
    return form


def field_message(form: Form, name: str) -> tuple[str | None, str]:
    field = next(f for f in form.findChildren(FormField) if f.objectName() == name)
    return field.message.property("message_type"), field.message.text()


def test_a_number_below_the_minimum_stops_the_form(qtbot):
    values = {"delay": 3, "initial_value": 0, "metric": {"type": "Node", "name": "in"}}
    form = make_form(qtbot, "Parameter", "Delay", values)
    assert form.validate() is not False
    field = next(f for f in form.findChildren(FormField) if f.objectName() == "delay")
    field.widget.line_edit.setText("0")
    assert form.validate() is False
    assert field_message(form, "delay") == ("error", "The value must be at least 1")


def test_a_json_value_of_the_wrong_type_stops_the_form(qtbot):
    form = make_form(qtbot, "Node", "Link", {})
    field = next(f for f in form.findChildren(FormField) if f.objectName() == "parameters")
    field.widget.text.setPlainText('"abc"')
    assert form.validate() is False
    assert field_message(form, "parameters") == ("error", "The value must be a list")


def test_a_list_of_the_wrong_size_stops_the_form(qtbot):
    values = {"threshold": {"type": "Literal", "value": 1}, "predicate": "LT"}
    form = make_form(qtbot, "Parameter", "Threshold", values)
    field = next(f for f in form.findChildren(FormField) if f.objectName() == "returned_metrics")
    field.widget.text.setPlainText("[1, 2, 3]")
    assert form.validate() is False
    assert field_message(form, "returned_metrics")[1] == "The list must have at most 2 items"


@pytest.fixture
def model(tmp_path) -> ModelConfig:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    content = {
        "metadata": {"title": "t"},
        "time": {"start": "2020-01-01", "end": "2020-01-05", "timestep": {"type": "Days", "days": 1}},
        "network": {
            "nodes": [{"meta": {"name": "in"}, "type": "Input"}],
            "parameters": [{"meta": {"name": "known"}, "type": "Constant", "value": 1}],
            "tables": [{"meta": {"name": "tbl"}, "format": "CSV", "url": "data.csv"}],
            "metric_sets": [{"meta": {"name": "set"}, "metrics": []}],
        },
    }
    file = tmp_path / "model.json"
    file.write_text(json.dumps(content))
    config = ModelConfig(str(file))
    assert config.load_error is None
    return config


def test_a_reference_to_a_missing_component_is_a_warning(qtbot, model):
    """
    The schema accepts any name, but the model cannot be built: the form saves, and
    says so under the field.
    """
    values = {"max_flow": {"type": "Parameter", "name": "missing"}}
    form = make_form(qtbot, "Node", "Input", values, model)
    assert form.validate() == values
    kind, text = field_message(form, "max_flow")
    assert kind == "warning"
    assert text == 'The model has no parameter "missing"'


def test_a_reference_to_a_component_that_exists_has_no_warning(qtbot, model):
    values = {"max_flow": {"type": "Parameter", "name": "known"}}
    form = make_form(qtbot, "Node", "Input", values, model)
    assert form.validate() == values
    assert field_message(form, "max_flow") == (None, "")


def test_a_node_reference_can_name_a_node_and_a_missing_table_warns(qtbot, model):
    node = {"max_flow": {"type": "Node", "name": "in"}}
    assert make_form(qtbot, "Node", "Input", node, model).validate() == node
    table = {"max_flow": {"type": "Table", "table": "nope", "row": "a"}}
    form = make_form(qtbot, "Node", "Input", table, model)
    assert form.validate() == table
    assert field_message(form, "max_flow") == ("warning", 'The model has no table "nope"')


def test_a_missing_metric_set_is_a_warning(qtbot, model):
    form = make_form(qtbot, "Output", "CSV", {"filename": "a.csv", "metric_set": "nope"}, model)
    assert form.validate() is not False
    assert field_message(form, "metric_set") == ("warning", 'The model has no metric set "nope"')
    form = make_form(qtbot, "Output", "CSV", {"filename": "a.csv", "metric_set": "set"}, model)
    assert form.validate() is not False
    assert field_message(form, "metric_set") == (None, "")


def test_a_missing_data_file_is_a_warning(qtbot, model):
    base = {"type": "Scalar", "lookup": {"type": "Row", "cols": 1}}
    values = {**base, "url": "other.csv"}
    form = make_form(qtbot, "DataTable", "CSV", values, model)
    assert form.validate() == values
    assert field_message(form, "url") == ("warning", 'The file "other.csv" does not exist')
    values = {**base, "url": "data.csv"}
    form = make_form(qtbot, "DataTable", "CSV", values, model)
    assert form.validate() == values
    assert field_message(form, "url") == (None, "")


def test_an_error_replaces_a_warning(qtbot, model):
    values = {"delay": 3, "initial_value": 0, "metric": {"type": "Parameter", "name": "missing"}}
    form = make_form(qtbot, "Parameter", "Delay", values, model)
    assert form.validate() is not False
    assert field_message(form, "metric")[0] == "warning"
    field = next(f for f in form.findChildren(FormField) if f.objectName() == "delay")
    field.widget.line_edit.setText("0")
    assert form.validate() is False
    assert field_message(form, "delay")[0] == "error"


class TestIntroducedIssues:
    def test_a_problem_added_by_the_edit_is_reported(self):
        old = {"meta": {"name": "a"}, "type": "Link"}
        new = {**old, "not_a_property": 1}
        issues = introduced_issues("Node", "Link", old, new)
        assert len(issues) == 1

    def test_a_problem_the_component_already_had_is_not_reported(self):
        old = {"meta": {"name": "a"}, "type": "Link", "not_a_property": 1}
        new = {**old, "another": 2}
        assert introduced_issues("Node", "Link", old, old) == []
        # a second unexpected property is a new problem, the first one is not
        assert [i.message for i in introduced_issues("Node", "Link", old, new)] == [
            '"another" is not allowed here'
        ]

    def test_a_new_component_is_checked_completely(self):
        new = {"meta": {"name": "a"}, "type": "Link", "not_a_property": 1}
        assert len(introduced_issues("Node", "Link", None, new)) == 1

    def test_a_valid_component_has_no_issue(self):
        component = {"meta": {"name": "a"}, "type": "Link"}
        assert introduced_issues("Node", "Link", component, component) == []

    def test_an_unknown_type_is_not_checked(self):
        component = {"meta": {"name": "a"}, "type": "FutureNode", "x": 1}
        assert introduced_issues("Node", "FutureNode", None, component) == []
