from dataclasses import dataclass
from typing import Any, Iterator

from pywr_editor.dialects.next.validation import component_from_path

"""
 References between the components of a pywr-next model. Unlike pywr v1, where a
 reference is a string that may or may not be a component name, pywr-next references
 are typed, so they can be found and renamed exactly:
   - metrics: {"type": "Node" | "VirtualNode" | "Parameter" | "TimeSeries", "name": ...}
     and {"type": "Table", "table": ...}; a local parameter is referenced by its name
     and, when it belongs to another node, the name of that node in "node"; an edge
     metric names its nodes in "edge";
   - the members of a virtual node: {"name": ...} in its "nodes" and "storage_nodes";
   - the metric sets of an output: a name, or a list of names, in "metric_set".
 The edges of the network are not references: they are part of the nodes they join.
"""

NAME_REFERENCE_TYPES = {
    "Node": "node",
    "VirtualNode": "virtual node",
    "Parameter": "parameter",
    "TimeSeries": "time series",
}
""" The metric types that reference a component by its "name" """


@dataclass(frozen=True)
class Reference:
    kind: str
    """ The kind of the referenced component: "node", "virtual node", "parameter",
    "local parameter", "table", "time series" or "metric set" """
    name: str
    """ The name of the referenced component """
    path: tuple[str | int, ...]
    """ The location of the name in the model dictionary """
    owner: tuple[str, str] | None
    """ The (kind, name) of the component with the reference, if any """


@dataclass
class _Found:
    kind: str
    container: dict | list
    key: str | int

    @property
    def name(self) -> Any:
        return self.container[self.key]


def _walk(node: Any, path: tuple, in_virtual_node: bool) -> Iterator[tuple]:
    if isinstance(node, dict):
        ref_type = node.get("type")
        if ref_type in NAME_REFERENCE_TYPES and "name" in node:
            yield path + ("name",), _Found(NAME_REFERENCE_TYPES[ref_type], node, "name")
        elif ref_type == "LocalParameter":
            if "name" in node:
                yield path + ("name",), _Found("local parameter", node, "name")
            if "node" in node:
                yield path + ("node",), _Found("node", node, "node")
        elif ref_type == "Table" and "table" in node:
            yield path + ("table",), _Found("table", node, "table")
        elif ref_type == "Edge" and isinstance(node.get("edge"), dict):
            edge = node["edge"]
            for key in ("from_node", "to_node"):
                if key in edge:
                    yield path + ("edge", key), _Found("node", edge, key)

        for key, value in node.items():
            if in_virtual_node and key in ("nodes", "storage_nodes"):
                if isinstance(value, list):
                    for i, member in enumerate(value):
                        if isinstance(member, dict) and "name" in member:
                            yield path + (key, i, "name"), _Found(
                                "node", member, "name"
                            )
                continue
            if key == "metric_set" and len(path) >= 2 and path[1] == "outputs":
                if isinstance(value, str):
                    yield path + (key,), _Found("metric set", node, key)
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, str):
                            yield path + (key, i), _Found("metric set", value, i)
                continue
            # the members of a virtual node are its direct "nodes" key only
            yield from _walk(value, path + (key,), False)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk(item, path + (i,), False)


def _iter_references(model: dict) -> Iterator[tuple[tuple, _Found]]:
    network = model.get("network") if isinstance(model, dict) else None
    if not isinstance(network, dict):
        return
    for key, value in network.items():
        # the edges join the nodes and are not references to them
        if key == "edges" or not isinstance(value, list):
            continue
        for i, item in enumerate(value):
            yield from _walk(
                item, ("network", key, i), in_virtual_node=key == "virtual_nodes"
            )


def find_references(
    model: dict, kind: str | None = None, name: str | None = None
) -> list[Reference]:
    """
    Finds the references between the components of a pywr-next model.
    :param model: The model dictionary.
    :param kind: Only return the references to this kind of component. Optional.
    :param name: Only return the references to the component with this name.
    Optional.
    :return: The list of references.
    """
    references = []
    for path, found in _iter_references(model):
        if not isinstance(found.name, str):
            continue
        if (kind is None or found.kind == kind) and (
            name is None or found.name == name
        ):
            references.append(
                Reference(
                    kind=found.kind,
                    name=found.name,
                    path=path,
                    owner=component_from_path(model, path),
                )
            )
    return references


def rename_references(model: dict, kind: str, old_name: str, new_name: str) -> int:
    """
    Renames the references to a component. The component itself is not renamed.
    :param model: The model dictionary, changed in place.
    :param kind: The kind of the component, such as "node".
    :param old_name: The current name of the component.
    :param new_name: The new name.
    :return: The number of references changed.
    """
    if kind == "local parameter":
        # local parameter names are only unique within their node
        raise ValueError("The references to a local parameter cannot be renamed")
    # collect first, so that the model is not changed while it is walked
    to_change = [
        found
        for _, found in _iter_references(model)
        if found.kind == kind and found.name == old_name
    ]
    for found in to_change:
        found.container[found.key] = new_name
    return len(to_change)
