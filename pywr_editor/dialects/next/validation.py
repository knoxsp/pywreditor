import json
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from pywr_editor.model.validation import Diagnostic, _leaf_error, _shorten

"""
 Validation of pywr-next models: the structure is checked against the JSON Schema
 exported by pywr-next, then the editor checks what the schema cannot express, which
 pywr-next checks when it loads a model (duplicate names and invalid edges).
"""

SCHEMA_DIR = Path(__file__).parents[2] / "model" / "schemas"
SCHEMA_FILE = "pywr-next-model.schema.json"

COMPONENT_LISTS = {
    "nodes": "node",
    "virtual_nodes": "virtual node",
    "parameters": "parameter",
    "tables": "table",
    "time_series": "time series",
    "metric_sets": "metric set",
    "outputs": "output",
}
""" The lists of components in the network, with the kind of their items """


def schema_info() -> dict:
    """
    Returns the version information of the bundled pywr-next schema.
    :return: The dictionary stored in schemas/SOURCE-pywr-next.json.
    """
    return json.loads((SCHEMA_DIR / "SOURCE-pywr-next.json").read_text())


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMA_DIR / SCHEMA_FILE).read_text()))


def component_name(item: Any) -> str | None:
    """
    Returns the name of a pywr-next component, which is stored in its "meta".
    :param item: The component dictionary.
    :return: The name or None if the component has no valid name.
    """
    if isinstance(item, dict) and isinstance(item.get("meta"), dict):
        name = item["meta"].get("name")
        if isinstance(name, str):
            return name
    return None


def component_from_path(
    model: dict, path: tuple[str | int, ...]
) -> tuple[str, str] | None:
    """
    Identifies the component a path belongs to.
    :param model: The model dictionary.
    :param path: The path in the model dictionary, such as
    ("network", "nodes", 3, "max_flow").
    :return: The (kind, name) of the component or None if the path is not in a
    named component.
    """
    if len(path) < 3 or path[0] != "network" or path[1] not in COMPONENT_LISTS:
        return None
    try:
        name = component_name(model["network"][path[1]][path[2]])
    except (KeyError, IndexError, TypeError):
        return None
    return None if name is None else (COMPONENT_LISTS[path[1]], name)


def validate_schema(model: dict) -> list[Diagnostic]:
    """
    Validates the model structure against the bundled pywr-next schema.
    :param model: The model dictionary.
    :return: The list of diagnostics.
    """
    diagnostics = []
    for error in sorted(
        _validator().iter_errors(model),
        key=lambda e: [str(p) for p in e.absolute_path],
    ):
        leaf = _leaf_error(error)
        path = tuple(leaf.absolute_path)
        diagnostics.append(
            Diagnostic(
                severity="error",
                source="schema",
                message=_shorten(leaf.message),
                path=path,
                component=component_from_path(model, path),
            )
        )
    return diagnostics


def _components(network: dict, key: str) -> list:
    items = network.get(key)
    return items if isinstance(items, list) else []


def validate_network(model: dict) -> list[Diagnostic]:
    """
    Runs the checks that pywr-next makes when it loads a network and the schema
    cannot express: names must be unique, and edges must connect two different
    nodes that exist and are not virtual.
    :param model: The model dictionary.
    :return: The list of diagnostics.
    """
    network = model.get("network")
    if not isinstance(network, dict):
        return []
    diagnostics = []

    def duplicates(keys: list[str], label: str) -> None:
        counts = Counter(
            component_name(item)
            for key in keys
            for item in _components(network, key)
            if component_name(item) is not None
        )
        for name, count in sorted(counts.items()):
            if count > 1:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        source="model",
                        message=f'The {label} name "{name}" is used {count} times',
                        path=("network", keys[0]),
                        component=(COMPONENT_LISTS[keys[0]], name),
                    )
                )

    # nodes and virtual nodes share their names
    duplicates(["nodes", "virtual_nodes"], "node")
    for key in ["parameters", "tables", "time_series", "metric_sets"]:
        duplicates([key], COMPONENT_LISTS[key])

    node_names = {component_name(n) for n in _components(network, "nodes")}
    virtual_names = {component_name(n) for n in _components(network, "virtual_nodes")}
    for ei, edge in enumerate(_components(network, "edges")):
        if not isinstance(edge, dict):
            continue
        problems = []
        for key, end in [("from_node", "source"), ("to_node", "target")]:
            name = edge.get(key)
            if name in virtual_names:
                problems.append(f'The {end} node "{name}" is a virtual node')
            elif name not in node_names:
                problems.append(f'The {end} node "{name}" does not exist')
        if edge.get("from_node") == edge.get("to_node"):
            problems.append(
                f'The node "{edge.get("from_node")}" is connected to itself'
            )
        for problem in problems:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    source="model",
                    message=problem,
                    path=("network", "edges", ei),
                )
            )
    return diagnostics


def validate_all(model: dict) -> list[Diagnostic]:
    """
    Runs the schema validation followed by the network checks.
    :param model: The model dictionary.
    :return: The list of diagnostics.
    """
    return validate_schema(model) + validate_network(model)
