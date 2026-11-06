import pytest

from pywr_editor.dialects.next.schema import FieldSpec
from pywr_editor.form import Form
from pywr_editor.form.schema_form import field_configs
from pywr_editor.form.widgets.metric_widget import MetricWidget
from pywr_editor.model import ModelConfig
from tests.utils import model_path


@pytest.fixture(autouse=True)
def no_error_box(monkeypatch):
    # a form that does not validate shows a modal message box
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical", staticmethod(lambda *args: None)
    )


@pytest.fixture
def model() -> ModelConfig:
    return ModelConfig(str(model_path() / "pywr_next" / "time-series.json"))


def make(qtbot, value, model=None, ref="Metric") -> tuple[Form, MetricWidget]:
    spec = FieldSpec("max_flow", "Max flow", "ref", ref=ref)
    form = Form({"Fields": field_configs([spec], {"max_flow": value}, model)})
    qtbot.addWidget(form)
    form.load_fields()
    widget = form.find_field("max_flow").widget
    assert isinstance(widget, MetricWidget)
    return form, widget


def set_type(widget: MetricWidget, metric_type: str) -> None:
    widget.type_combo.setCurrentIndex(widget.type_combo.findData(metric_type))


def test_literal(qtbot):
    form, widget = make(qtbot, {"type": "Literal", "value": 10.5})
    assert widget.metric_type == "Literal"
    assert form.validate() == {"max_flow": {"type": "Literal", "value": 10.5}}
    widget.editors["value"].widget.setText("abc")
    assert form.validate() is False


def test_empty(qtbot):
    form, widget = make(qtbot, None)
    assert widget.metric_type is None
    assert form.validate() == {}


def test_pickers_list_model_components(qtbot, model):
    """
    Tests that the names of the model components are offered.
    """
    _, widget = make(qtbot, {"type": "Parameter", "name": "demand"}, model)
    combo = widget.editors["name"].widget
    names = [combo.itemText(i) for i in range(combo.count())]
    assert "demand" in names and "factored_flow" in names

    set_type(widget, "Node")
    combo = widget.editors["name"].widget
    names = [combo.itemText(i) for i in range(combo.count())]
    assert "input1" in names and "output1" in names
    attributes = widget.editors["attribute"].widget
    assert "Outflow" in [attributes.itemText(i) for i in range(attributes.count())]


def test_change_type(qtbot, model):
    """
    Tests that the fields follow the type of metric.
    """
    form, widget = make(qtbot, {"type": "Literal", "value": 1}, model)
    set_type(widget, "TimeSeries")
    assert set(widget.editors) == {"name", "columns"}
    # the name is required
    assert form.validate() is False
    widget.editors["name"].widget.setCurrentText("inflow")
    widget.editors["columns"].widget.setText('{"type": "Column", "name": "a"}')
    assert form.validate() == {
        "max_flow": {
            "type": "TimeSeries",
            "name": "inflow",
            "columns": {"type": "Column", "name": "a"},
        }
    }
    widget.editors["columns"].widget.setText("{bad")
    assert form.validate() is False


def test_optional_fields_left_out(qtbot):
    form, widget = make(qtbot, {"type": "Parameter", "name": "p", "key": "a"})
    widget.editors["key"].widget.setCurrentText("")
    assert form.validate() == {"max_flow": {"type": "Parameter", "name": "p"}}


def test_table_index_is_a_string(qtbot):
    """
    Tests that a table column is kept as a string, even when it looks like a number.
    """
    value = {"type": "Table", "table": "t", "column": "2020", "row": ["a", "b"]}
    form, _ = make(qtbot, value)
    assert form.validate() == {"max_flow": value}


def test_index_metric(qtbot):
    form, widget = make(qtbot, {"type": "Constant", "value": 2}, ref="IndexMetric")
    assert widget.type_combo.findData("Literal") == -1
    widget.editors["value"].widget.setText("2.5")
    assert form.validate() is False


def test_unknown_keys_and_types_are_kept(qtbot):
    """
    Tests that what the bundled schema does not describe is not lost.
    """
    value = {"type": "Literal", "value": 1, "future_option": True}
    form, _ = make(qtbot, value)
    assert form.validate() == {"max_flow": value}

    value = {"type": "FutureMetric", "anything": [1]}
    form, widget = make(qtbot, value)
    assert widget.metric_type == "FutureMetric"
    assert form.validate() == {"max_flow": value}
