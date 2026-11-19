import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 Shortcuts to put nodes and parameters in the metric sets of a pywr-next model
 without opening the metric sets dialog. A metric set has a list of "metrics", each
 like {"type": "Node", "name": "Reservoir", "attribute": "Volume"}, and a metric set
 outputs them when the model runs. No Qt in this module.
"""

NODE_ATTRIBUTES = (
    "Inflow",
    "Outflow",
    "Volume",
    "MaxVolume",
    "ProportionalVolume",
    "Loss",
    "Deficit",
    "Power",
    "Compensation",
    "Rainfall",
    "Evaporation",
    "Abstraction",
)
""" The attributes of a node that a metric can read, from the schema """

STORAGE_TYPES = ("Storage", "Reservoir", "RiverGauge")


def default_attribute(node_type: str | None, kind: str = "Node") -> str:
    """
    Returns the attribute most users want for a node.
    :param node_type: The node type, such as "Reservoir".
    :param kind: "Node" or "VirtualNode".
    :return: "Volume" for storage nodes, "Outflow" otherwise.
    """
    if node_type and any(word in node_type for word in STORAGE_TYPES):
        return "Volume"
    if kind == "VirtualNode" and node_type and "Storage" in node_type:
        return "Volume"
    return "Outflow"


def node_metric(name: str, attribute: str | None, kind: str = "Node") -> dict:
    """
    Builds the metric of a node or virtual node.
    :param name: The node name.
    :param attribute: The attribute. None leaves it out, so pywr-next uses its
    default.
    :param kind: "Node" or "VirtualNode".
    :return: The metric dictionary.
    """
    metric: dict[str, Any] = {"type": kind, "name": name}
    if attribute:
        metric["attribute"] = attribute
    return metric


def parameter_metric(name: str) -> dict:
    """
    Builds the metric of a parameter.
    :param name: The parameter name.
    :return: The metric dictionary.
    """
    return {"type": "Parameter", "name": name}


def _same_target(metric: Any, other: dict) -> bool:
    return (
        isinstance(metric, dict)
        and metric.get("type") == other.get("type")
        and metric.get("name") == other.get("name")
    )


def metrics_of(metric_set: dict) -> list[dict]:
    """
    Returns the metrics of a metric set.
    :param metric_set: The metric set dictionary.
    :return: The list of metrics, empty if there are none.
    """
    metrics = metric_set.get("metrics")
    return [m for m in metrics if isinstance(m, dict)] if isinstance(metrics, list) else []


def sets_containing(
    model: "ModelConfig", kind: str, name: str
) -> list[tuple[str, list[dict]]]:
    """
    Finds the metric sets that have a metric for a node or parameter.
    :param model: The model configuration.
    :param kind: "Node", "VirtualNode" or "Parameter".
    :param name: The name of the node or parameter.
    :return: The name of each metric set, with its metrics for the component.
    """
    target = {"type": kind, "name": name}
    found = []
    for metric_set in model.metric_sets.get_all():
        metrics = [m for m in metrics_of(metric_set) if _same_target(m, target)]
        if metrics:
            found.append((metric_set["meta"]["name"], metrics))
    return found


def describe_sets(sets: list[tuple[str, list[dict]]]) -> str:
    """
    Describes the metric sets of a component for the user.
    :param sets: The result of sets_containing().
    :return: The text, such as "Daily (Outflow), Monthly (Volume, Outflow)".
    """
    parts = []
    for name, metrics in sets:
        attributes = [m.get("attribute") or m.get("key") for m in metrics]
        attributes = [a for a in attributes if a]
        parts.append(f"{name} ({', '.join(attributes)})" if attributes else name)
    return ", ".join(parts)


def add_metrics(
    model: "ModelConfig", set_name: str, metrics: list[dict], create: bool = False
) -> int:
    """
    Adds metrics to a metric set, leaving out the ones it already has.
    :param model: The model configuration.
    :param set_name: The name of the metric set.
    :param metrics: The metrics to add.
    :param create: Create the metric set if the model has no set with this name.
    :return: The number of metrics added.
    """
    components = model.metric_sets
    current = components.config(set_name)
    if current is None:
        if not create:
            raise ValueError(f'The model has no metric set "{set_name}"')
        components.add({"meta": {"name": set_name}, "metrics": []})
        current = components.config(set_name)
    updated = copy.deepcopy(current)
    existing = metrics_of(updated)
    new_list = updated.get("metrics")
    new_list = list(new_list) if isinstance(new_list, list) else []
    added = 0
    for metric in metrics:
        if metric not in existing:
            new_list.append(copy.deepcopy(metric))
            existing.append(metric)
            added += 1
    if added:
        updated["metrics"] = new_list
        components.update(set_name, updated)
    return added


def remove_metrics(model: "ModelConfig", set_name: str, kind: str, name: str) -> int:
    """
    Removes the metrics of a node or parameter from a metric set.
    :param model: The model configuration.
    :param set_name: The name of the metric set.
    :param kind: "Node", "VirtualNode" or "Parameter".
    :param name: The name of the node or parameter.
    :return: The number of metrics removed.
    """
    current = model.metric_sets.config(set_name)
    if current is None:
        return 0
    target = {"type": kind, "name": name}
    metrics = current.get("metrics")
    if not isinstance(metrics, list):
        return 0
    kept = [m for m in metrics if not _same_target(m, target)]
    removed = len(metrics) - len(kept)
    if removed:
        updated = copy.deepcopy(current)
        updated["metrics"] = kept
        model.metric_sets.update(set_name, updated)
    return removed
