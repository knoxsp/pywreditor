import copy
import itertools
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pywr_editor.dialects.next import scenarios as sc
from pywr_editor.model.results import METADATA_FILE

"""
 The results of a pywr-next run, for the results viewer.

 The run service writes the outputs of the model in the folder of the run. When the
 user asks to save the results, the editor adds to the model it sends to the service (not
 to the model file) a metric set with every node and virtual node, and a CSV output with
 the metric set in "wide" format: a column for each node, attribute and scenario. After
 the run the CSV is converted to the folder format that the results of a pywr v1 run
 have (see model/results.py), so that the same results dialog shows them:

   index.csv      one row for each node: its name, the attribute as the type, the file
   summary.csv    the mean over the run of each node, for each scenario
   scenarios.csv  the index of each scenario group of each simulation
   recorders/     the time series of each node
 The outputs the user defined in the model are written by the service as usual.
"""

EDITOR_RESULTS = "editor results"
""" The name of the metric set and the output the editor adds """
EDITOR_RESULTS_FILE = "editor_results.arrow"
""" The Arrow stream the editor adds to the outputs of the run """
WIDE_FILE = "editor_results.csv"
""" The CSV that the Arrow stream is turned into """
SCENARIOS_FILE = "editor_results.scenarios.json"
""" The scenarios of the Arrow stream """
BATCH_SIZE = 256
""" The rows of a batch of the Arrow stream. The batch being written is saved when
the run is stopped, so the results of a stopped run are not lost """
SOURCE = "pywr-next"


def with_editor_results(model: dict) -> dict:
    """
    Adds the metric set and the output that give the results of every node.
    :param model: The model dictionary.
    :return: A copy of the model. It is not changed if there is no network or the
    user already has outputs with these names.
    """
    result = copy.deepcopy(model)
    network = result.get("network")
    if not isinstance(network, dict) or not network.get("nodes"):
        return result
    metric_sets = network.setdefault("metric_sets", [])
    outputs = network.setdefault("outputs", [])
    taken = {
        c.get("meta", {}).get("name")
        for c in (metric_sets or []) + (outputs or [])
        if isinstance(c, dict)
    }
    if EDITOR_RESULTS in taken:
        return result
    metric_sets.append(
        {
            "meta": {"name": EDITOR_RESULTS},
            "filters": {
                "all_nodes": True,
                "all_virtual_nodes": bool(network.get("virtual_nodes")),
            },
            "metrics": [],
        }
    )
    outputs.append(
        {
            "type": "ArrowStream",
            "meta": {"name": EDITOR_RESULTS},
            "filename": EDITOR_RESULTS_FILE,
            "batch_size": BATCH_SIZE,
            "metric_set": EDITOR_RESULTS,
        }
    )
    return result

ARROW_PROGRAM = """\
import json, sys
import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

source, wide, info = sys.argv[1:4]
reader = ipc.open_stream(open(source, "rb"))
batches = []
try:
    for batch in reader:
        batches.append(batch)
except Exception:
    pass  # the run was stopped while a batch was written
if not batches:
    sys.exit(3)
table = pa.Table.from_batches(batches, schema=reader.schema)
if table.num_rows == 0:
    sys.exit(3)
metadata = reader.schema.metadata or {}
simulations = json.loads(metadata.get(b"PYWR_SCENARIOS", b"[]"))
groups = json.loads(metadata.get(b"PYWR_SCENARIO_GROUPS", b"[]"))
labels = ["-".join(str(l) for l in s["scenario_labels"]) for s in simulations]
times = table.column("time_start").to_pandas().dt.strftime("%Y-%m-%dT%H:%M:%S")

nodes, attributes, ids, scenario_labels, columns = [], [], [], [], []
for field in reader.schema:
    extension = (field.metadata or {}).get(b"ARROW:extension:metadata")
    if extension is None:
        continue
    metric = json.loads(extension)
    column = table.column(field.name).combine_chunks()
    values = column.flatten().to_numpy(zero_copy_only=False).reshape(len(column), -1)
    for position in range(values.shape[1]):
        nodes.append(metric["name"])
        attributes.append(metric.get("attribute") or "")
        ids.append(str(simulations[position]["simulation_id"] if simulations else position))
        scenario_labels.append(labels[position] if labels else str(position))
        columns.append(values[:, position])
if not columns:
    sys.exit(3)
data = np.column_stack(columns)
with open(wide, "w", newline="") as out:
    for name, row in (("node", nodes), ("attribute", attributes), ("simulation_id", ids), ("label", scenario_labels)):
        out.write(",".join([name] + row) + "\\n")
    for when, row in zip(times, data):
        out.write(when + "," + ",".join(repr(float(v)) for v in row) + "\\n")
with open(info, "w") as out:
    json.dump({"groups": [g["name"] for g in groups], "simulations": simulations}, out)
"""
""" The program that turns the Arrow stream of the results into the wide CSV, run with
the Python of the pywr-next environment, which has pyarrow. It exits with 3 if the stream
has no rows """


def arrow_to_wide(python: str, run_dir: str | Path, timeout: float = 300.0) -> bool:
    """
    Turns the Arrow stream of the results into the wide CSV and the scenarios file.
    :param python: The Python interpreter of the pywr-next environment.
    :param run_dir: The folder of the run.
    :param timeout: The seconds after which the conversion is stopped.
    :return: True if the files were written, False if the stream has no results.
    :raises RuntimeError: If the conversion failed.
    """
    import subprocess

    run_dir = Path(run_dir)
    source = run_dir / EDITOR_RESULTS_FILE
    if not source.is_file():
        return False
    process = subprocess.run(
        [
            python,
            "-c",
            ARROW_PROGRAM,
            str(source),
            str(run_dir / WIDE_FILE),
            str(run_dir / SCENARIOS_FILE),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if process.returncode == 3:
        return False
    if process.returncode != 0:
        raise RuntimeError(
            "The results could not be read from the output of the run:\n"
            + (process.stderr or process.stdout).strip()
        )
    return True


def read_wide_csv(path: Path) -> pd.DataFrame:
    """
    Reads a CSV output in wide format.
    :param path: The file.
    :return: The values with the time as index, and a column for each node, attribute,
    simulation id and scenario label (a MultiIndex with these names).
    """
    frame = pd.read_csv(path, header=[0, 1, 2, 3], index_col=0)
    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "time"
    frame.columns = frame.columns.set_names(["node", "attribute", "simulation", "label"])
    frame.columns = frame.columns.set_levels(
        frame.columns.levels[2].astype(int), level="simulation"
    )
    return frame


def simulation_indices(domain: Any) -> list[list[int]] | None:
    """
    Lists the scenario of each group in each simulation of a scenario domain.
    :param domain: The "scenarios" dictionary, or None.
    :return: One list of indices for each simulation, in the order pywr-next runs
    them (the last group changes fastest). None if the domain is not valid.
    """
    groups = sc.groups_of(domain)
    combinations = domain.get("combinations") if isinstance(domain, dict) else None
    if combinations:
        rows = []
        for combination in combinations:
            row = []
            for value, group in zip(combination, groups):
                labels = group.get("labels") or []
                row.append(labels.index(value) if isinstance(value, str) else value)
            rows.append(row)
        return rows
    choices = [sc.subset_indices(group) for group in groups]
    if any(choice is None for choice in choices):
        return None
    return [list(row) for row in itertools.product(*choices)]


def scenario_table(
    domain: Any,
    simulations: list[int],
    labels: list[str],
    info: dict | None = None,
) -> pd.DataFrame:
    """
    Builds the table of the scenarios of the run, with the scenario of each group.
    :param domain: The "scenarios" dictionary, or None.
    :param simulations: The simulation ids of the results.
    :param labels: The label of each simulation, as in the CSV.
    :param info: The scenarios written by the run (the content of SCENARIOS_FILE),
    which are used instead of the domain when they fit the results.
    :return: A table with a row for each simulation and a column for each group, with
    the label of the scenario when the group has labels, or its index. Without a
    scenario domain that fits the results, there is one column with the CSV labels.
    """
    by_id = {s["simulation_id"]: s for s in (info or {}).get("simulations", [])}
    names = (info or {}).get("groups") or []
    if names and by_id and all(s in by_id for s in simulations):
        columns = {name: [] for name in names}
        for simulation in simulations:
            values = by_id[simulation]["scenario_labels"]
            for name, value in zip(names, values):
                columns[name].append(int(value) if str(value).isdigit() else value)
        frame = pd.DataFrame(columns)
        frame.index = pd.Index(range(len(simulations)), name="combination")
        return frame

    groups = sc.groups_of(domain)
    rows = simulation_indices(domain)
    if groups and rows is not None and len(rows) == len(simulations):
        table = {}
        for position, group in enumerate(groups):
            names = group.get("labels") or []
            table[group.get("name") or f"group {position + 1}"] = [
                names[row[position]] if names and row[position] < len(names) else row[position]
                for row in rows
            ]
        frame = pd.DataFrame(table)
    else:
        frame = pd.DataFrame({"scenario": labels})
    frame.index = pd.Index(range(len(simulations)), name="combination")
    return frame


def _safe_name(name: str, max_length: int = 80) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")[:max_length] or "node"


def convert_run(
    run_dir: str | Path,
    model: dict,
    model_file: str | Path | None = None,
    completed: bool = True,
    solver: str | None = None,
    python: str | None = None,
) -> bool:
    """
    Converts the results the editor asked the service to write to the folder format of
    the results viewer.
    :param run_dir: The folder of the run.
    :param model: The model dictionary, for its scenarios.
    :param model_file: The model file, stored in the metadata.
    :param completed: Whether the run reached its end.
    :param solver: The solver of the run, stored in the metadata.
    :param python: The Python interpreter of the pywr-next environment, which reads the
    Arrow stream of the service. Not needed if the run folder has the wide CSV.
    :return: True if the results were converted, False if the run has no editor
    results.
    """
    run_dir = Path(run_dir)
    source = run_dir / WIDE_FILE
    if python and (run_dir / EDITOR_RESULTS_FILE).is_file():
        if not arrow_to_wide(python, run_dir):
            return False
    if not source.is_file() or source.stat().st_size == 0:
        return False
    frame = read_wide_csv(source)
    if frame.empty:
        return False
    info = None
    info_file = run_dir / SCENARIOS_FILE
    if info_file.is_file():
        info = json.loads(info_file.read_text())

    simulations = sorted(frame.columns.get_level_values("simulation").unique())
    label_of = dict(
        zip(
            frame.columns.get_level_values("simulation"),
            frame.columns.get_level_values("label"),
        )
    )
    scenarios = scenario_table(
        model.get("scenarios"),
        simulations,
        [str(label_of[s]) for s in simulations],
        info,
    )
    position = {simulation: number for number, simulation in enumerate(simulations)}

    (run_dir / "recorders").mkdir(exist_ok=True)
    pairs = list(dict.fromkeys(zip(frame.columns.get_level_values("node"), frame.columns.get_level_values("attribute"))))
    nodes_with_attributes: dict[str, int] = {}
    for node, _ in pairs:
        nodes_with_attributes[node] = nodes_with_attributes.get(node, 0) + 1

    index_rows, summary_rows = [], []
    for number, (node, attribute) in enumerate(pairs):
        name = node if nodes_with_attributes[node] == 1 else f"{node} ({attribute})"
        selected = frame.xs((node, attribute), axis=1, level=("node", "attribute"))
        series = pd.DataFrame(
            {
                position[simulation]: selected.xs(simulation, axis=1, level="simulation").iloc[:, 0]
                for simulation in selected.columns.get_level_values("simulation").unique()
            }
        ).sort_index(axis=1)
        series.index.name = "time"
        file = f"{number:04d}_{_safe_name(name)}.csv"
        series.to_csv(run_dir / "recorders" / file)
        index_rows.append(
            {"name": name, "type": attribute, "file": f"recorders/{file}", "traces": series.shape[1]}
        )
        for combination, value in series.mean().items():
            summary_rows.append((name, int(combination), float(value)))

    pd.DataFrame(index_rows, columns=["name", "type", "file", "traces"]).to_csv(
        run_dir / "index.csv", index=False
    )
    pd.DataFrame(summary_rows, columns=["recorder", "scenario", "value"]).to_csv(
        run_dir / "summary.csv", index=False
    )
    scenarios.to_csv(run_dir / "scenarios.csv")

    pywr_version = None
    try:
        from pywr_editor.dialects.next.validation import schema_info

        pywr_version = schema_info()["pywr_version"]
    except Exception:
        pass
    with open(run_dir / METADATA_FILE, "w") as file:
        json.dump(
            {
                "format": SOURCE,
                "model_file": str(model_file) if model_file else None,
                "saved": datetime.now().isoformat(timespec="seconds"),
                "completed": completed,
                "last_timestep": str(frame.index[-1]),
                "solver": solver,
                "pywr_version": pywr_version,
                "recorders": len(index_rows),
                "skipped": {},
                "summary": "mean over the run",
            },
            file,
            indent=2,
        )
    # the wide files are only a step towards the files of the viewer
    for name in (WIDE_FILE, SCENARIOS_FILE):
        (run_dir / name).unlink(missing_ok=True)
    return True
