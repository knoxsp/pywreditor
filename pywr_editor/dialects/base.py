from abc import ABC, abstractmethod
from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

from pywr_editor.model.connection_rules import (
    ConnectionIssue,
    Endpoint,
    Role,
    check_connection,
)

if TYPE_CHECKING:
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QDialog, QWidget

    from pywr_editor.model import ModelConfig, NodeConfig

"""
 A dialect handles one model file format: pywr v1 or pywr-next. The editor detects
 the dialect when a model is opened and asks it for everything that depends on the
 format. The schematic, the map, the sidecar, the shapes, the styles and the undo
 history are shared by all dialects.

 The interface grows as each part of the editor is moved behind it.
"""


@dataclass(frozen=True)
class ComponentKind:
    """
    A kind of model component that is edited in its own dialog, such as the
    parameters or the tables. The main window adds a ribbon button for each kind of
    the model's dialect, and the components tree and the search show only these kinds.
    """

    key: str
    """ The identifier, such as "parameter" """
    label: str
    """ The plural name shown on the ribbon button, such as "Parameters" """
    action_key: str
    """ The key of the ribbon action, such as "edit-parameters" """
    icon: str
    """ The resource path of the ribbon icon """
    tooltip: str
    """ The tooltip of the ribbon button """
    dialog_class: Callable[[], type["QDialog"]]
    """ Returns the class of the dialog. The dialog is imported only when needed """
    shortcut: str | None = None
    """ The keyboard shortcut of the ribbon button, such as "Ctrl+P" """
    large_button: bool = True
    """ Whether the ribbon button is large or a small button in a column """
    panel: str | None = None
    """ The name of the ribbon panel for the button, when it is not in the "Settings"
    panel with the other kinds. The buttons of a panel are large """
    list_key: str | None = None
    """ For pywr-next components, the key of their list in the network (such as
    "parameters"). The components tree and the search then list them generically """
    definition: str | None = None
    """ For pywr-next components, their definition in the schema (such as
    "Parameter"), which gives the key with their type """

    def open_dialog(
        self,
        model: "ModelConfig",
        selected_name: str | None = None,
        parent: "QWidget | None" = None,
    ) -> "QDialog":
        """
        Opens the dialog of the components.
        :param model: The model configuration.
        :param selected_name: The name of the component to select. Optional.
        :param parent: The parent widget. Optional.
        :return: The dialog.
        """
        dialog = self.dialog_class()(
            model=model, selected_name=selected_name, parent=parent
        )
        dialog.show()
        return dialog


class ModelDialect(ABC):
    key: str
    """ A short identifier, such as "v1" """
    label: str
    """ The name shown to the user, such as "pywr v1" """
    can_open: bool = True
    """ Whether the editor can open models in this dialect yet """

    @classmethod
    @abstractmethod
    def detect(cls, model_json: Any) -> bool:
        """
        Checks whether a model dictionary is written in this dialect.
        :param model_json: The content of the model file.
        :return: True if the model is in this dialect, False otherwise.
        """

    @abstractmethod
    def empty_model(self) -> dict:
        """
        Returns the dictionary of a new empty model.
        :return: The model dictionary.
        """

    time_key: str
    """ The key of the model section with the start and end dates """

    @abstractmethod
    def setup_model(self, model: "ModelConfig") -> None:
        """
        Checks the structure of a loaded model and adds its components (nodes,
        edges...) to the ModelConfig. When the model cannot be used, this sets
        model.load_error.
        :param model: The model configuration with the loaded dictionary.
        :return: None
        """

    @abstractmethod
    def timestep_days(self, time_section: dict) -> int | None:
        """
        Returns the length of the time step in days.
        :param time_section: The model section with the dates and the time step.
        :return: The number of days or None if the time step is not in days.
        """

    @abstractmethod
    def set_timestep_days(self, time_section: dict, days: int) -> None:
        """
        Sets the length of the time step in days.
        :param time_section: The model section with the dates and the time step.
        :param days: The number of days.
        :return: None
        """

    features: frozenset[str] = frozenset()
    """ The editor features available for the models of this dialect:
     - "node-dialog": the dialog to edit a node (see node_dialog_class());
     - "node-data-panel": the dockable panel with the form of a node;
     - "imports": importing custom components from Python files;
     - "python-paths": folders added to the Python path to run the model;
     - "slots": the dialog to name the slots of the edges;
     - "orphaned-parameters": finding the parameters that nothing uses;
     - "run": the run controls (run, run to, step, stop), see create_run_worker();
     - "preflight": the check that loads the model with pywr v1 (validation dialog);
     - "run-results": the results of the last run, saved by the editor;
     - "run-inspector": the inspector of the pywr v1 model that is being run;
     - "console": the IPython console with the model loaded;
     - "metric-sets": the shortcuts to add nodes and parameters to metric sets;
     - "convert-to-next": the conversion of the model to pywr-next """

    def time_bounds(self, time_section: dict) -> "tuple[datetime, datetime] | None":
        """
        Returns the start and the end of the model with their time of day, for the
        formats that have one (the toolbar only shows the dates).
        :param time_section: The "time" dictionary.
        :return: The start and the end, or None if the model has no time of day or they
        are not valid.
        """
        return None

    def simple_time(self, time_section: dict) -> bool:
        """
        Checks whether the dates and the timestep of the model are edited in the
        toolbar, which has a date for the start and the end and a timestep in days.
        :param time_section: The time dictionary.
        :return: False if the model has a time of day or another kind of timestep,
        which the time dialog edits.
        """
        return True

    def supports(self, feature: str) -> bool:
        """
        Checks whether an editor feature is available for this dialect.
        :param feature: The feature, such as "run" (see features).
        :return: True if the feature is available, False otherwise.
        """
        return feature in self.features

    def node_dialog_class(self) -> type | None:
        """
        Returns the class of the dialog to edit a node.
        :return: The dialog class, or None if nodes cannot be edited.
        """
        return None

    supports_custom_nodes: bool = False
    """ Whether models can have custom node types imported from Python files """

    node_roles: dict[str, Role] = {}
    """ The role of the node types in the connection rules, by lowercase type without
    the "node" suffix. A type that is not here is not restricted """

    edge_issue_severity: Literal["error", "warning"] = "warning"
    """ How the validation reports an edge that is not allowed in an existing model.
    The editor never lets the user add one. It is an error if the model cannot be
    loaded by the runtime, a warning if the runtime accepts it """

    def connection_endpoint(self, node: "NodeConfig") -> Endpoint:
        """
        Describes a node for the connection rules.
        :param node: The node.
        :return: The end point.
        """
        return Endpoint(
            name=node.name,
            role=self.node_roles.get(node.key or ""),
            virtual=node.is_virtual,
            label=self.node_type_label(node),
        )

    def node_type_label(self, node: "NodeConfig") -> str:
        """
        Returns the type of a node as shown in messages.
        :param node: The node.
        :return: The type, such as "Output".
        """
        return node.humanised_type

    def connection_endpoints(self, model: "ModelConfig") -> dict[str, Endpoint]:
        """
        Describes the nodes of a model for the connection rules.
        :param model: The model.
        :return: The end points by node name.
        """
        endpoints = {}
        for props in model.nodes.get_all():
            node = model.nodes.node(props)
            if node.name is not None:
                endpoints[node.name] = self.connection_endpoint(node)
        return endpoints

    def check_connection(
        self, model: "ModelConfig", source_name: str, target_name: str
    ) -> ConnectionIssue | None:
        """
        Checks whether an edge between two nodes of the model can be added.
        :param model: The model.
        :param source_name: The name of the node the edge starts from.
        :param target_name: The name of the node the edge goes to.
        :return: The reason it cannot be added, or None if it can.
        """
        source = model.nodes.config(source_name, as_dict=False)
        target = model.nodes.config(target_name, as_dict=False)
        if source is None or target is None:
            return None
        return check_connection(
            self.connection_endpoint(source),
            self.connection_endpoint(target),
            model.edges.records(),
        )

    def node_shape_name(self, node_type: str) -> str:
        """
        Returns the name of the schematic shape of a node type.
        :param node_type: The node type.
        :return: The name of a class of pywr_editor.node_shapes. The generic shape is
        used if there is no class with this name.
        """
        return node_type

    @abstractmethod
    def node_types(self) -> dict[str, str]:
        """
        Returns the built-in node types, for the node library.
        :return: The label of each node type, by the type written in the model.
        """

    @abstractmethod
    def create_node(
        self, name: str, node_type: str, position: tuple[float, float]
    ) -> dict:
        """
        Returns the dictionary of a new node.
        :param name: The node name.
        :param node_type: The node type, as returned by node_types().
        :param position: The schematic position.
        :return: The node dictionary.
        """

    @abstractmethod
    def validate_model(
        self, model: "ModelConfig", include_orphans: bool = True
    ) -> list:
        """
        Runs the checks of the editor, which are quick.
        :param model: The model configuration.
        :param include_orphans: Whether to report the components nothing uses.
        :return: The list of Diagnostic.
        """

    def create_run_worker(
        self, run_widget: "QWidget", end_date: Any, run_to_date: Any
    ) -> "QObject | None":
        """
        Creates the worker that runs the model in its own thread. It has the signals
        and methods of the pywr v1 worker (PywrWorker).
        :param run_widget: The run controls, with the main window and settings.
        :param end_date: The end date of the run, as pandas Timestamp.
        :param run_to_date: The run-to date, as pandas Timestamp.
        :return: The worker, or None if the model cannot be run now (for example
        because the user did not install what it needs).
        """
        return None

    @abstractmethod
    def validate_schema(self, model_dict: dict) -> list:
        """
        Validates a model against the JSON Schema of the dialect. This may take a few
        seconds and is run in a thread.
        :param model_dict: The model dictionary, without the editor data.
        :return: The list of Diagnostic.
        """

    @abstractmethod
    def validation_note(self) -> str:
        """
        Describes what the validation checks, for the validation dialog.
        :return: The text.
        """

    def component_kinds(self) -> list[ComponentKind]:
        """
        Returns the kinds of components edited in their own dialog, in the order
        their ribbon buttons are shown.
        :return: The list of component kinds.
        """
        return []

    def component_kind(self, key: str) -> ComponentKind | None:
        """
        Returns a component kind from its key.
        :param key: The key, such as "parameter".
        :return: The component kind or None if the dialect does not have it.
        """
        for kind in self.component_kinds():
            if kind.key == key:
                return kind
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.key!r}>"
