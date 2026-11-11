import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pywr_editor.dialects.next import NextDialect
from pywr_editor.dialects.v1 import V1Dialect
from pywr_editor.model.connection_rules import Role
from tests.utils import model_path

"""
 Contract tests: the role of each node type, which the connection rules use, must agree
 with the pywr that is installed. They fail when a new pywr changes how a type behaves.
"""

NEXT_MODELS = model_path() / "pywr_next"


def test_v1_roles_follow_the_pywr_classes():
    """
    Tests that the role of every pywr v1 node type is the one given by the class in
    pywr: the inputs, the outputs and the storages are told apart by their base class.
    """
    nodes = pytest.importorskip("pywr.nodes")
    core = pytest.importorskip("pywr._core")
    if not hasattr(nodes, "NodeMeta"):
        pytest.skip("this is not pywr v1")

    mismatches = []
    for key, role in V1Dialect.node_roles.items():
        registry = nodes.NodeMeta.node_registry
        node_class = registry.get(key) or registry.get(key + "node")
        assert node_class is not None, f"pywr has no node type {key}"
        if issubclass(node_class, core.BaseInput):
            expected = Role.SOURCE
        elif issubclass(node_class, core.BaseOutput):
            expected = Role.SINK
        elif issubclass(node_class, core.Storage):
            expected = Role.STORAGE
        else:
            expected = Role.THROUGH
        if role != expected:
            mismatches.append(f"{key}: table {role}, pywr {expected}")
    assert mismatches == []


PROBE = """
import json, sys
import pywr

def builds(request):
    try:
        schema = pywr.ModelSchema.from_json_string(json.dumps(request["model"]))
        schema.build(request["dir"], None)
        return True
    except Exception:
        return False

print(json.dumps([builds(r) for r in json.load(sys.stdin)]))
"""


@pytest.mark.skipif(
    not os.environ.get("PYWR_NEXT_PYTHON"), reason="needs PYWR_NEXT_PYTHON"
)
def test_next_roles_follow_the_pywr_next_build():
    """
    Tests the role of every pywr-next node type that is in the test models against
    pywr-next: an edge into a source or out of a sink must be refused when the network
    is built, and an edge to or from any other node must be accepted.
    """
    def probe(requests: list[dict]) -> list[bool]:
        output = subprocess.run(
            [os.environ["PYWR_NEXT_PYTHON"], "-c", PROBE],
            input=json.dumps(requests),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return json.loads(output.stdout.strip().splitlines()[-1])

    # the models that build as they are (some need files that are not copied)
    models = []
    for file in sorted(NEXT_MODELS.glob("*.json")):
        model = json.loads(file.read_text())
        if "network" in model:
            models.append((file, model))
    builds = probe([{"model": m, "dir": str(f.parent)} for f, m in models])

    examples = {}  # the type -> (the file, the model, the node name)
    for (file, model), builds_as_it_is in zip(models, builds):
        for node in model["network"]["nodes"] if builds_as_it_is else []:
            examples.setdefault(node["type"], (file, model, node["meta"]["name"]))

    requests, labels = [], []
    for node_type, (file, model, name) in examples.items():
        for direction, other in (("out", "Output"), ("in", "Input")):
            changed = copy.deepcopy(model)
            changed["network"]["nodes"].append(
                {"meta": {"name": "__probe"}, "type": other}
            )
            edge = (name, "__probe") if direction == "out" else ("__probe", name)
            changed["network"].setdefault("edges", []).append(
                {"from_node": edge[0], "to_node": edge[1]}
            )
            requests.append({"model": changed, "dir": str(file.parent)})
            labels.append((node_type, direction))
    results = dict(zip(labels, probe(requests)))

    checked, mismatches = [], []
    for node_type in examples:
        role = NextDialect.node_roles.get(node_type.lower())
        if role is None:
            continue  # not in the table
        checked.append(node_type)
        out_accepted = results[(node_type, "out")]
        in_accepted = results[(node_type, "in")]
        expected_out = role != Role.SINK
        expected_in = role != Role.SOURCE
        if (out_accepted, in_accepted) != (expected_out, expected_in):
            mismatches.append(
                f"{node_type} ({role.value}): pywr-next accepts an edge out of it: "
                f"{out_accepted}, into it: {in_accepted}"
            )
    assert mismatches == []
    # the types of the table that no test model has are not checked: keep this list short
    assert {"input", "output", "catchment", "storage", "link"} <= {
        t.lower() for t in checked
    }
