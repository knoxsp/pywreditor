import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

"""
 Saves the recorder results of a model run to disk and reads them back.

 A run is saved in a timestamped folder:

   <output folder>/<YYYYMMDD_HHMMSS>/
       metadata.json      information on the run
       index.csv          one row per recorder: name, type, file, number of traces
       summary.csv        the value of every recorder for each scenario combination
       scenarios.csv      the scenario indexes of each scenario combination
       recorders/*.csv    the time series of the recorders that store one. The index
                          is the timestep and each column a scenario combination
"""

DEFAULT_OUTPUT_FOLDER = "outputs"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
METADATA_FILE = "metadata.json"


def default_output_dir(model_file: str | Path | None) -> Path:
    """
    Returns the default output folder: the "outputs" folder next to the model file.
    :param model_file: The path to the model JSON file.
    :return: The output folder.
    """
    if model_file:
        return Path(model_file).parent / DEFAULT_OUTPUT_FOLDER
    return Path.cwd() / DEFAULT_OUTPUT_FOLDER


def resolve_output_dir(
    configured: str | None, model_file: str | Path | None
) -> Path:
    """
    Returns the folder where the runs are saved.
    :param configured: The folder set by the user. A relative path is relative to
    the model folder. If empty, the default folder is used.
    :param model_file: The path to the model JSON file.
    :return: The output folder.
    """
    if not configured or not configured.strip():
        return default_output_dir(model_file)
    folder = Path(configured.strip()).expanduser()
    if not folder.is_absolute() and model_file:
        folder = Path(model_file).parent / folder
    return folder


def _safe_name(name: str, max_length: int = 80) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")[:max_length] or "recorder"


def export_results(
    pywr_model,
    output_dir: str | Path,
    model_file: str | Path | None = None,
    completed: bool = True,
    timestamp: datetime | None = None,
) -> Path:
    """
    Saves the recorders of a (stepped) Pywr model to a new timestamped folder.
    :param pywr_model: The Pywr model.
    :param output_dir: The folder containing the runs.
    :param model_file: The model JSON file, stored in the metadata.
    :param completed: Whether the run reached the end date.
    :param timestamp: The run timestamp. Default to now.
    :return: The folder of the run.
    """
    timestamp = timestamp or datetime.now()
    run_dir = Path(output_dir) / timestamp.strftime(TIMESTAMP_FORMAT)
    # two runs can finish in the same second
    suffix = 1
    while run_dir.exists():
        run_dir = Path(output_dir) / f"{timestamp.strftime(TIMESTAMP_FORMAT)}_{suffix}"
        suffix += 1
    (run_dir / "recorders").mkdir(parents=True)

    index_rows = []
    summary_rows = []
    skipped = {}
    combinations = None

    for number, recorder in enumerate(pywr_model.recorders):
        name = recorder.name
        if name is None:
            continue
        row = {
            "name": name,
            "type": type(recorder).__name__,
            "file": "",
            "traces": 0,
        }
        try:
            values = np.asarray(recorder.values(), dtype=float)
            for combo, value in enumerate(values):
                summary_rows.append((name, combo, float(value)))
            row["traces"] = len(values)
        except Exception as e:
            skipped[name] = f"values: {e}"

        if hasattr(recorder, "to_dataframe"):
            try:
                frame = recorder.to_dataframe()
                if combinations is None:
                    combinations = [tuple(c) for c in frame.columns.to_list()]
                    scenario_names = list(frame.columns.names)
                frame = frame.copy()
                frame.columns = range(frame.shape[1])
                if isinstance(frame.index, pd.PeriodIndex):
                    frame.index = frame.index.to_timestamp()
                frame.index.name = "time"
                file = f"{number:04d}_{_safe_name(name)}.csv"
                frame.to_csv(run_dir / "recorders" / file)
                row["file"] = f"recorders/{file}"
                row["traces"] = frame.shape[1]
            except Exception as e:
                skipped[name] = f"time series: {e}"
        index_rows.append(row)

    pd.DataFrame(index_rows, columns=["name", "type", "file", "traces"]).to_csv(
        run_dir / "index.csv", index=False
    )
    pd.DataFrame(summary_rows, columns=["recorder", "scenario", "value"]).to_csv(
        run_dir / "summary.csv", index=False
    )
    if combinations is not None:
        scenarios = pd.DataFrame(combinations, columns=scenario_names)
        scenarios.index.name = "combination"
        scenarios.to_csv(run_dir / "scenarios.csv")

    current = None
    try:
        current = str(pywr_model.timestepper.current.period)
    except Exception:
        pass
    solver = getattr(getattr(pywr_model, "solver", None), "name", None)
    try:
        import pywr

        pywr_version = pywr.__version__
    except Exception:
        pywr_version = None
    with open(run_dir / METADATA_FILE, "w") as fid:
        json.dump(
            {
                "model_file": str(model_file) if model_file else None,
                "saved": timestamp.isoformat(timespec="seconds"),
                "completed": completed,
                "last_timestep": current,
                "solver": solver,
                "pywr_version": pywr_version,
                "recorders": len(index_rows),
                "skipped": skipped,
            },
            fid,
            indent=2,
        )
    return run_dir


def list_runs(output_dir: str | Path) -> list[Path]:
    """
    Lists the saved runs in a folder.
    :param output_dir: The folder containing the runs.
    :return: The run folders, the most recent first.
    """
    folder = Path(output_dir)
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if (p / METADATA_FILE).is_file()),
        key=lambda p: p.name,
        reverse=True,
    )


@dataclass
class Trace:
    """A single line of a plot: one scenario combination of a recorder."""

    recorder: str
    combination: int
    label: str

    @property
    def key(self) -> tuple[str, int]:
        return self.recorder, self.combination


@dataclass
class ResultsRun:
    """The saved results of a run."""

    path: Path
    metadata: dict = field(default_factory=dict)
    index: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    scenarios: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __post_init__(self):
        self.path = Path(self.path)
        self._cache: dict[str, pd.DataFrame] = {}
        with open(self.path / METADATA_FILE) as fid:
            self.metadata = json.load(fid)
        self.index = pd.read_csv(self.path / "index.csv", keep_default_na=False)
        self.index = self.index.set_index("name", drop=False)
        self.summary = pd.read_csv(self.path / "summary.csv")
        scenarios = self.path / "scenarios.csv"
        if scenarios.is_file():
            self.scenarios = pd.read_csv(scenarios, index_col=0)

    @property
    def recorder_names(self) -> list[str]:
        return list(self.index.index)

    def has_timeseries(self, name: str) -> bool:
        return bool(self.index.loc[name, "file"])

    def timeseries(self, name: str) -> pd.DataFrame:
        """
        Returns the time series of a recorder, with a column for each scenario
        combination (the column name is the combination index).
        """
        if name not in self._cache:
            file = self.index.loc[name, "file"]
            if not file:
                raise KeyError(f"The recorder '{name}' has no time series")
            frame = pd.read_csv(self.path / file, index_col=0, parse_dates=True)
            frame.columns = [int(c) for c in frame.columns]
            self._cache[name] = frame
        return self._cache[name]

    def combination_label(self, combination: int) -> str:
        """
        Describes a scenario combination using only the scenarios that vary.
        """
        if self.scenarios.empty or combination not in self.scenarios.index:
            return str(combination)
        varying = [c for c in self.scenarios.columns if self.scenarios[c].nunique() > 1]
        if not varying:
            return str(combination)
        row = self.scenarios.loc[combination]
        return ", ".join(f"{c}={row[c]}" for c in varying)

    def traces(self, names: list[str]) -> list[Trace]:
        """
        Returns the traces of the recorders (one for each scenario combination).
        Recorders without a time series are ignored.
        """
        traces = []
        for name in names:
            if not self.has_timeseries(name):
                continue
            columns = self.timeseries(name).columns
            for combination in columns:
                label = (
                    name
                    if len(columns) == 1
                    else f"{name} [{self.combination_label(combination)}]"
                )
                traces.append(Trace(name, int(combination), label))
        return traces

    def trace_data(self, traces: list[Trace]) -> pd.DataFrame:
        """
        Returns the values of the traces, one column for each trace.
        """
        frames = {t.label: self.timeseries(t.recorder)[t.combination] for t in traces}
        return pd.DataFrame(frames)


MAX_INDIVIDUAL_TRACES = 20
""" The number of traces drawn by default as individual lines """
MAX_PICKABLE_TRACES = 200
""" Above this, drawing a selection of lines is not a useful way to read the results """
ENVELOPE_PERCENTILES = (5, 25, 50, 75, 95)


def choose_plot_mode(trace_count: int, recorder_count: int) -> str:
    """
    Chooses how a set of traces is drawn.
    - "individual": each ticked trace is a line. All the traces are ticked up to
      MAX_INDIVIDUAL_TRACES, otherwise the first ones are and the user picks others.
    - "envelope": the percentiles of the traces (median and bands) are drawn, with
      the ticked traces highlighted. This is the only readable view of hundreds or
      thousands of scenarios of a few recorders. It is chosen when there are many
      traces and few recorders. With many recorders each is a different quantity
      (and may have different units), so the user is left to filter and pick.
    :param trace_count: The number of traces.
    :param recorder_count: The number of recorders the traces belong to.
    :return: "individual" or "envelope".
    """
    if trace_count > MAX_PICKABLE_TRACES and recorder_count <= MAX_INDIVIDUAL_TRACES:
        return "envelope"
    return "individual"


def default_ticked(traces: list[Trace], mode: str) -> set[tuple[str, int]]:
    """
    Returns the traces ticked by default.
    """
    if mode == "envelope":
        return set()
    return {t.key for t in traces[:MAX_INDIVIDUAL_TRACES]}


def envelope(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Computes the percentiles of the traces at every timestep.
    :param frame: The traces, one for each column.
    :return: A dataframe with a column for each of ENVELOPE_PERCENTILES.
    """
    values = np.nanpercentile(frame.to_numpy(dtype=float), ENVELOPE_PERCENTILES, axis=1)
    return pd.DataFrame(
        values.T, index=frame.index, columns=list(ENVELOPE_PERCENTILES)
    )


def trace_statistics(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Returns the minimum, mean and maximum of each trace, used to find the traces of
    interest (for example the ones with the highest maximum).
    """
    return pd.DataFrame(
        {"min": frame.min(), "mean": frame.mean(), "max": frame.max()}
    )
