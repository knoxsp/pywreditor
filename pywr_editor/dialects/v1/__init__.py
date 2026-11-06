from datetime import datetime
from typing import Any

from pywr_editor.dialects.base import ModelDialect
from pywr_editor.model.constants import Constants


class V1Dialect(ModelDialect):
    key = "v1"
    label = "pywr v1"

    @classmethod
    def detect(cls, model_json: Any) -> bool:
        """
        Any model that is not in another dialect is read as a pywr v1 model, so that
        the v1 validation reports what is wrong with it.
        :param model_json: The content of the model file.
        :return: Always True.
        """
        return True

    def empty_model(self) -> dict:
        """
        Returns the dictionary of a new empty pywr v1 model.
        :return: The model dictionary.
        """
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
        return {
            "metadata": {
                "minimum_version": 0.1,
                "title": "New model",
                "description": f"Model created on {current_time}",
            },
            "includes": [],
            "timestepper": {"start": "2000-1-1", "end": "2000-12-31", "timestep": 1},
            "scenarios": [],
            "nodes": [],
            "edges": [],
            "tables": {},
            "recorders": {},
            Constants.EDITOR_CONFIG_KEY.value: {Constants.SHAPES_KEY.value: []},
        }
