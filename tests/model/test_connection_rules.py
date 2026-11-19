import pytest

from pywr_editor.model.connection_rules import (
    Endpoint,
    Role,
    check_connection,
    find_edge_issues,
    find_unrouted,
)
from pywr_editor.model.edges import EdgeRecord


def node(name: str, role: Role | None, virtual: bool = False) -> Endpoint:
    label = {Role.SOURCE: "Input", Role.SINK: "Output"}.get(role, "Link")
    return Endpoint(name, role, virtual, label)


INPUT = node("in", Role.SOURCE)
OUTPUT = node("out", Role.SINK)
LINK = node("link", Role.THROUGH)
STORE = node("store", Role.STORAGE)


@pytest.mark.parametrize(
    "source, target",
    [
        (INPUT, LINK),
        (INPUT, OUTPUT),
        (LINK, node("link2", Role.THROUGH)),
        (LINK, OUTPUT),
        (INPUT, STORE),
        (STORE, OUTPUT),
        (STORE, node("store2", Role.STORAGE)),
        (node("custom", None), node("custom2", None)),
    ],
)
def test_allowed(source, target):
    assert check_connection(source, target) is None


@pytest.mark.parametrize(
    "source, target, kind, text",
    [
        (OUTPUT, LINK, "from_sink", "nothing can flow out of it"),
        (OUTPUT, STORE, "from_sink", "an Output node"),
        (LINK, INPUT, "to_source", "no node can be connected to it"),
        (INPUT, node("in2", Role.SOURCE), "to_source", "an Input node"),
        (OUTPUT, node("out2", Role.SINK), "from_sink", "cannot be connected"),
        (LINK, LINK, "self", "to itself"),
        (LINK, node("v", Role.THROUGH, virtual=True), "virtual", "virtual node"),
        (node("v", None, virtual=True), LINK, "virtual", "virtual node"),
    ],
)
def test_refused(source, target, kind, text):
    issue = check_connection(source, target)
    assert issue is not None
    assert issue.kind == kind
    assert text in issue.message


def test_the_article_follows_the_type():
    catchment = Endpoint("c", Role.SOURCE, label="Catchment")
    assert "a Catchment node" in check_connection(LINK, catchment).message
    assert "an Input node" in check_connection(LINK, INPUT).message


def test_a_duplicate_is_refused_but_the_reverse_edge_is_not_a_duplicate():
    existing = [EdgeRecord("a", "b")]
    a, b = node("a", Role.THROUGH), node("b", Role.THROUGH)
    assert check_connection(a, b, existing).kind == "duplicate"
    assert check_connection(b, a, existing) is None
    assert check_connection(a, node("c", Role.THROUGH), existing) is None


def test_find_edge_issues_reports_each_bad_edge():
    endpoints = {e.name: e for e in (INPUT, LINK, OUTPUT)}
    edges = [
        EdgeRecord("in", "link"),
        EdgeRecord("link", "out"),
        EdgeRecord("out", "link"),  # out of a sink
        EdgeRecord("link", "in"),  # into a source
        EdgeRecord("in", "link"),  # duplicate
        EdgeRecord("link", "missing"),  # another check reports a missing node
    ]
    issues = [(i, issue.kind) for i, issue in find_edge_issues(endpoints, edges)]
    assert issues == [(2, "from_sink"), (3, "to_source"), (4, "duplicate")]


def test_unrouted_nodes():
    endpoints = {
        e.name: e
        for e in (INPUT, LINK, OUTPUT, node("dead_end", Role.THROUGH), STORE)
    }
    # in -> link -> out is a route; dead_end only receives; the storage has no edge
    edges = [
        EdgeRecord("in", "link"),
        EdgeRecord("link", "out"),
        EdgeRecord("link", "dead_end"),
    ]
    assert find_unrouted(endpoints, edges) == ["dead_end"]


def test_an_edge_that_is_not_allowed_does_not_make_a_route():
    endpoints = {e.name: e for e in (INPUT, LINK, OUTPUT)}
    # the only edge into the sink is out of the sink's own side: no flow reaches link
    edges = [EdgeRecord("out", "link"), EdgeRecord("link", "in")]
    assert find_unrouted(endpoints, edges) == ["in", "link", "out"]


def test_storage_is_a_source_and_a_sink():
    endpoints = {e.name: e for e in (INPUT, STORE, LINK, OUTPUT)}
    edges = [EdgeRecord("in", "store"), EdgeRecord("store", "link"), EdgeRecord("link", "out")]
    assert find_unrouted(endpoints, edges) == []


def test_isolated_and_virtual_nodes_are_not_reported():
    endpoints = {
        "alone": node("alone", Role.THROUGH),
        "virtual": node("virtual", None, virtual=True),
        "unknown": node("unknown", None),
    }
    assert find_unrouted(endpoints, []) == []
    assert find_unrouted(endpoints, [EdgeRecord("alone", "unknown")]) == ["alone"]
