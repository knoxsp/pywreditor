import json

import pytest

from pywr_editor.dialects.next.references import find_references, rename_references
from tests.utils import model_path


def load(file: str) -> dict:
    return json.loads((model_path() / "pywr_next" / file).read_text())


def refs(model: dict, **kwargs) -> set[tuple]:
    return {(r.kind, r.name, r.owner) for r in find_references(model, **kwargs)}


def test_metric_references():
    """
    Tests references from node attributes, parameters and metric sets.
    """
    model = load("time-series.json")
    assert refs(model, kind="time series") == {
        ("time series", "inflow", ("node", "input1")),
        ("time series", "inflow", ("parameter", "factored_flow")),
    }
    assert ("parameter", "demand", ("node", "output1")) in refs(model)
    assert ("node", "output1", ("metric set", "nodes")) in refs(model)


def test_table_references():
    model = load("daily-profile1.json")
    assert refs(model, kind="table") == {
        ("table", "profiles-365", ("parameter", "daily-profile-365")),
        ("table", "profiles-366", ("parameter", "daily-profile-366")),
    }


def test_virtual_node_references():
    """
    Tests the members of a virtual node and the references to a virtual node.
    """
    model = load("agg-storage1.json")
    assert refs(model, kind="node") == {
        ("node", "storage1", ("virtual node", "total-storage")),
        ("node", "storage2", ("virtual node", "total-storage")),
    }
    assert refs(model, kind="virtual node") == {
        ("virtual node", "total-storage", ("parameter", "demand"))
    }


def test_edge_metric_references():
    model = load("piecewise_link1.json")
    assert refs(model, name="input1") == {("node", "input1", ("metric set", "edges"))}


def test_output_metric_sets():
    """
    Tests outputs with one metric set and with a list of metric sets.
    """
    assert refs(load("csv3.json"), kind="metric set") == {
        ("metric set", "nodes-monthly-mean", ("output", "monthly-avg-outputs")),
        ("metric set", "nodes-annual-mean", ("output", "monthly-avg-outputs")),
    }
    assert refs(load("agg-storage1.json"), kind="metric set") == {
        ("metric set", "nodes", ("output", "my-outputs"))
    }


def test_local_parameter_references():
    model = load("local-parameter1.json")
    assert refs(model, kind="local parameter") == {
        ("local parameter", "demand", ("node", "demand1"))
    }
    with pytest.raises(ValueError):
        rename_references(model, "local parameter", "demand", "other")


def test_edges_are_not_references():
    """
    Tests that the edges of the network are not listed as references.
    """
    model = load("piecewise_link1.json")
    assert all(r.path[1] != "edges" for r in find_references(model))


@pytest.mark.parametrize(
    "file, kind, old, new, count",
    [
        ("time-series.json", "time series", "inflow", "river", 2),
        ("daily-profile1.json", "table", "profiles-365", "t365", 1),
        ("agg-storage1.json", "node", "storage1", "res1", 1),
        ("agg-storage1.json", "virtual node", "total-storage", "all", 1),
        ("csv3.json", "metric set", "nodes-annual-mean", "annual", 1),
        ("piecewise_link1.json", "node", "input1", "in1", 1),
        ("time-series.json", "parameter", "missing", "other", 0),
    ],
)
def test_rename(file, kind, old, new, count):
    """
    Tests that only the references to the component are renamed.
    """
    model = load(file)
    before = refs(model)
    assert rename_references(model, kind, old, new) == count
    assert not any(r.name == old for r in find_references(model, kind=kind))
    renamed = {(k, new if k == kind and n == old else n, o) for k, n, o in before}
    # the owner of a reference is unchanged: only the referenced name changes
    assert refs(model) == renamed
