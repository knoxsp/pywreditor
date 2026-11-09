import re
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from pywr_editor.model.constants import Constants
from pywr_editor.model.edges import EdgeRecord, Edges
from pywr_editor.model.editor_tags import read_tag, write_tag
from pywr_editor.model.node_config import NodeConfig
from pywr_editor.model.nodes import Nodes

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 The model layer for pywr-next models. pywr-next keeps the components of a network in
 the "network" object; each component has its name, comment and (for nodes) position
 in its "meta" object, and edges are objects with "from_node" and "to_node".

 While a model is open, the editor data of a node (its style, colour and size) is
 kept in the dictionary with its position, as for pywr v1 models, and is moved to the
 sidecar file when the model is saved.
"""


def humanise_type(node_type: str | None) -> str:
    """
    Converts a pywr-next type such as "RiverSplitWithGauge" to "River split with
    gauge".
    :param node_type: The type.
    :return: The humanised type.
    """
    if not node_type:
        return "Unknown"
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", node_type)
    if not words:
        return node_type
    return " ".join([words[0]] + [w if w.isupper() else w.lower() for w in words[1:]])


class NextNodeConfig(NodeConfig):
    """A pywr-next node. Its name and position are in its "meta" object."""

    def _meta(self, create: bool = False) -> dict | None:
        meta = self.props.get("meta")
        if not isinstance(meta, dict):
            if not create:
                return None
            meta = self.props["meta"] = {}
        return meta

    def position_dict(self, create: bool = False) -> dict | None:
        """
        Returns the "position" object in the node's "meta".
        :param create: Whether to add an empty dictionary if the node has none.
        :return: The dictionary or None if the node does not have one.
        """
        meta = self._meta(create)
        if meta is None:
            return None
        position = meta.get("position")
        if not isinstance(position, dict):
            if not create:
                return None
            position = meta["position"] = {}
        return position

    def drop_empty_position(self) -> None:
        """
        Removes the position object when it is empty.
        :return: None
        """
        meta = self._meta()
        if meta is not None and meta.get("position") == {}:
            del meta["position"]

    def editor_value(self, key: str):
        """
        Returns a value the editor stores for the node, read from the node's tags.
        :param key: The key, such as "node_color".
        :return: The value (a number for the node size), None if not set.
        """
        value = read_tag(self._meta_tags(), key)
        if value is not None and key == Constants.NODE_SIZE_KEY.value:
            try:
                return float(value)
            except ValueError:
                return None
        return value

    def set_editor_value(self, key: str, value) -> None:
        """
        Sets or removes a value the editor stores for the node, in the node's tags.
        :param key: The key, such as "node_color".
        :param value: The value. None removes it.
        :return: None
        """
        meta = self._meta(create=value is not None)
        if meta is None:
            return
        tags = meta.get("tags")
        if not isinstance(tags, dict):
            if value is None:
                return
            tags = meta["tags"] = {}
        write_tag(tags, key, value)
        if not tags:
            del meta["tags"]

    def _meta_tags(self) -> dict | None:
        meta = self._meta()
        return None if meta is None else meta.get("tags")

    @property
    def name(self) -> str | None:
        """
        Returns the node name.
        :return: The name or None if the node has no valid name.
        """
        meta = self._meta()
        if meta is None or not isinstance(meta.get("name"), str):
            return None
        return meta["name"]

    def change_name(self, name: str) -> None:
        """
        Changes the node name.
        :param name: The new name.
        :return: None
        """
        self._meta(create=True)["name"] = name

    @property
    def comment(self) -> str | None:
        """
        Returns the node comment.
        :return: The comment or None if not set.
        """
        meta = self._meta()
        return None if meta is None else meta.get("comment")

    @property
    def is_virtual(self) -> bool:
        """
        pywr-next keeps the virtual nodes in their own list, so a node in the
        "nodes" list is never virtual.
        :return: False
        """
        return False

    @property
    def is_custom(self) -> bool:
        """
        pywr-next has no custom nodes.
        :return: False
        """
        return False

    @property
    def humanised_type(self) -> str:
        """
        Returns a user-friendly name of the node type.
        :return: The node type.
        """
        return humanise_type(self.props.get("type"))

    @staticmethod
    def create(name: str, node_type: str, position: Sequence[float]) -> dict:
        """
        Creates the dictionary of a new pywr-next node.
        :param name: The node name.
        :param node_type: The node type, such as "Link".
        :param position: The schematic position.
        :return: The node dictionary.
        """
        return {
            "meta": {
                "name": name,
                "position": {
                    Constants.POSITION_KEY.value: [
                        round(position[0], 4),
                        round(position[1], 4),
                    ]
                },
            },
            "type": node_type,
        }


@dataclass
class NextNodes(Nodes):
    """The nodes of a pywr-next network."""

    node_config_class = NextNodeConfig

    def get_all(self) -> list[dict]:
        """
        Returns the list of the nodes.
        :return: The node dictionaries.
        """
        return self.model.json["network"]["nodes"]

    def update(self, node_dict: dict) -> None:
        """
        Replaces the dictionary of an existing node, keeping its position and editor
        data.
        :param node_dict: The new node dictionary.
        :return: None
        """
        name = self.node(node_dict).name
        if name is None:
            raise ValueError("The node must have a name")
        node_index = self.find_node_index_by_name(name)
        if node_index is None:
            return
        position = self.node(self.get_all()[node_index]).position_dict()
        new_node = deepcopy(node_dict)
        if position is not None:
            self.node(new_node).position_dict(create=True).update(position)
        self.get_all()[node_index] = new_node
        self.model.has_changed()

    def rename_references(self, node_name: str, new_name: str) -> None:
        """
        Renames the references to a node in the other components.
        :param node_name: The node name to change.
        :param new_name: The new node name.
        :return: None
        """
        from pywr_editor.dialects.next.references import rename_references

        rename_references(self.model.json, "node", node_name, new_name)


@dataclass
class VirtualNodes:
    """The virtual nodes of a pywr-next network, which are not on the schematic."""

    model: "ModelConfig"

    def get_all(self) -> list[dict]:
        """
        Returns the list of the virtual nodes.
        :return: The virtual node dictionaries.
        """
        nodes = self.model.json["network"].get("virtual_nodes")
        return nodes if isinstance(nodes, list) else []

    @property
    def names(self) -> list[str]:
        """
        Returns the names of the virtual nodes.
        :return: The list of names.
        """
        return [NextNodeConfig(node).name for node in self.get_all()]


@dataclass
class NextEdges(Edges):
    """The edges of a pywr-next network."""

    def get_all(self) -> list[dict]:
        """
        Returns the edges as stored in the model file.
        :return: The edge dictionaries.
        """
        return self.model.json["network"]["edges"]

    @staticmethod
    def _record(edge: dict) -> EdgeRecord:
        return EdgeRecord(
            edge.get("from_node"),
            edge.get("to_node"),
            edge.get("from_slot"),
            edge.get("to_slot"),
        )

    def records(self) -> list[EdgeRecord]:
        """
        Returns the edges as records.
        :return: The list of edge records.
        """
        return [self._record(edge) for edge in self.get_all() if isinstance(edge, dict)]

    def find(
        self, source_node_name: str, target_node_name: str
    ) -> tuple[dict, int] | tuple[None, None]:
        """
        Finds an edge and its index from the source and target node names.
        :param source_node_name: The name of the source node.
        :param target_node_name: The name of the target node.
        :return: The edge dictionary and its index, or None if not found.
        """
        for ei, edge in enumerate(self.get_all()):
            if (
                isinstance(edge, dict)
                and edge.get("from_node") == source_node_name
                and edge.get("to_node") == target_node_name
            ):
                return edge, ei
        return None, None

    def find_record(
        self, source_node_name: str, target_node_name: str
    ) -> EdgeRecord | None:
        """
        Finds the edge between two nodes.
        :param source_node_name: The name of the source node.
        :param target_node_name: The name of the target node.
        :return: The edge record or None if the nodes are not connected.
        """
        edge, _ = self.find(source_node_name, target_node_name)
        return None if edge is None else self._record(edge)

    def add(
        self,
        source_node_name: str,
        target_node_name: str,
        slot_source: dict | None = None,
        slot_target: dict | None = None,
    ) -> bool:
        """
        Adds a new edge.
        :param source_node_name: The name of the source node.
        :param target_node_name: The name of the target node.
        :param slot_source: The slot of the source node. Optional.
        :param slot_target: The slot of the target node. Optional.
        :return: True if the edge is added, False otherwise.
        """
        all_nodes = self.model.nodes.names
        if source_node_name not in all_nodes or target_node_name not in all_nodes:
            return False

        edge = {"from_node": source_node_name, "to_node": target_node_name}
        if slot_source is not None:
            edge["from_slot"] = slot_source
        if slot_target is not None:
            edge["to_slot"] = slot_target
        self.get_all().append(edge)
        self.model.has_changed()
        return True

    def delete(
        self,
        source_node_name: str | None = None,
        target_node_name: str | None = None,
    ) -> None:
        """
        Deletes the edges from a source node, to a target node, or between the two.
        :param source_node_name: The source node name. Optional.
        :param target_node_name: The target node name. Optional.
        :return: None
        """
        if source_node_name is None and target_node_name is None:
            return

        def matches(edge: dict) -> bool:
            return (
                source_node_name is None or edge.get("from_node") == source_node_name
            ) and (target_node_name is None or edge.get("to_node") == target_node_name)

        self.model.json["network"]["edges"] = [
            edge
            for edge in self.get_all()
            if not (isinstance(edge, dict) and matches(edge))
        ]
        self.model.has_changed()

    def rename_node(self, node_name: str, new_name: str) -> None:
        """
        Renames a node in the edges.
        :param node_name: The node name to change.
        :param new_name: The new node name.
        :return: None
        """
        for edge in self.get_all():
            if not isinstance(edge, dict):
                continue
            for key in ("from_node", "to_node"):
                if edge.get(key) == node_name:
                    edge[key] = new_name

    def slot(
        self,
        source_node_name: str,
        target_node_name: str,
        slot_pos: int,
    ) -> dict | None:
        """
        Returns the slot of the source (slot_pos 1) or target (slot_pos 2) node.
        :param source_node_name: The name of the source node.
        :param target_node_name: The name of the target node.
        :param slot_pos: 1 for the source node slot, 2 for the target node slot.
        :return: The slot or None if it is not set.
        """
        if slot_pos not in [1, 2]:
            raise ValueError("slot_pos can only be 1 or 2")
        edge, _ = self.find(source_node_name, target_node_name)
        if edge is None:
            return None
        return edge.get("from_slot" if slot_pos == 1 else "to_slot")

    def set_slot(
        self,
        source_node_name: str,
        target_node_name: str,
        slot_pos: int,
        slot: dict | None,
    ) -> None:
        """
        Sets or removes the slot of the source (slot_pos 1) or target (slot_pos 2)
        node.
        :param source_node_name: The name of the source node.
        :param target_node_name: The name of the target node.
        :param slot_pos: 1 for the source node slot, 2 for the target node slot.
        :param slot: The slot, such as {"type": "River"}. None removes it.
        :return: None
        """
        if slot_pos not in [1, 2]:
            raise ValueError("slot_pos can only be 1 or 2")
        edge, _ = self.find(source_node_name, target_node_name)
        if edge is None:
            return
        key = "from_slot" if slot_pos == 1 else "to_slot"
        if slot is None:
            edge.pop(key, None)
        else:
            edge[key] = slot
        self.model.has_changed()


class NamedComponents:
    """
    A list of named pywr-next components, such as the parameters or the tables of
    the network, or the local parameters of a node. Each component has its name in
    its "meta" and its type in "type" (or "format" for tables).
    """

    def __init__(
        self,
        model: "ModelConfig",
        key: str,
        kind: str,
        owner: dict | None = None,
    ):
        """
        :param model: The model configuration.
        :param key: The key of the list, such as "parameters".
        :param kind: The kind of the components for the references, such as
        "parameter" (see references.py).
        :param owner: The dictionary with the list. Defaults to the network; a node
        for its local parameters.
        """
        self.model = model
        self.key = key
        self.kind = kind
        self.owner = owner

    def _owner(self) -> dict:
        return self.owner if self.owner is not None else self.model.json["network"]

    def get_all(self) -> list[dict]:
        """
        Returns the components. The list is added to the model when missing.
        :return: The component dictionaries.
        """
        owner = self._owner()
        if not isinstance(owner.get(self.key), list):
            owner[self.key] = []
        return owner[self.key]

    @property
    def names(self) -> list[str]:
        """
        Returns the names of the components.
        :return: The list of names.
        """
        from pywr_editor.dialects.next.validation import component_name

        names = (component_name(item) for item in self._owner().get(self.key) or [])
        return [name for name in names if name is not None]

    @property
    def count(self) -> int:
        return len(self.names)

    def exists(self, name: str) -> bool:
        return name in self.names

    def find_index(self, name: str) -> int | None:
        """
        Returns the position of a component in the list.
        :param name: The component name.
        :return: The index, or None if there is no component with the name.
        """
        from pywr_editor.dialects.next.validation import component_name

        for index, item in enumerate(self._owner().get(self.key) or []):
            if component_name(item) == name:
                return index
        return None

    def config(self, name: str) -> dict | None:
        """
        Returns the dictionary of a component.
        :param name: The component name.
        :return: The dictionary, or None if there is no component with the name.
        """
        index = self.find_index(name)
        return None if index is None else self.get_all()[index]

    def add(self, component: dict) -> None:
        """
        Adds a component.
        :param component: The component dictionary, with its name in "meta".
        :return: None
        """
        from pywr_editor.dialects.next.validation import component_name

        name = component_name(component)
        if name is None:
            raise ValueError("The component must have a name in its meta")
        if self.exists(name):
            raise ValueError(f'A {self.kind} named "{name}" already exists')
        self.get_all().append(component)
        self.model.has_changed()

    def update(self, name: str, component: dict) -> None:
        """
        Replaces a component. When its name changes, the references to it are
        renamed too.
        :param name: The current name of the component.
        :param component: The new component dictionary.
        :return: None
        """
        from pywr_editor.dialects.next.validation import component_name

        index = self.find_index(name)
        if index is None:
            raise KeyError(f'There is no {self.kind} named "{name}"')
        new_name = component_name(component)
        if new_name != name:
            self.rename_references(name, new_name)
        self.get_all()[index] = component
        self.model.has_changed()

    def delete(self, name: str) -> None:
        """
        Deletes a component. The references to it are not changed.
        :param name: The component name.
        :return: None
        """
        index = self.find_index(name)
        if index is not None:
            components = self.get_all()
            del components[index]
            if not components:
                # do not leave an empty list in the model
                del self._owner()[self.key]
            self.model.has_changed()

    def references(self, name: str) -> list:
        """
        Returns the references to a component.
        :param name: The component name.
        :return: The list of Reference.
        """
        from pywr_editor.dialects.next.references import find_references

        return find_references(self.model.json, kind=self.kind, name=name)

    def rename_references(self, name: str, new_name: str) -> None:
        """
        Renames the references to a component.
        :param name: The current name.
        :param new_name: The new name.
        :return: None
        """
        if self.kind == "local parameter":
            # local parameter names are only unique within their node
            return
        from pywr_editor.dialects.next.references import rename_references

        rename_references(self.model.json, self.kind, name, new_name)
