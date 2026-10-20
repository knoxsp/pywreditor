import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pywr.model import Model

from pywr_editor import MainWindow
from pywr_editor.console.console_panel import STARTUP_SCRIPT
from pywr_editor.console.interpreter import check_interpreter, resolve_interpreter
from pywr_editor.model.results import export_results
from pywr_editor.utils import Settings

MODEL = {
    "metadata": {"title": "tiny"},
    "timestepper": {"start": "2020-01-01", "end": "2020-01-10", "timestep": 1},
    "nodes": [
        {"name": "in", "type": "input", "max_flow": 10},
        {"name": "out", "type": "output", "max_flow": 5, "cost": -10},
    ],
    "edges": [["in", "out"]],
    "recorders": {"flow": {"type": "NumpyArrayNodeRecorder", "node": "out"}},
}


@pytest.fixture
def model_file(tmp_path):
    file = tmp_path / "model.json"
    file.write_text(json.dumps(MODEL))
    return file


def test_console_python_setting(model_file):
    settings = Settings(str(model_file))
    settings.instance.clear()
    assert settings.console_python == ""
    settings.save_console_python("  /some/venv/bin/python ")
    assert settings.console_python == "/some/venv/bin/python"
    settings.instance.clear()


def test_resolve_interpreter():
    assert resolve_interpreter("") == sys.executable
    assert resolve_interpreter(None) == sys.executable
    assert resolve_interpreter(" /a/python ") == "/a/python"


def test_check_interpreter(tmp_path):
    assert check_interpreter(sys.executable) is None
    assert "Cannot run" in check_interpreter(str(tmp_path / "missing"))


def run_startup(tmp_path, model_file, code: str, **config) -> str:
    """Runs the startup script in a plain Python process and then some code"""
    folder = tmp_path / "console"
    folder.mkdir()
    (folder / "model.json").write_text(json.dumps(MODEL))
    settings = {
        "model_json": str(folder / "model.json"),
        "model_file": str(model_file),
        "python_paths": [],
        "python_modules": [],
        "solver": "",
        "output_dir": str(tmp_path / "outputs"),
        **config,
    }
    (folder / "config.json").write_text(json.dumps(settings))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"exec(open({str(STARTUP_SCRIPT)!r}).read()); reload_model(); {code}",
        ],
        env={**os.environ, "PYWR_EDITOR_CONSOLE_CONFIG": str(folder / "config.json")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_startup_loads_the_model(tmp_path, model_file):
    out = run_startup(
        tmp_path,
        model_file,
        "model.run(); print('FLOW', recorders['flow'].to_dataframe().sum().iloc[0]);"
        "print('NODES', sorted(n.name for n in nodes))",
    )
    assert "Loaded the model with 2 nodes, 0 parameters and 1 recorders." in out
    assert "FLOW 50.0" in out
    assert "NODES ['in', 'out']" in out


def test_startup_applies_python_paths_and_modules(tmp_path, model_file):
    modules = tmp_path / "src"
    modules.mkdir()
    (modules / "custom_mod.py").write_text("MARKER = 42\n")
    out = run_startup(
        tmp_path,
        model_file,
        "import custom_mod; print('MARKER', custom_mod.MARKER)",
        python_paths=[str(modules)],
        python_modules=["custom_mod.py"],
    )
    assert "MARKER 42" in out


def test_startup_reports_a_failing_module(tmp_path, model_file):
    out = run_startup(
        tmp_path, model_file, "print('MODEL', model is not None)",
        python_modules=["not_a_module"],
    )
    assert "Cannot import the module 'not_a_module'" in out
    assert "MODEL True" in out


def test_startup_reads_saved_results(tmp_path, model_file):
    model = Model.load(MODEL)
    model.run()
    run_dir = export_results(model, tmp_path / "outputs", model_file)
    out = run_startup(
        tmp_path,
        model_file,
        "r = results(); print('RUN', r.path.name, r.recorder_names);"
        "print('SUM', r.timeseries('flow').sum().iloc[0]);"
        "print('RUNS', [p.name for p in runs()])",
    )
    assert f"RUN {run_dir.name} ['flow']" in out
    assert "SUM 50.0" in out
    assert f"RUNS ['{run_dir.name}']" in out


def test_console_panel_loads_the_model(qtbot, model_file):
    window = MainWindow(str(model_file))
    try:
        qtbot.addWidget(window)
        window.console_panel.show()
        console = window.console_panel.console
        assert console is not None
        qtbot.waitUntil(
            lambda: "Loaded the model with 2 nodes" in console._control.toPlainText(),
            timeout=90000,
        )
        # edits made in the editor are available after the model is reloaded
        window.model_config.json["nodes"].append(
            {"name": "extra", "type": "output", "max_flow": 1}
        )
        window.console_panel.reload_model()
        qtbot.waitUntil(
            lambda: "Loaded the model with 3 nodes" in console._control.toPlainText(),
            timeout=90000,
        )
    finally:
        window.console_panel.shutdown()
        window.prompt_unsaved_changes = False
        window.close()
