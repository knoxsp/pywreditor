from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Literal, Mapping, Sequence

from pywr_editor.model.edges import EdgeRecord

"""
 The rules for the connections between nodes, shared by pywr v1 and pywr-next.

 Neither JSON Schema says anything about connections (an edge is two names), so the
 editor keeps the rules itself. A dialect gives the role of each node type; the rules
 only use the roles:
  - nothing can flow out of a sink (an Output) or into a source (an Input, a
    Catchment), so an edge in that direction is dead: it can never be on a route from
    a source to a sink;
  - a node cannot be connected to itself, a virtual node cannot be connected, and the
    same edge cannot be added twice.
 pywr-next refuses these edges when it builds the network. pywr v1 accepts them, and
 the edge carries no flow. The editor does not allow either (dead links are not
 allowed). The roles are checked against the installed pywr by tests.
"""

IssueKind = Literal["self", "virtual", "from_sink", "to_source", "duplicate"]


class Role(Enum):
    """What a node type does to the flow, for the connection rules."""

    SOURCE = "source"
    """ Flow starts here: nothing can be connected to it (Input, Catchment) """
    SINK = "sink"
    """ Flow ends here: it cannot be connected to anything (Output) """
    THROUGH = "through"
    """ Flow passes through (Link and its variants) """
    STORAGE = "storage"
    """ Flow can come in and out (Storage, Reservoir) """


@dataclass(frozen=True)
class Endpoint:
    """A node, as the connection rules see it."""

    name: str
    role: Role | None
    """ None if the type is not known: the node is not restricted """
    virtual: bool = False
    label: str = "node"
    """ The type of the node as shown to the user, such as "Output" """


@dataclass(frozen=True)
class ConnectionIssue:
    """Why an edge is not allowed."""

    kind: IssueKind
    message: str


def _article(label: str) -> str:
    return "an" if label[:1].lower() in "aeiou" else "a"


def check_connection(
    source: Endpoint,
    target: Endpoint,
    existing: Iterable[EdgeRecord] = (),
    source_slot: Any = None,
    target_slot: Any = None,
) -> ConnectionIssue | None:
    """
    Checks whether a new edge can be added.
    :param source: The node the edge starts from.
    :param target: The node the edge goes to.
    :param existing: The edges of the model, to find a duplicate.
    :param source_slot: The slot of the source node the edge uses, if any. Two edges
    between the same nodes that use different slots are different connections.
    :param target_slot: The slot of the target node the edge uses, if any.
    :return: The reason the edge is not allowed, or None if it is.
    """
    if source.name == target.name:
        return ConnectionIssue(
            "self", f'The node "{source.name}" cannot be connected to itself'
        )
    for end in (source, target):
        if end.virtual:
            return ConnectionIssue(
                "virtual",
                f'The {end.label} node "{end.name}" is a virtual node, which cannot '
                "be connected",
            )
    if source.role == Role.SINK:
        return ConnectionIssue(
            "from_sink",
            f'"{source.name}" is {_article(source.label)} {source.label} node: nothing can flow out of it, '
            "so it cannot be connected to another node",
        )
    if target.role == Role.SOURCE:
        return ConnectionIssue(
            "to_source",
            f'"{target.name}" is {_article(target.label)} {target.label} node: it is where the flow starts, '
            "so no node can be connected to it",
        )
    if any(
        edge.source == source.name
        and edge.target == target.name
        and edge.source_slot == source_slot
        and edge.target_slot == target_slot
        for edge in existing
    ):
        return ConnectionIssue(
            "duplicate",
            f'"{source.name}" is already connected to "{target.name}"',
        )
    return None


def find_edge_issues(
    endpoints: Mapping[str, Endpoint], edges: Sequence[EdgeRecord]
) -> list[tuple[int, ConnectionIssue]]:
    """
    Finds the edges of a model that are not allowed. Edges with an end point that does
    not exist are not reported (they are another check).
    :param endpoints: The nodes of the model, by name.
    :param edges: The edges of the model.
    :return: The index of each edge that is not allowed with the reason. A duplicate
    is reported on the second and later copies.
    """
    issues = []
    for index, edge in enumerate(edges):
        source, target = endpoints.get(edge.source), endpoints.get(edge.target)
        if source is None or target is None:
            continue
        issue = check_connection(
            source, target, edges[:index], edge.source_slot, edge.target_slot
        )
        if issue is not None:
            issues.append((index, issue))
    return issues


def find_unrouted(
    endpoints: Mapping[str, Endpoint], edges: Sequence[EdgeRecord]
) -> list[str]:
    """
    Finds the nodes that are not on a route from a source to a sink, which pywr v1
    reports as an error when the model is run. Edges that are not allowed do not count.
    Nodes of unknown type and virtual nodes are not checked, and neither are the nodes
    with no edge at all (the model checks report those as not connected).
    :param endpoints: The nodes of the model, by name.
    :param edges: The edges of the model.
    :return: The names of the nodes, in the order of the model.
    """
    valid = [
        edge
        for edge in edges
        if edge.source in endpoints
        and edge.target in endpoints
        and check_connection(endpoints[edge.source], endpoints[edge.target]) is None
    ]
    downstream: dict[str, list[str]] = {}
    upstream: dict[str, list[str]] = {}
    for edge in valid:
        downstream.setdefault(edge.source, []).append(edge.target)
        upstream.setdefault(edge.target, []).append(edge.source)

    def reach(starts: list[str], links: dict[str, list[str]]) -> set[str]:
        seen = set(starts)
        queue = deque(starts)
        while queue:
            for name in links.get(queue.popleft(), []):
                if name not in seen:
                    seen.add(name)
                    queue.append(name)
        return seen

    supplied = reach(
        [n for n, e in endpoints.items() if e.role in (Role.SOURCE, Role.STORAGE)],
        downstream,
    )
    drained = reach(
        [n for n, e in endpoints.items() if e.role in (Role.SINK, Role.STORAGE)],
        upstream,
    )
    connected = {edge.source for edge in edges} | {edge.target for edge in edges}
    unrouted = []
    for name, endpoint in endpoints.items():
        if endpoint.virtual or endpoint.role is None or name not in connected:
            continue
        if endpoint.role == Role.STORAGE:
            # a storage always counts as a source and a sink: it is only on no route
            # when all its edges are not allowed
            on_route = name in downstream or name in upstream
        else:
            on_route = name in supplied and name in drained
        if not on_route:
            unrouted.append(name)
    return unrouted
