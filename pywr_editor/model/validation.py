import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from pywr_editor.model.pywr_nodes_data import PywrNodesData
from pywr_editor.model.pywr_parameters_data import PywrParametersData
from pywr_editor.model.pywr_recorders_data import PywrRecordersData

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 Validation of a model before it is run. Checks are split in two layers:
  1. the structural check against the bundled pywr-v1-schema JSON Schema;
  2. the checks owned by the editor, which cover what the schema does not validate
     (references between components, unique names, edge end points, external files
     and orphaned components).
 Neither layer guarantees that the model solves at every time-step. See
 pywr_editor.model.preflight for the check that loads the model using pywr.
"""

SCHEMA_DIR = Path(__file__).parent / "schemas"
Severity = Literal["error", "warning"]
Source = Literal["schema", "model"]

# node keys that pywr reads as parameter names when they are strings
NODE_PARAMETER_KEYS = [
    "max_flow",
    "min_flow",
    "cost",
    "max_volume",
    "min_volume",
    "level",
    "area",
]
MAX_VALUE_LENGTH = 80


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    source: Source
    message: str
    path: tuple[str | int, ...] = ()
    """ The location of the problem in the model dictionary """
    component: tuple[str, str] | None = None
    """ The (kind, name) of the component with the issue. The kind is one of
    "node", "parameter", "recorder", "table" or "scenario" """

    @property
    def path_str(self) -> str:
        """
        The path as a string, for example "nodes/3/max_flow".
        """
        return "/".join(str(p) for p in self.path)


def schema_info() -> dict:
    """
    Returns the version information of the bundled schema.
    :return: The dictionary stored in schemas/SOURCE.json.
    """
    return json.loads((SCHEMA_DIR / "SOURCE.json").read_text())


@lru_cache(maxsize=None)
def _validator(strict: bool) -> Draft202012Validator:
    """
    Loads a validator for the bundled schema.
    :param strict: Whether to load the strict schema, which does not accept an
    invalid core node or parameter as a custom type.
    :return: The validator.
    """
    name = "pywr-v1-model-strict" if strict else "pywr-v1-model"
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    return Draft202012Validator(schema)


def _shorten(text: str) -> str:
    # the schema messages embed the invalid value, which may be a whole node
    # or parameter dictionary
    if len(text) > MAX_VALUE_LENGTH * 2:
        return text[: MAX_VALUE_LENGTH * 2] + "..."
    return text


def component_from_path(
    model: dict, path: tuple[str | int, ...]
) -> tuple[str, str] | None:
    """
    Identifies the component a path belongs to.
    :param model: The model dictionary.
    :param path: The path in the model dictionary.
    :return: The (kind, name) of the component or None if the path is not in a
    component.
    """
    if len(path) < 2:
        return None
    section, key = path[0], path[1]
    kinds = {
        "parameters": "parameter",
        "recorders": "recorder",
        "tables": "table",
        "nodes": "node",
        "scenarios": "scenario",
    }
    if section not in kinds:
        return None
    if isinstance(key, int):
        try:
            item = model[section][key]
        except (KeyError, IndexError, TypeError):
            return None
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            return kinds[section], item["name"]
        return None
    return kinds[section], str(key)


def _leaf_errors(error) -> list:
    if not error.context:
        return [error]
    return [leaf for sub in error.context for leaf in _leaf_errors(sub)]


def _leaf_error(error):
    # anyOf/oneOf errors do not say which branch is the closest match. The branches
    # for the wrong node or parameter type fail early (a missing property, for
    # example), while the one for the right type fails deeper in the component.
    leaves = _leaf_errors(error)
    deepest = max(len(leaf.absolute_path) for leaf in leaves)
    return best_match([leaf for leaf in leaves if len(leaf.absolute_path) == deepest])


def validate_schema(model: dict, strict: bool = True) -> list[Diagnostic]:
    """
    Validates the model structure against the bundled pywr-v1-schema.

    Problems found by the standard schema are errors. The strict schema also reports
    core nodes and parameters that only pass because pywr reads them as a custom type
    when their core definition is invalid. These are warnings, as the component may
    be a valid custom one or use a feature the schema does not model yet.
    :param model: The model dictionary.
    :param strict: Whether to also run the strict schema. This doubles the time taken
    on a large model.
    :return: The list of diagnostics.
    """
    diagnostics: list[Diagnostic] = []
    reported: set[tuple] = set()

    for error in sorted(
        _validator(False).iter_errors(model),
        key=lambda e: [str(p) for p in e.absolute_path],
    ):
        leaf = _leaf_error(error)
        path = tuple(leaf.absolute_path)
        severity: Severity = "error"
        message = _shorten(leaf.message)
        if (
            len(path) == 4
            and path[0] == "nodes"
            and path[2:] == ("position", "geographic")
            and isinstance(leaf.instance, dict)
        ):
            # the editor stores the geographic position of a node that is not a
            # point as a GeoJSON geometry, which pywr reads as any other value
            severity = "warning"
            message = (
                "The geographic position is a GeoJSON geometry. The schema only "
                "accepts a [longitude, latitude] pair"
            )
        reported.add(path)
        diagnostics.append(
            Diagnostic(
                severity=severity,
                source="schema",
                message=message,
                path=path,
                component=component_from_path(model, path),
            )
        )

    if not strict:
        return diagnostics

    # The branch of a failed anyOf which best matches a core node or parameter is
    # not reliable, so strict findings only name the component
    for error in _validator(True).iter_errors(model):
        path = tuple(error.absolute_path)
        paths = [path]
        if path == ("parameters",):
            # the error is for the whole dictionary. Its context has the errors of
            # each invalid parameter
            paths = sorted(
                {
                    tuple(sub.absolute_path)[:2]
                    for sub in error.context
                    if len(sub.absolute_path) >= 2
                },
                key=str,
            )
        for path in paths:
            # skip components with an error from the standard schema
            if any(p[: len(path)] == path or path[: len(p)] == p for p in reported):
                continue
            component = component_from_path(model, path)
            if component is None:
                message = _shorten(_leaf_error(error).message)
            else:
                kind, name = component
                message = (
                    f'The {kind} "{name}" does not match a core {kind} definition '
                    "and is read as a custom one"
                )
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    source="schema",
                    message=message,
                    path=path,
                    component=component,
                )
            )
    return diagnostics


def _iter_references(
    config: Any, path: tuple[str | int, ...], owner_type: str | None = None
) -> Iterator[tuple[tuple[str | int, ...], str, str, str | None]]:
    """
    Walks a node, parameter or recorder configuration and yields the values pywr
    reads as the name of another component.
    :param config: The configuration, or a nested one.
    :param path: The path to the configuration.
    :param owner_type: The type of the closest component with a "type" key.
    :return: The (path, kind, name, owner_type) of each reference, where kind is one
    of "parameter", "node", "table" or "scenario".
    """
    if isinstance(config, list):
        for i, item in enumerate(config):
            yield from _iter_references(item, path + (i,), owner_type)
        return
    if not isinstance(config, dict):
        return

    if isinstance(config.get("type"), str):
        owner_type = config["type"]
    for key, value in config.items():
        sub_path = path + (key,)
        if key == "parameter" and isinstance(value, str):
            yield sub_path, "parameter", value, owner_type
        elif key == "parameters" and isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    yield sub_path + (i,), "parameter", item, owner_type
        elif key in ("node", "storage_node") and isinstance(value, str):
            yield sub_path, "node", value, owner_type
        elif key == "table" and isinstance(value, str):
            yield sub_path, "table", value, owner_type
        elif key == "scenario" and isinstance(value, str):
            yield sub_path, "scenario", value, owner_type

        if isinstance(value, (dict, list)):
            yield from _iter_references(value, sub_path, owner_type)


def _iter_urls(
    config: Any, path: tuple[str | int, ...]
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(config, list):
        for i, item in enumerate(config):
            yield from _iter_urls(item, path + (i,))
    elif isinstance(config, dict):
        for key, value in config.items():
            if key in ("url", "h5file") and isinstance(value, str):
                yield path + (key,), value
            elif isinstance(value, (dict, list)):
                yield from _iter_urls(value, path + (key,))


def validate_model(
    model_config: "ModelConfig", include_orphans: bool = True
) -> list[Diagnostic]:
    """
    Runs the checks owned by the editor, which the schema does not cover.
    :param model_config: The model configuration.
    :param include_orphans: Whether to report orphaned nodes and parameters
    as warnings.
    :return: The list of diagnostics.
    """
    model = model_config.json
    diagnostics: list[Diagnostic] = []

    def add(severity: Severity, message: str, path: tuple):
        component = component_from_path(model, path)
        diagnostics.append(
            Diagnostic(
                severity=severity,
                source="model",
                message=message,
                path=path,
                component=component,
            )
        )

    def section(key: str, expected: type) -> Any:
        value = model.get(key)
        return value if isinstance(value, expected) else expected()

    # keep non-dictionary items so that the indexes match the model
    nodes = section("nodes", list)
    node_names = [
        n["name"]
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("name"), str)
    ]
    parameters = section("parameters", dict)
    recorders = section("recorders", dict)
    tables = section("tables", dict)
    scenarios = {
        s.get("name") for s in section("scenarios", list) if isinstance(s, dict)
    }

    # unique node names
    for name, count in Counter(node_names).items():
        if count > 1:
            first = next(
                i
                for i, n in enumerate(nodes)
                if isinstance(n, dict) and n.get("name") == name
            )
            add(
                "error",
                f'The node name "{name}" is used by {count} nodes. Node names '
                "must be unique",
                ("nodes", first, "name"),
            )

    # edges
    for i, edge in enumerate(section("edges", list)):
        if not isinstance(edge, list):
            continue
        for end in edge[:2]:
            if isinstance(end, str) and end not in node_names:
                add(
                    "error",
                    f'The edge connects the node "{end}", which does not exist',
                    ("edges", i),
                )

    # references between components
    core_types = [PywrNodesData(), PywrParametersData(), PywrRecordersData()]

    def check_references(config: Any, path: tuple, allow_node_parameters: bool):
        if allow_node_parameters and isinstance(config, dict):
            for key in NODE_PARAMETER_KEYS:
                if isinstance(config.get(key), str):
                    name = config[key]
                    if name not in parameters:
                        add(
                            "error",
                            f'"{key}" refers to the parameter "{name}", which '
                            "does not exist",
                            path + (key,),
                        )
        for ref_path, kind, name, owner_type in _iter_references(config, path):
            exists = {
                "parameter": name in parameters,
                "node": name in node_names,
                "table": name in tables,
                "scenario": name in scenarios,
            }[kind]
            if exists:
                continue
            # custom components may use these keys for something else. Only report an
            # error when pywr is sure to read the value as a component name
            is_core = owner_type is not None and any(
                data.exists(owner_type) for data in core_types
            )
            add(
                "error" if is_core else "warning",
                f'The {kind} "{name}" does not exist'
                + (
                    ""
                    if is_core
                    else " (unless the custom component uses it differently)"
                ),
                ref_path,
            )

    for i, node in enumerate(nodes):
        check_references(node, ("nodes", i), allow_node_parameters=True)
    for key, config in parameters.items():
        check_references(config, ("parameters", key), allow_node_parameters=False)
    for key, config in recorders.items():
        check_references(config, ("recorders", key), allow_node_parameters=False)

    # external files. These may be generated or mounted at run time, so they are
    # warnings
    for kind, items in (("tables", tables), ("parameters", parameters)):
        for key, config in items.items():
            for url_path, url in _iter_urls(config, (kind, key)):
                if url and not model_config.does_file_exist(url):
                    add("warning", f'The file "{url}" does not exist', url_path)
    for i, include in enumerate(section("includes", list)):
        if isinstance(include, str) and include.endswith(".py"):
            if not model_config.does_file_exist(include):
                add(
                    "warning",
                    f'The imported file "{include}" does not exist',
                    ("includes", i),
                )

    if include_orphans:
        for name in model_config.nodes.orphans() or []:
            idx = model_config.nodes.find_node_index_by_name(name)
            add(
                "warning",
                f'The node "{name}" is not connected to any other node',
                ("nodes", idx if idx is not None else 0, "name"),
            )
        for name in model_config.parameters.orphans() or []:
            add(
                "warning",
                f'The parameter "{name}" is not used by any component',
                ("parameters", name),
            )

    return diagnostics


def validate_all(model_config: "ModelConfig") -> list[Diagnostic]:
    """
    Runs the schema validation followed by the editor checks.
    :param model_config: The model configuration.
    :return: The diagnostics, errors first.
    """
    diagnostics = validate_schema(model_config.json) + validate_model(model_config)
    return sorted(diagnostics, key=lambda d: d.severity != "error")
