from datetime import datetime
from typing import TYPE_CHECKING, Any

from pywr_editor.dialects.base import ModelDialect

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig


class NextDialect(ModelDialect):
    key = "next"
    label = "pywr-next"
    time_key = "time"

    @classmethod
    def detect(cls, model_json: Any) -> bool:
        """
        pywr-next models keep the nodes in a "network" object. Models with several
        networks list them in "networks", and the networks they reference may be in
        their own files, with the nodes at the top level like in a pywr v1 model;
        these are told apart by the name of the nodes, which is in their "meta".
        :param model_json: The content of the model file.
        :return: True if the model is a pywr-next model, False otherwise.
        """
        if not isinstance(model_json, dict):
            return False
        return (
            isinstance(model_json.get("network"), dict)
            or cls.is_multi_network(model_json)
            or cls.is_network_file(model_json)
        )

    @staticmethod
    def is_multi_network(model_json: dict) -> bool:
        """
        Checks whether a pywr-next model has several networks.
        :param model_json: The model dictionary.
        :return: True if the model has several networks, False otherwise.
        """
        return isinstance(model_json.get("networks"), list)

    @staticmethod
    def is_network_file(model_json: dict) -> bool:
        """
        Checks whether the file has only a network, referenced by a multi-network
        model.
        :param model_json: The content of the file.
        :return: True if the file is a pywr-next network, False otherwise.
        """
        nodes = model_json.get("nodes")
        return (
            "network" not in model_json
            and "timestepper" not in model_json
            and isinstance(nodes, list)
            and len(nodes) > 0
            and all(isinstance(node, dict) and "meta" in node for node in nodes)
        )

    def empty_model(self) -> dict:
        """
        Returns the dictionary of a new empty pywr-next model.
        :return: The model dictionary.
        """
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
        return {
            "metadata": {
                "title": "New model",
                "description": f"Model created on {current_time}",
                "minimum_version": "2.0",
            },
            "time": {
                "start": "2000-01-01",
                "end": "2000-12-31",
                "timestep": {"type": "Days", "days": 1},
            },
            "network": {"nodes": [], "edges": []},
        }

    def setup_model(self, model: "ModelConfig") -> None:
        """
        Checks the structure the editor relies on and adds the components of a
        pywr-next model. The rest of the model is checked by the validation.
        :param model: The model configuration with the loaded dictionary.
        :return: None
        """
        from pywr_editor.dialects.next.model import NextEdges, NextNodes, VirtualNodes
        from pywr_editor.model import GisLayers, ModelFileInfo, Shapes
        from pywr_editor.model.constants import Constants

        json = model.json
        if self.is_multi_network(json):
            model.load_error = (
                "This is a pywr-next model with several networks. The editor cannot "
                + "open these models yet"
            )
            return
        if self.is_network_file(json):
            model.load_error = (
                "This file has a pywr-next network that is part of a model with "
                + "several networks. Open the model file instead"
            )
            return

        network = json["network"]
        for key in ["nodes", "edges"]:
            network.setdefault(key, [])
            if not isinstance(network[key], list):
                model.load_error = f'The "network.{key}" value must be a list'
                return
        for ni, node in enumerate(network["nodes"]):
            meta = node.get("meta") if isinstance(node, dict) else None
            if not isinstance(meta, dict) or not isinstance(meta.get("name"), str):
                model.load_error = f"The node at position {ni + 1} has no name"
                return
            if not isinstance(node.get("type"), str):
                model.load_error = f'The node "{meta["name"]}" has no type'
                return
        for ei, edge in enumerate(network["edges"]):
            if not isinstance(edge, dict) or not all(
                isinstance(edge.get(key), str) for key in ("from_node", "to_node")
            ):
                model.load_error = (
                    f"The edge at position {ei + 1} must have a 'from_node' and a "
                    + "'to_node'"
                )
                return
        if not isinstance(json.get(self.time_key), dict):
            json[self.time_key] = {}
        if not isinstance(json.get("metadata"), dict):
            json["metadata"] = {}
        # the editor data (shapes, map...) while the model is open
        json.setdefault(Constants.EDITOR_CONFIG_KEY.value, {})

        model.file = ModelFileInfo(model.json_file)
        model.nodes = NextNodes(model=model)
        model.edges = NextEdges(model=model)
        model.virtual_nodes = VirtualNodes(model=model)
        model.shapes = Shapes(model=model)
        model.gis_layers = GisLayers(model=model)
        # pywr v1 components that pywr-next does not have, or that are not
        # supported yet
        model.parameters = model.recorders = model.tables = None
        model.scenarios = model.includes = None

    def validate_model(self, model: "ModelConfig") -> list:
        """
        Runs the checks pywr-next makes when it loads a network and the schema cannot
        express (unique names, valid edges).
        :param model: The model configuration.
        :return: The list of Diagnostic.
        """
        from pywr_editor.dialects.next.validation import validate_network

        return validate_network(model.clean_json)

    def validate_schema(self, model_dict: dict) -> list:
        """
        Validates a model against the bundled pywr-next schema.
        :param model_dict: The model dictionary, without the editor data.
        :return: The list of Diagnostic.
        """
        from pywr_editor.dialects.next.validation import validate_schema

        return validate_schema(model_dict)

    def validation_note(self) -> str:
        """
        Describes the checks against the pywr-next schema.
        :return: The text.
        """
        from pywr_editor.dialects.next.validation import schema_info

        return (
            "The structure is checked against the schema of pywr "
            f"{schema_info()['pywr_version']} and by the editor."
        )

    def node_types(self) -> dict[str, str]:
        """
        Returns the pywr-next node types from the bundled schema.
        :return: The humanised name of each type, by type.
        """
        from pywr_editor.dialects.next.model import humanise_type
        from pywr_editor.dialects.next.schema import bundled_schema

        return {
            node_type: humanise_type(node_type)
            for node_type in bundled_schema().types("Node")
            # a placeholder stands for a node that another tool fills in
            if node_type != "Placeholder"
        }

    def create_node(
        self, name: str, node_type: str, position: tuple[float, float]
    ) -> dict:
        """
        Returns the dictionary of a new pywr-next node.
        :param name: The node name.
        :param node_type: The node type, such as "Link".
        :param position: The schematic position.
        :return: The node dictionary.
        """
        from pywr_editor.dialects.next.model import NextNodeConfig

        return NextNodeConfig.create(name=name, node_type=node_type, position=position)

    def timestep_days(self, time_section: dict) -> int | None:
        """
        Returns the time step when it is a number of days.
        :param time_section: The "time" dictionary.
        :return: The number of days, or None if the time step is in hours or is
        a frequency.
        """
        timestep = time_section.get("timestep")
        if isinstance(timestep, dict) and timestep.get("type") == "Days":
            days = timestep.get("days")
            if isinstance(days, int) and not isinstance(days, bool):
                return days
        return None

    def set_timestep_days(self, time_section: dict, days: int) -> None:
        """
        Sets the time step to a number of days.
        :param time_section: The "time" dictionary.
        :param days: The number of days.
        :return: None
        """
        time_section["timestep"] = {"type": "Days", "days": days}
