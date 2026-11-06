import copy
import json
import math
import os
import shutil
from pathlib import Path

from pywr_editor.model.constants import Constants

"""
 The editor keeps its own data (the shapes drawn on the schematic, the size of the
 schematic, the style of the nodes, the map settings and the GIS layers) out of the
 model file, which only has what Pywr defines. The data is stored in a "sidecar" file,
 in a hidden folder next to the model:

    models/
    ├── model.json
    └── .pywr-editor/
        └── model.json.json      (the sidecar of model.json)

 The sidecar names the model it belongs to. While the model is open, the editor keeps
 the data in the model dictionary (in the "pywr_editor" key and in the "position" of
 the nodes, which is in their "meta" in pywr-next models) and separates it from the
 model when the model is saved, and merges it back when the model is loaded. Models
 that still contain the data (saved by previous versions of the editor) are read as
 they are, and are saved without it.
"""

SIDECAR_FOLDER = ".pywr-editor"
SIDECAR_VERSION = 1
GEOMETRY_KEY = "geographic_geometry"
""" key in a node entry where the GeoJSON geometry of the node is stored """
NODES_KEY = "nodes"
""" key in the sidecar where the data of the nodes is stored, by node name """
NODE_EDITOR_KEYS = (
    Constants.NODE_STYLE_KEY.value,
    Constants.EDGE_COLOR_KEY.value,
    Constants.NODE_COLOR_KEY.value,
    Constants.NODE_SIZE_KEY.value,
)
""" The keys in the "position" of a node that the editor stores """
RESERVED_KEYS = ("model", "version", NODES_KEY)


def _is_next(model: dict) -> bool:
    # pywr-next models keep the nodes in "network", with the name and the position
    # in their "meta"
    return isinstance(model.get("network"), dict)


def _model_nodes(model: dict) -> list | None:
    nodes = model["network"].get("nodes") if _is_next(model) else model.get("nodes")
    return nodes if isinstance(nodes, list) else None


def _node_name(node: dict, is_next: bool) -> object:
    if is_next:
        meta = node.get("meta")
        return meta.get("name") if isinstance(meta, dict) else None
    return node.get("name")


def _node_position(node: dict, is_next: bool, create: bool = False) -> dict | None:
    owner = node
    if is_next:
        owner = node.get("meta")
        if not isinstance(owner, dict):
            if not create:
                return None
            owner = node["meta"] = {}
    if create and "position" not in owner:
        owner["position"] = {}
    position = owner.get("position")
    return position if isinstance(position, dict) else None


def _with_position(node: dict, position: dict, is_next: bool) -> dict:
    # a copy of the node with the position replaced (removed when empty)
    clean_node = dict(node)
    owner = clean_node
    if is_next:
        owner = clean_node["meta"] = dict(node["meta"])
    if position:
        owner["position"] = position
    else:
        del owner["position"]
    return clean_node


CONTENT_KEYS = (
    Constants.SHAPES_KEY.value,
    Constants.NODE_TYPES_KEY.value,
    Constants.MAP_KEY.value,
    NODES_KEY,
)
""" The sidecar is only created when it has one of these. The schematic size alone
does not justify a file, as it is derived from the schematic """


def sidecar_path(json_file: str | os.PathLike) -> Path:
    """
    Returns the path to the sidecar of a model.
    :param json_file: The path to the model file.
    :return: The path. The file may not exist.
    """
    path = Path(json_file)
    return path.parent / SIDECAR_FOLDER / f"{path.name}.json"


def read_sidecar(json_file: str | os.PathLike) -> tuple[dict, str | None]:
    """
    Reads the sidecar of a model.
    :param json_file: The path to the model file.
    :return: The sidecar content and an error message. The content is empty if
    there is not a sidecar. The error is None unless the file cannot be read.
    """
    path = sidecar_path(json_file)
    if not path.exists():
        return {}, None
    try:
        with open(path, "r") as fid:
            data = json.load(fid)
        if not isinstance(data, dict):
            raise ValueError("the content must be a dictionary")
        return data, None
    except Exception as error:
        return {}, f"{type(error).__name__}: {error}"


def has_content(data: dict) -> bool:
    """
    Whether the editor data has something worth storing.
    :param data: The editor data (the content of the sidecar).
    :return: True if the data has shapes, styles, map settings or node data.
    """
    return any(data.get(key) for key in CONTENT_KEYS)


def write_sidecar(
    json_file: str | os.PathLike, data: dict, backup_existing: bool = False
) -> None:
    """
    Writes the sidecar of a model. Nothing is written when there is no data and no
    sidecar. The sidecar is removed when the data is empty, and so is its folder if
    nothing else is in it.
    :param json_file: The path to the model file.
    :param data: The editor data.
    :param backup_existing: Whether to keep a copy of the existing sidecar, which
    could not be read, in a ".bak" file before it is replaced.
    :return: None
    """
    path = sidecar_path(json_file)
    if not has_content(data):
        if path.exists() and not backup_existing:
            path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                # the folder is not empty
                pass
        return

    path.parent.mkdir(exist_ok=True)
    if backup_existing and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    payload = {"model": Path(json_file).name, "version": SIDECAR_VERSION}
    payload.update(data)
    # write the file in one go, so that a failure does not leave half of it
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w") as fid:
        json.dump(payload, fid, indent=2)
    os.replace(temporary, path)


def _centroid(geometry: dict) -> list[float] | None:
    # imported here as the node configuration needs the constants of this package
    from pywr_editor.model.node_config import NodeConfig

    return NodeConfig(
        {"position": {Constants.GEOGRAPHIC_KEY.value: geometry}}
    ).geographic_position


def split_model(model: dict) -> tuple[dict, dict]:
    """
    Separates the data of the editor from the model.
    :param model: The model dictionary as it is in the editor.
    :return: The dictionary to write in the model file, and the editor data to write
    in the sidecar. The model is not changed.
    """
    editor_key = Constants.EDITOR_CONFIG_KEY.value
    data = copy.deepcopy(model.get(editor_key, {}))
    if not isinstance(data, dict):
        data = {}
    nodes_data: dict[str, dict] = {}

    clean = {key: value for key, value in model.items() if key != editor_key}
    is_next = _is_next(model)
    nodes = _model_nodes(model)
    if nodes is not None:
        clean_nodes = []
        for node in nodes:
            position = _node_position(node, is_next) if isinstance(node, dict) else None
            if position is None:
                clean_nodes.append(node)
                continue

            position = dict(position)
            entry = {}
            for key in NODE_EDITOR_KEYS:
                if key in position:
                    entry[key] = position.pop(key)

            # a geometry (the footprint of a node) is not a Pywr position. The model
            # keeps its centroid
            geometry = position.get(Constants.GEOGRAPHIC_KEY.value)
            if isinstance(geometry, dict):
                entry[GEOMETRY_KEY] = copy.deepcopy(geometry)
                centroid = _centroid(geometry)
                if centroid is None:
                    del position[Constants.GEOGRAPHIC_KEY.value]
                else:
                    position[Constants.GEOGRAPHIC_KEY.value] = centroid

            clean_nodes.append(_with_position(node, position, is_next))

            name = _node_name(node, is_next)
            if entry and isinstance(name, str):
                nodes_data[name] = entry
        if is_next:
            clean["network"] = {**model["network"], "nodes": clean_nodes}
        else:
            clean["nodes"] = clean_nodes

    if nodes_data:
        data[NODES_KEY] = nodes_data
    return clean, data


def merge_editor_data(model: dict, data: dict) -> None:
    """
    Adds the editor data read from the sidecar to the model dictionary. The sidecar
    takes priority over data that is still in the model. The data of nodes that are
    not in the model is ignored.
    :param model: The model dictionary, changed in place.
    :param data: The content of the sidecar.
    :return: None
    """
    editor_key = Constants.EDITOR_CONFIG_KEY.value
    if not isinstance(model.get(editor_key), dict):
        model[editor_key] = {}
    for key, value in data.items():
        if key not in RESERVED_KEYS:
            model[editor_key][key] = value

    nodes_data = data.get(NODES_KEY)
    if not isinstance(nodes_data, dict):
        return
    is_next = _is_next(model)
    for node in _model_nodes(model) or []:
        if not isinstance(node, dict):
            continue
        name = _node_name(node, is_next)
        if not isinstance(name, str) or name not in nodes_data:
            continue
        entry = nodes_data[name]
        if not isinstance(entry, dict):
            continue
        position = _node_position(node, is_next, create=True)
        if position is None:
            continue

        for key in NODE_EDITOR_KEYS:
            if key in entry:
                position[key] = entry[key]

        # use the geometry only if the point in the model is still its centroid.
        # Otherwise the position was changed outside of the editor
        geometry = entry.get(GEOMETRY_KEY)
        if isinstance(geometry, dict):
            centroid = _centroid(geometry)
            point = position.get(Constants.GEOGRAPHIC_KEY.value)
            if (
                centroid is not None
                and isinstance(point, list)
                and len(point) == 2
                and all(
                    isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in point
                )
                and all(
                    math.isclose(a, b, abs_tol=1e-6) for a, b in zip(point, centroid)
                )
            ):
                position[Constants.GEOGRAPHIC_KEY.value] = geometry


def read_into_model(json_file: str | os.PathLike, model: dict) -> str | None:
    """
    Reads the sidecar of a model and merges it in the model dictionary.
    :param json_file: The path to the model file.
    :param model: The model dictionary, changed in place.
    :return: The error message if the sidecar cannot be read, None otherwise.
    """
    data, error = read_sidecar(json_file)
    if error is None and data:
        merge_editor_data(model, data)
    return error
