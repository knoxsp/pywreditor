from datetime import datetime
from typing import Any

from pywr_editor.dialects.base import ModelDialect


class NextDialect(ModelDialect):
    key = "next"
    label = "pywr-next"
    # the model layer for pywr-next is not implemented yet
    can_open = False

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
