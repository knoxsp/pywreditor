import copy
import json
import shutil

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor.dialects.next.references import (
    existing_names,
    missing_references,
    unresolved,
    value_references,
)
from pywr_editor.dialects.next.validation import (
    validate_files,
    validate_network,
)
from pywr_editor.dialogs.next_components.components_dialog import NextParametersDialog
from pywr_editor.model import ModelConfig
from pywr_editor.model.schema_check import SchemaIssue
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"
DIALOG_MODULE = "pywr_editor.dialogs.next_components.components_dialog"


@pytest.fixture
def model() -> dict:
    return {
        "metadata": {"title": "t"},
        "time": {
            "start": "2020-01-01",
            "end": "2020-01-05",
            "timestep": {"type": "Days", "days": 1},
        },
        "network": {
            "nodes": [
                {
                    "meta": {"name": "in"},
                    "type": "Input",
                    "max_flow": {"type": "Parameter", "name": "known"},
                },
                {"meta": {"name": "out"}, "type": "Output"},
            ],
            "edges": [{"from_node": "in", "to_node": "out"}],
            "parameters": [{"meta": {"name": "known"}, "type": "Constant", "value": 1}],
            "tables": [
                {
                    "meta": {"name": "tbl"},
                    "type": "Scalar",
                    "format": "CSV",
                    "lookup": {"type": "Row", "cols": 1},
                    "url": "data.csv",
                }
            ],
            "time_series": [
                {"meta": {"name": "ts"}, "type": "Pandas", "path": "series.csv"}
            ],
            "metric_sets": [{"meta": {"name": "set"}, "metrics": []}],
            "outputs": [
                {"meta": {"name": "o"}, "type": "CSV", "filename": "o.csv", "metric_set": "set"}
            ],
        },
    }


def with_input_metric(model: dict, metric: dict) -> dict:
    changed = copy.deepcopy(model)
    changed["network"]["nodes"][0]["max_flow"] = metric
    return changed


def test_a_model_with_every_reference_has_no_warning(model):
    assert missing_references(model) == []
    assert [d for d in validate_network(model) if d.severity == "warning"] == []


@pytest.mark.parametrize(
    "metric, kind, name",
    [
        ({"type": "Parameter", "name": "gone"}, "parameter", "gone"),
        ({"type": "Node", "name": "gone"}, "node", "gone"),
        ({"type": "Table", "table": "gone"}, "table", "gone"),
        ({"type": "TimeSeries", "name": "gone"}, "time series", "gone"),
    ],
)
def test_a_reference_to_a_missing_component_is_a_warning(model, metric, kind, name):
    """
    The schema accepts any name, but pywr-next cannot build the model.
    """
    diagnostics = validate_network(with_input_metric(model, metric))
    [warning] = [d for d in diagnostics if d.severity == "warning"]
    assert warning.message == (
        f'The node "in" refers to the {kind} "{name}", which does not exist'
    )
    assert warning.component == ("node", "in")
    assert warning.path[:3] == ("network", "nodes", 0)


def test_references_that_exist_are_not_reported(model):
    for metric in (
        {"type": "Node", "name": "out"},
        {"type": "Table", "table": "tbl"},
        {"type": "TimeSeries", "name": "ts"},
    ):
        assert missing_references(with_input_metric(model, metric)) == []


def test_a_missing_metric_set_of_an_output_is_reported(model):
    model["network"]["outputs"][0]["metric_set"] = "gone"
    [reference] = missing_references(model)
    assert (reference.kind, reference.name) == ("metric set", "gone")


def test_the_names_a_reference_can_use(model):
    names = existing_names(model)
    assert names["node"] == {"in", "out"}
    assert names["parameter"] == {"known"}
    assert names["table"] == {"tbl"}
    assert names["time series"] == {"ts"}
    assert names["metric set"] == {"set"}
    assert unresolved(
        [("parameter", "known"), ("parameter", "x"), ("parameter", "x"), ("local parameter", "y")],
        names,
    ) == [("parameter", "x")]


def test_references_in_a_value():
    value = {
        "type": "Parameter",
        "name": "a",
    }
    assert value_references(value) == [("parameter", "a")]
    assert value_references({"type": "Literal", "value": 1}) == []
    assert value_references("text") == []


def test_missing_data_files_are_warnings(model, tmp_path):
    model_file = tmp_path / "model.json"
    (tmp_path / "data.csv").write_text("a")
    diagnostics = validate_files(model, str(model_file))
    assert [(d.message, d.path, d.component) for d in diagnostics] == [
        (
            'The file "series.csv" does not exist',
            ("network", "time_series", 0, "path"),
            ("time series", "ts"),
        )
    ]
    (tmp_path / "series.csv").write_text("a")
    assert validate_files(model, str(model_file)) == []


def test_files_cannot_be_checked_before_the_model_is_saved(model):
    assert validate_files(model, None) == []


def test_the_dialect_validation_includes_the_files(model, tmp_path):
    file = tmp_path / "model.json"
    file.write_text(json.dumps(model))
    config = ModelConfig(str(file))
    messages = [d.message for d in config.dialect.validate_model(config)]
    assert 'The file "data.csv" does not exist' in messages
    assert 'The file "series.csv" does not exist' in messages


def test_the_other_models_have_no_missing_reference():
    """
    No false positive on the pywr-next test models.
    """
    for file in sorted(NEXT_MODELS.glob("*.json")):
        content = json.loads(file.read_text())
        if isinstance(content.get("network"), dict):
            assert missing_references(content) == [], file.name


class TestDialogRefusesWhatTheSchemaRejects:
    @pytest.fixture
    def dialog(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pywr_editor.form.form.QMessageBox.critical",
            staticmethod(lambda *args: None),
        )
        monkeypatch.setattr(
            f"{DIALOG_MODULE}.QMessageBox.question",
            staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
        )
        file = tmp_path / "model.json"
        shutil.copy(NEXT_MODELS / "time-series.json", file)
        config = ModelConfig(str(file))
        dialog = NextParametersDialog(model=config, selected_name="demand")
        qtbot.addWidget(dialog)
        return dialog

    def test_a_result_the_schema_rejects_is_not_saved(self, dialog, monkeypatch):
        """
        Tests that the dialog does not save a component when the check of the whole
        component finds a problem that this edit introduced, even if every field is
        accepted.
        """
        boxes = []
        monkeypatch.setattr(
            f"{DIALOG_MODULE}.QMessageBox.critical",
            staticmethod(lambda *args: boxes.append(args[-1])),
        )
        monkeypatch.setattr(
            f"{DIALOG_MODULE}.introduced_issues",
            lambda *args: [SchemaIssue("The value is wrong", ("value",))],
        )
        before = copy.deepcopy(dialog.components.config("demand"))
        assert dialog.save() is False
        assert boxes and "The value is wrong" in boxes[0]
        assert dialog.components.config("demand") == before

    def test_a_valid_edit_is_saved(self, dialog):
        assert dialog.save() is not False
