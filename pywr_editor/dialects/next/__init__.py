from datetime import datetime
from typing import TYPE_CHECKING, Any

from pywr_editor.dialects.base import ComponentKind, ModelDialect

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig


ICONS = {
    "table": ":/toolbar/edit-tables",
    "time series": ":/toolbar/edit-tables",
    "parameter": ":/toolbar/edit-parameters",
    "metric set": ":/toolbar/edit-recorders",
    "output": ":/toolbar/edit-recorders",
}
""" The ribbon icons of the kinds of components """


NODE_GROUPS = (
    ("Core", ("Input", "Link", "Output")),
    ("Storage", ("Storage", "Reservoir", "PiecewiseStorage")),
    ("River", ("Catchment", "River", "RiverGauge", "RiverSplitWithGauge", "Abstraction")),
    ("Other", ("LossLink", "PiecewiseLink", "Delay", "WaterTreatmentWorks", "Turbine")),
)
""" The groups of node types in the node library, in order. A type that is not here
(from a later version of pywr-next) is shown after them """
NODE_SHAPES = {
    "Delay": "DelayNode",
    "WaterTreatmentWorks": "Works",
}
""" The schematic shapes of the node types that are not drawn with a shape of the same
name. The other types have their own shape, or the generic one """


def node_group_order(node_type: str) -> int:
    """
    Returns the position of the group of a node type, for sorting.
    :param node_type: The node type.
    :return: The position of the group in NODE_GROUPS and the position in it.
    """
    for number, (_, types) in enumerate(NODE_GROUPS):
        if node_type in types:
            return number * 100 + types.index(node_type)
    return len(NODE_GROUPS) * 100


def node_group(node_type: str) -> str:
    """
    Returns the name of the group of a node type in the node library.
    :param node_type: The node type.
    :return: The group name, "Other" if the type is not in a group.
    """
    for name, types in NODE_GROUPS:
        if node_type in types:
            return name
    return "Other"


def _list_kind(
    key: str,
    label: str,
    list_key: str,
    definition: str,
    dialog: str,
    shortcut: str | None = None,
) -> ComponentKind:
    """
    Returns a kind of component kept in a list of the network.
    :param key: The kind key, such as "parameter".
    :param label: The plural label, such as "Parameters".
    :param list_key: The key of the list in the network.
    :param definition: The schema definition of the components.
    :param dialog: The name of the dialog class in components_dialog.py.
    :param shortcut: The keyboard shortcut. Optional.
    :return: The component kind.
    """

    def dialog_class() -> type:
        from pywr_editor.dialogs.next_components import components_dialog

        return getattr(components_dialog, dialog)

    return ComponentKind(
        key=key,
        label=label,
        action_key=f"edit-{list_key.replace('_', '-')}",
        icon=ICONS[key],
        tooltip=f"Add, modify and delete the model {label.lower()}",
        dialog_class=dialog_class,
        shortcut=shortcut,
        list_key=list_key,
        definition=definition,
    )


class NextDialect(ModelDialect):
    key = "next"
    label = "pywr-next"
    time_key = "time"
    features = frozenset(["node-dialog", "run", "run-results", "metric-sets"])

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
        from pywr_editor.dialects.next.model import (
            NamedComponents,
            NextEdges,
            NextNodes,
            VirtualNodes,
        )
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

        self.move_appearance_to_tags(network)

        model.file = ModelFileInfo(model.json_file)
        model.nodes = NextNodes(model=model)
        model.edges = NextEdges(model=model)
        model.virtual_nodes = VirtualNodes(model=model)
        model.shapes = Shapes(model=model)
        model.gis_layers = GisLayers(model=model)
        model.parameters = NamedComponents(model, "parameters", "parameter")
        model.tables = NamedComponents(model, "tables", "table")
        model.time_series = NamedComponents(model, "time_series", "time series")
        model.metric_sets = NamedComponents(model, "metric_sets", "metric set")
        model.outputs = NamedComponents(model, "outputs", "output")
        # pywr v1 components that pywr-next does not have, or that are not
        # supported yet
        model.recorders = model.scenarios = model.includes = None

    def validate_model(
        self, model: "ModelConfig", include_orphans: bool = True
    ) -> list:
        """
        Runs the checks pywr-next makes when it loads a network and the schema cannot
        express (unique names, valid edges).
        :param model: The model configuration.
        :param include_orphans: Not used: pywr-next components are not orphaned.
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

    def component_kinds(self) -> list[ComponentKind]:
        """
        Returns the kinds of pywr-next components edited in their own dialog.
        :return: The list of component kinds.
        """

        def time_dialog() -> type:
            from pywr_editor.dialogs.next_domain.time_dialog import NextTimeDialog

            return NextTimeDialog

        def scenarios_dialog() -> type:
            from pywr_editor.dialogs.next_domain.scenarios_dialog import (
                NextScenariosDialog,
            )

            return NextScenariosDialog

        return [
            # these have no list in the network: the tree and the search skip them
            ComponentKind(
                key="time",
                label="Time",
                action_key="edit-time",
                icon=":/toolbar/edit-metadata",
                tooltip="Change the dates and the timestep of the model",
                dialog_class=time_dialog,
                shortcut="Ctrl+Shift+T",
                panel="Time and scenarios",
            ),
            ComponentKind(
                key="scenario domain",
                label="Scenarios",
                action_key="edit-scenario-domain",
                icon=":/toolbar/edit-scenarios",
                tooltip="Add, modify and delete the groups of scenarios",
                dialog_class=scenarios_dialog,
                shortcut="Ctrl+Shift+S",
                panel="Time and scenarios",
            ),
            _list_kind(
                "table", "Tables", "tables", "DataTable", "NextTablesDialog", "Ctrl+T"
            ),
            _list_kind(
                "time series",
                "Time series",
                "time_series",
                "TimeSeries",
                "NextTimeSeriesDialog",
            ),
            _list_kind(
                "parameter",
                "Parameters",
                "parameters",
                "Parameter",
                "NextParametersDialog",
                "Ctrl+P",
            ),
            _list_kind(
                "metric set",
                "Metric sets",
                "metric_sets",
                "MetricSet",
                "NextMetricSetsDialog",
            ),
            _list_kind("output", "Outputs", "outputs", "Output", "NextOutputsDialog"),
        ]

    def create_run_worker(self, run_widget, end_date, run_to_date):
        """
        Creates the worker that runs a pywr-next model with the runner service of
        pywr-next, in its own Python environment. The user is asked to install
        pywr-next when this is not done yet.
        :param run_widget: The run controls.
        :param end_date: The end date of the run.
        :param run_to_date: The run-to date.
        :return: The worker, or None if pywr-next is not installed.
        """
        from pywr_editor.dialects.next.runner import NextRunWorker
        from pywr_editor.dialogs.environments.install_dialog import ensure_pywr_next
        from pywr_editor.model.results import resolve_output_dir

        environment = ensure_pywr_next("run this model", run_widget.app)
        if environment is None:
            return None
        app = run_widget.app
        settings = app.editor_settings
        model_config = run_widget.model_config
        return NextRunWorker(
            model_dict=model_config.clean_json,
            model_file=model_config.json_file,
            python=str(environment.python),
            end_date=end_date,
            run_to_date=run_to_date,
            solver=settings.next_solver,
            results_dir=(
                str(resolve_output_dir(settings.output_dir, model_config.json_file))
                if settings.are_results_saved
                else None
            ),
        )

    def node_dialog_class(self) -> type:
        """
        Returns the dialog to edit a pywr-next node, generated from the schema.
        :return: The dialog class.
        """
        from pywr_editor.dialogs.node.next_node_dialog import NextNodeDialog

        return NextNodeDialog

    def node_types(self) -> dict[str, str]:
        """
        Returns the pywr-next node types from the bundled schema, grouped: the core
        nodes, the storage, the river nodes and the others.
        :return: The humanised name of each type, by type.
        """
        from pywr_editor.dialects.next.model import humanise_type
        from pywr_editor.dialects.next.schema import bundled_schema

        # a placeholder stands for a node that another tool fills in
        types = [t for t in bundled_schema().types("Node") if t != "Placeholder"]
        types.sort(key=lambda t: (node_group_order(t), t))
        return {node_type: humanise_type(node_type) for node_type in types}

    def node_shape_name(self, node_type: str) -> str:
        """
        Returns the name of the schematic shape of a node type.
        :param node_type: The node type.
        :return: The name of a class of pywr_editor.node_shapes.
        """
        return NODE_SHAPES.get(node_type, node_type)

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

    @staticmethod
    def move_appearance_to_tags(network: dict) -> None:
        """
        Moves the appearance of the nodes (colour, size, style) that an earlier
        version of the editor wrote in their "position" to their tags.
        :param network: The network dictionary, changed in place.
        :return: None
        """
        from pywr_editor.model.sidecar import NODE_EDITOR_KEYS, _move_to_tags

        for node in network["nodes"]:
            position = node["meta"].get("position")
            if not isinstance(position, dict):
                continue
            values = {k: position.pop(k) for k in NODE_EDITOR_KEYS if k in position}
            _move_to_tags(node, values)
            if not position:
                del node["meta"]["position"]

    def simple_time(self, time_section: dict) -> bool:
        """
        Checks whether the toolbar can edit the time of the model: plain dates and a
        timestep in days.
        :param time_section: The "time" dictionary.
        :return: True if the toolbar can edit the time.
        """
        from pywr_editor.dialects.next import time_domain

        return (
            time_domain.parse_time(time_section.get("start")) is not None
            and time_domain.parse_time(time_section.get("end")) is not None
            and not time_domain.has_time_of_day(time_section.get("start"))
            and not time_domain.has_time_of_day(time_section.get("end"))
            and self.timestep_days(time_section) is not None
        )

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
