import json
import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from pywr_editor.dialects.next import results
from pywr_editor.model.results import ResultsRun, list_runs

WIDE = """\
node,in,out,in,out,in,out,in,out
attribute,Outflow,Inflow,Outflow,Inflow,Outflow,Inflow,Outflow,Inflow
simulation_id,0,0,1,1,2,2,3,3
label,dry-0,dry-0,dry-1,dry-1,wet-0,wet-0,wet-1,wet-1
2020-01-01T00:00:00,3.00,3.00,1.00,1.00,2.50,2.50,4.00,4.00
2020-01-02T00:00:00,3.00,3.00,2.00,2.00,2.50,2.50,4.00,4.00
2020-01-03T00:00:00,3.00,3.00,3.00,3.00,2.50,2.50,4.00,4.00
"""

DOMAIN = {
    "groups": [
        {"name": "Climate", "size": 2, "labels": ["dry", "wet"]},
        {"name": "Demand", "size": 2},
    ]
}

MODEL = {
    "metadata": {"title": "t"},
    "time": {"start": "2020-01-01", "end": "2020-01-03", "timestep": {"type": "Days", "days": 1}},
    "scenarios": DOMAIN,
    "network": {
        "nodes": [
            {"type": "Input", "meta": {"name": "in"}, "max_flow": {"type": "Literal", "value": 3}},
            {
                "type": "Output",
                "meta": {"name": "out"},
                "max_flow": {"type": "Literal", "value": 5},
                "cost": {"type": "Literal", "value": -10},
            },
        ],
        "edges": [{"from_node": "in", "to_node": "out"}],
    },
}


def test_adds_the_results_without_changing_the_model():
    before = json.loads(json.dumps(MODEL))
    result = results.with_editor_results(MODEL)
    assert MODEL == before
    network = result["network"]
    assert network["metric_sets"][-1]["meta"]["name"] == results.EDITOR_RESULTS
    assert network["metric_sets"][-1]["filters"] == {
        "all_nodes": True,
        "all_virtual_nodes": False,
    }
    output = network["outputs"][-1]
    assert output["type"] == "ArrowStream"
    assert output["filename"] == results.EDITOR_RESULTS_FILE
    assert output["metric_set"] == results.EDITOR_RESULTS
    # the user's metric sets and outputs are kept
    model = json.loads(json.dumps(MODEL))
    model["network"]["metric_sets"] = [{"meta": {"name": "mine"}, "metrics": []}]
    model["network"]["outputs"] = [
        {"type": "CSV", "meta": {"name": "out"}, "filename": "a.csv", "format": "Wide", "metric_set": "mine"}
    ]
    result = results.with_editor_results(model)
    assert [c["meta"]["name"] for c in result["network"]["metric_sets"]] == [
        "mine",
        results.EDITOR_RESULTS,
    ]
    assert len(result["network"]["outputs"]) == 2
    # adding twice does nothing more
    assert results.with_editor_results(result) == result


def test_a_model_without_nodes_is_left_alone():
    model = {"network": {"nodes": [], "edges": []}}
    assert results.with_editor_results(model) == model
    assert results.with_editor_results({}) == {}


def test_scenario_table():
    assert results.simulation_indices(DOMAIN) == [[0, 0], [0, 1], [1, 0], [1, 1]]
    table = results.scenario_table(DOMAIN, [0, 1, 2, 3], ["a", "b", "c", "d"])
    assert list(table.columns) == ["Climate", "Demand"]
    assert table["Climate"].tolist() == ["dry", "dry", "wet", "wet"]
    assert table["Demand"].tolist() == [0, 1, 0, 1]
    # a subset and combinations
    domain = {
        "groups": [{"name": "A", "size": 5, "subset": {"type": "Indices", "indices": [1, 4]}}]
    }
    assert results.simulation_indices(domain) == [[1], [4]]
    domain = {**DOMAIN, "combinations": [["wet", 1], [0, 0]]}
    assert results.simulation_indices(domain) == [[1, 1], [0, 0]]
    # results that do not fit the domain are labelled with the CSV labels
    table = results.scenario_table(DOMAIN, [0, 1], ["x", "y"])
    assert list(table.columns) == ["scenario"] and table["scenario"].tolist() == ["x", "y"]
    assert results.scenario_table(None, [0], ["0"])["scenario"].tolist() == ["0"]


def test_convert_to_the_format_of_the_results_viewer(tmp_path):
    (tmp_path / results.WIDE_FILE).write_text(WIDE)
    assert results.convert_run(tmp_path, MODEL, "m.json", completed=True, solver="clp")

    runs = list_runs(tmp_path.parent)
    assert tmp_path in runs
    run = ResultsRun(tmp_path)
    assert run.recorder_names == ["in", "out"]
    assert run.index.loc["in", "type"] == "Outflow"
    assert run.index.loc["out", "type"] == "Inflow"
    assert run.metadata["format"] == "pywr-next"
    assert run.metadata["completed"] is True and run.metadata["solver"] == "clp"
    assert list(run.scenarios.columns) == ["Climate", "Demand"]
    frame = run.timeseries("in")
    assert list(frame.columns) == [0, 1, 2, 3]
    assert len(frame) == 3
    assert frame[1].tolist() == [1.0, 2.0, 3.0]
    summary = run.summary[run.summary["recorder"] == "in"].set_index("scenario")["value"]
    assert summary.to_dict() == {0: 3.0, 1: 2.0, 2: 2.5, 3: 4.0}
    assert run.combination_label(2) == "Climate=wet, Demand=0"
    # the files that were only a step are removed
    assert not (tmp_path / results.WIDE_FILE).exists()


def test_a_run_without_editor_results_is_not_converted(tmp_path):
    assert not results.convert_run(tmp_path, MODEL)
    assert not (tmp_path / "index.csv").exists()


def test_scenarios_written_by_the_run_are_used(tmp_path):
    info = {
        "groups": ["Climate", "Demand"],
        "simulations": [
            {"simulation_id": i, "scenario_labels": [c, str(d)]}
            for i, (c, d) in enumerate([("dry", 0), ("dry", 1), ("wet", 0), ("wet", 1)])
        ],
    }
    (tmp_path / results.WIDE_FILE).write_text(WIDE)
    (tmp_path / results.SCENARIOS_FILE).write_text(json.dumps(info))
    # the model has no scenario domain, which would be the only source otherwise
    model = {k: v for k, v in MODEL.items() if k != "scenarios"}
    assert results.convert_run(tmp_path, model)
    run = ResultsRun(tmp_path)
    assert list(run.scenarios.columns) == ["Climate", "Demand"]
    assert run.scenarios["Climate"].tolist() == ["dry", "dry", "wet", "wet"]
    assert run.scenarios["Demand"].tolist() == [0, 1, 0, 1]


@pytest.mark.skipif(
    not os.environ.get("PYWR_NEXT_PYTHON"),
    reason="PYWR_NEXT_PYTHON is not set to a Python with pywr-next",
)
def test_results_of_a_real_run(tmp_path):
    """
    Runs a model with scenarios with pywr-next and converts the Arrow stream the
    editor asks for, keeping all the digits.
    """
    python = os.environ["PYWR_NEXT_PYTHON"]
    model = json.loads(json.dumps(MODEL))
    model["network"]["nodes"][0]["max_flow"]["value"] = 3.14159265
    sent = results.with_editor_results(model)
    (tmp_path / "m.json").write_text(json.dumps(sent))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    process = subprocess.run(
        [python, "-m", "pywr", "run", "m.json", "-d", ".", "-o", str(run_dir)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    assert (run_dir / results.EDITOR_RESULTS_FILE).is_file()
    assert results.convert_run(run_dir, model, completed=True, python=python)
    run = ResultsRun(run_dir)
    assert run.recorder_names == ["in", "out"]
    frame = run.timeseries("in")
    assert frame.shape == (3, 4)
    assert (frame == 3.14159265).all().all()
    assert list(run.scenarios.columns) == ["Climate", "Demand"]
    assert run.scenarios["Climate"].tolist() == ["dry", "dry", "wet", "wet"]
    assert not (run_dir / results.WIDE_FILE).exists()


def test_the_results_dialog_shows_a_converted_run(qtbot, tmp_path):
    from pywr_editor.dialogs import ResultsDialog

    run_dir = tmp_path / "20240101_000000"
    run_dir.mkdir()
    (run_dir / results.WIDE_FILE).write_text(WIDE)
    assert results.convert_run(run_dir, MODEL, completed=True)
    dialog = ResultsDialog(output_dir=tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.run_combo.currentData() == str(run_dir)
    assert dialog.recorder_list.count() == 2
    dialog.recorder_list.selectAll()
    dialog.update_selection()
    # 2 nodes with 4 scenarios each
    assert len(dialog.traces) == 8
    assert dialog.data_model.rowCount() == 3


def test_the_window_has_the_results_button(qtbot, tmp_path):
    import shutil

    from pywr_editor import MainWindow
    from tests.utils import model_path

    model_file = tmp_path / "model.json"
    shutil.copy(model_path() / "pywr_next" / "time-series.json", model_file)
    window = MainWindow(str(model_file))
    window.hide()
    assert window.model_config.dialect.supports("run-results")
    assert window.app_actions.get("run-results").isEnabled()
    window.model_config.reset_change_flag()
    window.close()
