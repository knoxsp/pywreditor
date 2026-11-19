import copy
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pywr_editor.model.sidecar import merge_editor_data, split_model, write_sidecar

"""
 The conversion of a pywr v1 model to a pywr-next model, which pywr-next does itself
 (pywr.convert_model_from_v1_json_string). The editor runs it with the Python of the
 pywr-next environment, as pywr v1 and pywr-next cannot be imported by the same
 Python, and adds to the result the editor data of the model (the shapes, the map, the
 GIS layers and the style of the nodes). No Qt in this module.
"""

CONVERT_PROGRAM = """\
import json, sys
from pywr import convert_model_from_v1_json_string

schema, errors = convert_model_from_v1_json_string(sys.stdin.read())
rows = []
for error in errors:
    inner = getattr(error, "error", None)
    rows.append(
        {
            "component": type(error).__name__,
            "name": getattr(error, "name", None),
            "attribute": getattr(error, "attr", None) or None,
            "error": type(inner).__name__ if inner is not None else None,
        }
    )
sys.stdout.write("\\n" + json.dumps({"model": json.loads(schema.to_json_string()), "errors": rows}))
"""
""" The program that converts a model, run with the Python of the pywr-next
environment. It reads the pywr v1 model from the standard input """

COMPONENTS = {
    "Parameter": "parameter",
    "Node": "node",
    "Table": "table",
    "Edge": "edge",
    "Scenarios": "scenarios",
    "Recorder": "recorder",
    "Metadata": "metadata",
    "Timestepper": "time",
}
""" The components a conversion error is about, from the name of its class """


@dataclass(frozen=True)
class ConversionError:
    """A component of the pywr v1 model that pywr-next could not convert."""

    component: str
    """ The kind of component: "parameter", "node", "table"... """
    name: str | None
    """ The name of the component """
    attribute: str | None
    """ The attribute that could not be converted, if the error is about one """
    error: str
    """ What went wrong, in words, such as "Unrecognised type" """


@dataclass
class ConversionResult:
    model: dict
    """ The pywr-next model dictionary, with the editor data of the original model """
    errors: list[ConversionError] = field(default_factory=list)


def humanise_error(name: str | None) -> str:
    """
    Turns the name of a conversion error class into words.
    :param name: The class name, such as "MissingAttribute".
    :return: The words, such as "Missing attribute".
    """
    if not name:
        return "Not converted"
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
    return words[:1].upper() + words[1:]


def convert_model(
    python: str, v1_model: dict, timeout: float = 300.0
) -> ConversionResult:
    """
    Converts a pywr v1 model to pywr-next.
    :param python: The Python interpreter of the pywr-next environment.
    :param v1_model: The model dictionary as it is in the editor, with its editor data.
    :param timeout: The seconds after which the conversion is stopped.
    :return: The converted model, with the editor data of the original, and the
    components that could not be converted.
    :raises RuntimeError: If the conversion failed as a whole.
    """
    clean, editor_data = split_model(v1_model)
    try:
        process = subprocess.run(
            [python, "-c", CONVERT_PROGRAM],
            input=json.dumps(clean),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"The conversion did not finish in {timeout:g} seconds")
    except OSError as error:
        raise RuntimeError(f"Python could not be started: {error}")
    if process.returncode != 0:
        raise RuntimeError(
            "pywr-next could not convert the model:\n"
            + (process.stderr or process.stdout).strip()
        )
    try:
        reply = json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise RuntimeError(
            "pywr-next did not return the converted model:\n"
            + (process.stderr or process.stdout).strip()
        )
    model = reply["model"]
    # the shapes, the map and the GIS layers, and the style of the nodes (which are
    # in the tags of the pywr-next nodes). The node names are the same
    merge_editor_data(model, editor_data)
    errors = [
        ConversionError(
            component=COMPONENTS.get(row["component"], row["component"].lower()),
            name=row["name"],
            attribute=row["attribute"],
            error=humanise_error(row["error"]),
        )
        for row in reply["errors"]
    ]
    return ConversionResult(model, errors)


def count_components(model: dict) -> dict[str, int]:
    """
    Counts the components of a pywr-next model, for the summary of a conversion.
    :param model: The pywr-next model dictionary.
    :return: The number of nodes, edges, parameters and tables.
    """
    network = model.get("network") or {}
    return {
        "nodes": len(network.get("nodes") or []),
        "edges": len(network.get("edges") or []),
        "parameters": len(network.get("parameters") or []),
        "tables": len(network.get("tables") or []),
    }


def default_file(v1_file: str | Path | None) -> Path | None:
    """
    Returns where the converted model is saved by default: next to the original, with
    "_next" added to its name, so that the files the model reads can be found.
    :param v1_file: The path of the pywr v1 model.
    :return: The path, None if the model has no file yet.
    """
    if not v1_file:
        return None
    v1_file = Path(v1_file)
    return v1_file.with_name(f"{v1_file.stem}_next{v1_file.suffix or '.json'}")


def save_converted_model(model: dict, path: str | Path) -> None:
    """
    Writes a converted model and its sidecar, as ModelConfig.save() does.
    :param model: The model dictionary with the editor data.
    :param path: The model file.
    :return: None
    """
    clean, editor_data = split_model(copy.deepcopy(model))
    write_sidecar(path, editor_data)
    with open(path, "w") as file:
        json.dump(clean, file, indent=2)
