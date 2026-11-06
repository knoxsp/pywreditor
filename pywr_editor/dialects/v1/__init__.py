from datetime import datetime
from typing import Any

from pywr_editor.dialects.base import ComponentKind, ModelDialect
from pywr_editor.model.constants import Constants


def _scenarios_dialog() -> type:
    from pywr_editor.dialogs import ScenariosDialog

    return ScenariosDialog


def _tables_dialog() -> type:
    from pywr_editor.dialogs import TablesDialog

    return TablesDialog


def _parameters_dialog() -> type:
    from pywr_editor.dialogs import ParametersDialog

    return ParametersDialog


def _recorders_dialog() -> type:
    from pywr_editor.dialogs import RecordersDialog

    return RecordersDialog


class V1Dialect(ModelDialect):
    key = "v1"
    label = "pywr v1"

    _component_kinds = [
        ComponentKind(
            key="scenario",
            label="Scenarios",
            action_key="edit-scenarios",
            icon=":/toolbar/edit-scenarios",
            tooltip="Change the model scenarios",
            dialog_class=_scenarios_dialog,
            large_button=False,
        ),
        ComponentKind(
            key="table",
            label="Tables",
            action_key="edit-tables",
            icon=":/toolbar/edit-tables",
            tooltip="Add, modify and delete the model tables",
            dialog_class=_tables_dialog,
            shortcut="Ctrl+T",
        ),
        ComponentKind(
            key="parameter",
            label="Parameters",
            action_key="edit-parameters",
            icon=":/toolbar/edit-parameters",
            tooltip="Add, modify and delete the model parameters",
            dialog_class=_parameters_dialog,
            shortcut="Ctrl+P",
        ),
        ComponentKind(
            key="recorder",
            label="Recorders",
            action_key="edit-recorders",
            icon=":/toolbar/edit-recorders",
            tooltip="Add, modify and delete the model recorders",
            dialog_class=_recorders_dialog,
            shortcut="Ctrl+R",
        ),
    ]

    def component_kinds(self) -> list[ComponentKind]:
        """
        Returns the kinds of components edited in their own dialog.
        :return: The scenarios, tables, parameters and recorders.
        """
        return list(self._component_kinds)

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
