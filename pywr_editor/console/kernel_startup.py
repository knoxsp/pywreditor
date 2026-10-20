"""
 Startup script run by the IPython kernel of the console. The kernel can use a
 different Python environment from the editor, which may not have pywr_editor (or
 Qt) installed, so this script is self-contained and only needs Pywr and pandas.

 The editor passes the settings in a JSON file, whose path is stored in the
 PYWR_EDITOR_CONSOLE_CONFIG environment variable:
   model_json: a copy of the model as currently open in the editor
   model_file: the path to the model file (None if the model is not saved)
   python_paths, python_modules, solver, output_dir: the editor settings

 The names defined here are available in the console. The model is loaded by the
 first call to reload_model(), made by the editor once the console is connected.
"""
import copy as _copy
import importlib as _importlib
import json as _json
import os as _os
import site as _site
import sys as _sys
import traceback as _traceback
from pathlib import Path as _Path

with open(_os.environ["PYWR_EDITOR_CONSOLE_CONFIG"]) as _fid:
    _config = _json.load(_fid)


def _add_python_paths(paths):
    # same logic as the editor uses to run a model
    version = f"python{_sys.version_info.major}.{_sys.version_info.minor}"
    for path in paths:
        folder = _Path(path).expanduser()
        if not folder.is_dir():
            continue
        site_dirs = [
            d
            for d in [
                folder / "lib" / version / "site-packages",
                folder / "Lib" / "site-packages",
                folder / "site-packages",
            ]
            if d.is_dir()
        ]
        for d in site_dirs or [folder]:
            if str(d) not in _sys.path:
                if site_dirs:
                    _site.addsitedir(str(d))
                else:
                    _sys.path.insert(0, str(d))


_add_python_paths(_config["python_paths"])

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt

    get_ipython().run_line_magic("matplotlib", "inline")  # noqa: F821
except Exception:
    plt = None

import pywr
from pywr.model import Model

for _module in _config["python_modules"]:
    # accept a file name such as "parameters.py"
    _module = _module.strip().removesuffix(".py")
    try:
        _importlib.import_module(_module)
    except Exception:
        print(f"Cannot import the module '{_module}':\n{_traceback.format_exc()}")

model = None
model_data = None
nodes = parameters = recorders = scenarios = None
model_file = _config["model_file"]
output_dir = _config["output_dir"]


_banner_shown = False


def reload_model():
    """
    Loads the model as it is currently open in the editor. The editor refreshes the
    copy of the model when the console's "Reload model" button is used.
    """
    global model, model_data, nodes, parameters, recorders, scenarios, _banner_shown
    if not _banner_shown:
        # shown by the first call, which the editor makes once the console is
        # connected, because the output of this script would be lost
        _banner_shown = True
        print(
            f"Pywr {pywr.__version__} (Python {_sys.version.split()[0]})\n"
            "Available: model, nodes, parameters, recorders, scenarios, model_data, "
            "np, pd, plt\n"
            "Helpers: reload_model(), runs(), results()\n"
            "Run with model.run(). Use the Interrupt button to stop a long run.\n"
        )
    try:
        with open(_config["model_json"]) as fid:
            data = _json.load(fid)
        loaded = _copy.deepcopy(data)
        if _config["solver"] and "solver" not in loaded:
            loaded["solver"] = {"name": _config["solver"]}
        new_model = Model.load(loaded, path=model_file)
    except Exception:
        print(f"The model failed to load:\n{_traceback.format_exc()}")
        return
    model, model_data = new_model, data
    nodes, parameters = model.nodes, model.parameters
    recorders, scenarios = model.recorders, model.scenarios
    print(
        f"Loaded the model with {len(nodes)} nodes, {len(parameters)} parameters "
        f"and {len(recorders)} recorders."
    )


class Results:
    """The recorder results of a run saved by the editor."""

    def __init__(self, path):
        self.path = _Path(path)
        with open(self.path / "metadata.json") as fid:
            self.metadata = _json.load(fid)
        self.index = pd.read_csv(self.path / "index.csv", keep_default_na=False)
        self.index = self.index.set_index("name", drop=False)
        self.summary = pd.read_csv(self.path / "summary.csv")
        scenarios_file = self.path / "scenarios.csv"
        self.scenarios = (
            pd.read_csv(scenarios_file, index_col=0)
            if scenarios_file.is_file()
            else pd.DataFrame()
        )

    @property
    def recorder_names(self):
        return list(self.index.index)

    def timeseries(self, name):
        """The time series of a recorder: one column per scenario combination."""
        file = self.index.loc[name, "file"]
        if not file:
            raise KeyError(f"The recorder '{name}' has no time series")
        frame = pd.read_csv(self.path / file, index_col=0, parse_dates=True)
        frame.columns = [int(c) for c in frame.columns]
        return frame

    def __repr__(self):
        return f"Results({self.path.name!r}, {len(self.index)} recorders)"


def runs():
    """The folders of the saved runs, the most recent first."""
    folder = _Path(output_dir)
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if (p / "metadata.json").is_file()),
        key=lambda p: p.name,
        reverse=True,
    )


def results(run=None):
    """
    Reads the recorder results saved by the editor.
    :param run: The name or path of a run folder. Defaults to the latest run.
    """
    if run is None:
        available = runs()
        if not available:
            raise FileNotFoundError(f"No saved runs in {output_dir}")
        return Results(available[0])
    path = _Path(run)
    return Results(path if path.is_absolute() else _Path(output_dir) / path)

