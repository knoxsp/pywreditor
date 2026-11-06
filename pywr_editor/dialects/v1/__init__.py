from datetime import datetime
from typing import TYPE_CHECKING, Any

from pywr_editor.dialects.base import ComponentKind, ModelDialect
from pywr_editor.model.constants import Constants

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig


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

    time_key = "timestepper"
    features = frozenset(
        [
            "node-dialog",
            "node-data-panel",
            "imports",
            "python-paths",
            "slots",
            "orphaned-parameters",
            "run",
            "console",
        ]
    )
    supports_custom_nodes = True

    def validate_model(self, model: "ModelConfig") -> list:
        """
        Runs the checks of the editor on a pywr v1 model.
        :param model: The model configuration.
        :return: The list of Diagnostic.
        """
        from pywr_editor.model.validation import validate_model

        return validate_model(model)

    def validate_schema(self, model_dict: dict) -> list:
        """
        Validates a model against the bundled pywr-v1-schema.
        :param model_dict: The model dictionary, without the editor data.
        :return: The list of Diagnostic.
        """
        from pywr_editor.model.validation import validate_schema

        return validate_schema(model_dict)

    def validation_note(self) -> str:
        """
        Describes the checks against the pywr-v1-schema.
        :return: The text.
        """
        from pywr_editor.model.validation import schema_info

        info = schema_info()
        return (
            "The structure is checked against the pywr-v1-schema "
            f"{info['pywr_v1_schema_version']} "
            f"(for pywr {info['target_pywr_version']}) "
            "and by the editor."
        )

    def node_dialog_class(self) -> type:
        """
        Returns the dialog to edit a pywr v1 node.
        :return: The dialog class.
        """
        from pywr_editor.dialogs import NodeDialog

        return NodeDialog

    def node_types(self) -> dict[str, str]:
        """
        Returns the pywr v1 nodes.
        :return: The node names, by node class.
        """
        from pywr_editor.model import PywrNodesData

        return {item["class"]: item["name"] for item in PywrNodesData().data.values()}

    def create_node(
        self, name: str, node_type: str, position: tuple[float, float]
    ) -> dict:
        """
        Returns the dictionary of a new pywr v1 node. pywr v1 types are lowercase.
        :param name: The node name.
        :param node_type: The node class, such as "Link".
        :param position: The schematic position.
        :return: The node dictionary.
        """
        from pywr_editor.model import NodeConfig

        return NodeConfig.create(
            name=name, node_type=node_type.lower(), position=position
        )

    def setup_model(self, model: "ModelConfig") -> None:
        """
        Adds the missing sections, checks the model and adds its components.
        :param model: The model configuration with the loaded dictionary.
        :return: None
        """
        model.setup_v1_model()

    def timestep_days(self, time_section: dict) -> int | None:
        """
        Returns the time step, which is a number of days in pywr v1.
        :param time_section: The "timestepper" dictionary.
        :return: The number of days or None if not set.
        """
        timestep = time_section.get("timestep")
        if isinstance(timestep, int) and not isinstance(timestep, bool):
            return timestep
        return None

    def set_timestep_days(self, time_section: dict, days: int) -> None:
        """
        Sets the time step.
        :param time_section: The "timestepper" dictionary.
        :param days: The number of days.
        :return: None
        """
        time_section["timestep"] = days

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
