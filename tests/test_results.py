import json

import numpy as np
import pandas as pd
import pytest
from pywr.model import Model

from pywr_editor.model.results import (
    ResultsRun,
    choose_plot_mode,
    default_output_dir,
    default_ticked,
    envelope,
    export_results,
    list_runs,
    resolve_output_dir,
)


def make_model(scenario_size: int = 3, steps: int = 5):
    model = Model.load(
        {
            "metadata": {"title": "t", "minimum_version": "0"},
            "timestepper": {
                "start": "2020-01-01",
                "end": "2020-01-05",
                "timestep": 1,
            },
            "scenarios": [{"name": "s", "size": scenario_size}],
            "nodes": [
                {"name": "i", "type": "input", "max_flow": 5},
                {"name": "o", "type": "output", "max_flow": 3, "cost": -1},
            ],
            "edges": [["i", "o"]],
            "recorders": {
                "flow": {"type": "numpyarraynode", "node": "o"},
                "deficit/total (ml)": {"type": "numpyarraynodedeficit", "node": "o"},
                "agg": {
                    "type": "aggregated",
                    "recorder_agg_func": "sum",
                    "recorders": ["flow", "deficit/total (ml)"],
                },
            },
            "solver": {"name": "glpk-edge"},
        }
    )
    for _ in range(steps):
        model.step()
    return model


def test_output_dir_defaults_and_resolution(tmp_path):
    model_file = tmp_path / "models" / "m.json"
    assert default_output_dir(model_file) == tmp_path / "models" / "outputs"
    assert resolve_output_dir("", model_file) == tmp_path / "models" / "outputs"
    assert resolve_output_dir("res", model_file) == tmp_path / "models" / "res"
    assert resolve_output_dir(str(tmp_path / "abs"), model_file) == tmp_path / "abs"


class TestExport:
    def test_export_and_read_back(self, tmp_path):
        run_dir = export_results(make_model(), tmp_path / "outputs")
        assert run_dir.parent == tmp_path / "outputs"
        # timestamped folder name
        assert len(run_dir.name) == 15 and run_dir.name[8] == "_"
        assert list_runs(tmp_path / "outputs") == [run_dir]

        run = ResultsRun(run_dir)
        assert set(run.recorder_names) == {"flow", "deficit/total (ml)", "agg"}
        assert run.metadata["completed"] is True
        assert run.metadata["solver"] == "glpk-edge"
        # the aggregated recorder has a value but no time series
        assert not run.has_timeseries("agg")
        assert run.has_timeseries("flow")
        frame = run.timeseries("flow")
        assert frame.shape == (5, 3)
        assert isinstance(frame.index, pd.DatetimeIndex)
        assert set(run.summary["recorder"]) == {"flow", "deficit/total (ml)", "agg"}

    def test_two_runs_in_the_same_second_do_not_overwrite(self, tmp_path):
        from datetime import datetime

        now = datetime(2026, 1, 1, 10, 0, 0)
        a = export_results(make_model(), tmp_path, timestamp=now)
        b = export_results(make_model(), tmp_path, timestamp=now)
        assert a != b and a.exists() and b.exists()

    def test_traces_and_labels(self, tmp_path):
        run = ResultsRun(export_results(make_model(scenario_size=3), tmp_path))
        traces = run.traces(["flow", "agg"])
        # agg has no time series
        assert len(traces) == 3
        assert traces[0].label == "flow [s=0]"
        assert run.trace_data(traces).shape == (5, 3)

        single = ResultsRun(export_results(make_model(scenario_size=1), tmp_path))
        assert [t.label for t in single.traces(["flow"])] == ["flow"]


class TestManyTraces:
    def test_mode_choice(self):
        assert choose_plot_mode(3, 1) == "individual"
        assert choose_plot_mode(200, 1) == "individual"
        # thousands of scenarios of few recorders: envelope
        assert choose_plot_mode(5000, 2) == "envelope"
        # many distinct recorders are not blended into one band
        assert choose_plot_mode(869, 869) == "individual"

    def test_default_ticks(self, tmp_path):
        run = ResultsRun(export_results(make_model(scenario_size=30), tmp_path))
        traces = run.traces(["flow"])
        assert len(default_ticked(traces, "individual")) == 20
        assert default_ticked(traces, "envelope") == set()

    def test_envelope_percentiles(self):
        frame = pd.DataFrame(np.arange(100, dtype=float).reshape(1, 100).repeat(2, 0))
        env = envelope(frame)
        assert env[50].iloc[0] == pytest.approx(49.5)
        assert env[5].iloc[0] < env[25].iloc[0] < env[75].iloc[0] < env[95].iloc[0]


class TestResultsDialog:
    def open(self, qtbot, tmp_path, scenario_size):
        from pywr_editor.dialogs import ResultsDialog

        run_dir = export_results(make_model(scenario_size=scenario_size), tmp_path)
        dialog = ResultsDialog(output_dir=tmp_path)
        qtbot.addWidget(dialog)
        return dialog, run_dir

    def test_few_traces_are_all_plotted(self, qtbot, tmp_path):
        dialog, run_dir = self.open(qtbot, tmp_path, 3)
        assert dialog.run_combo.currentData() == str(run_dir)
        assert dialog.recorder_list.count() == 3

        dialog.recorder_list.selectAll()
        dialog.update_selection()
        assert len(dialog.traces) == 6
        assert len(dialog.ticked_traces()) == 6
        assert dialog.effective_mode() == "individual"
        assert dialog.data_model.rowCount() == 5
        assert dialog.data_model.columnCount() == 6
        # the aggregated recorder only has values
        assert dialog.values_model.rowCount() == 3

    def test_many_traces_tick_first_20_and_pick_others(self, qtbot, tmp_path):
        dialog, _ = self.open(qtbot, tmp_path, 60)
        dialog.recorder_list.item(0).setSelected(True)
        dialog.update_selection()
        assert len(dialog.traces) == 60
        assert len(dialog.ticked_traces()) == 20
        dialog.trace_table.selectRow(30)
        dialog.tick_highlighted()
        assert len(dialog.ticked_traces()) == 21
        dialog.tick_top()
        assert len(dialog.ticked_traces()) == 20
        dialog.untick_all()
        assert dialog.ticked_traces() == []

    def test_envelope_for_hundreds_of_scenarios(self, qtbot, tmp_path):
        dialog, _ = self.open(qtbot, tmp_path, 250)
        dialog.recorder_list.item(0).setSelected(True)
        dialog.update_selection()
        assert dialog.effective_mode() == "envelope"
        # nothing is highlighted until the user picks traces
        assert dialog.ticked_traces() == []
        dialog.tick_top()
        assert len(dialog.ticked_traces()) == 20
        # forcing the individual mode is possible
        dialog.mode_combo.setCurrentIndex(1)
        assert dialog.effective_mode() == "individual"

    def test_filter_by_name_and_type(self, qtbot, tmp_path):
        dialog, _ = self.open(qtbot, tmp_path, 3)
        dialog.filter.setText("agg")
        shown = [
            dialog.recorder_list.item(i).text()
            for i in range(dialog.recorder_list.count())
            if not dialog.recorder_list.item(i).isHidden()
        ]
        assert shown == ["agg"]


def test_full_run_saves_results_and_opens_viewer(qtbot, tmp_path):
    from PySide6.QtCore import Qt

    from pywr_editor import MainWindow
    from pywr_editor.toolbar.run_controls.run_widget import RunWidget
    from tests.utils import resolve_model_path

    with open(resolve_model_path("model_to_run.json")) as fp:
        model = json.load(fp)
    model["recorders"] = {"inflow": {"type": "numpyarraynode", "node": "Input"}}
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model))

    window = MainWindow(str(path))
    window.hide()
    window.editor_settings.save_results_enabled(True)
    run_widget = window.findChild(RunWidget)
    qtbot.mouseClick(run_widget.run_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: run_widget.last_results_dir is not None, timeout=20000)

    # default location: "outputs" next to the model
    runs = list_runs(tmp_path / "outputs")
    assert len(runs) == 1
    assert run_widget.last_results_dir == str(runs[0])
    run = ResultsRun(runs[0])
    assert run.metadata["completed"] is True
    assert run.has_timeseries("inflow")
    # the glpk-edge solver is the default
    assert run.metadata["solver"] == "glpk-edge"
    run_widget._results_box.close()
    window.editor_settings.instance.clear()
