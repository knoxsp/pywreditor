import json

import pytest

from pywr_editor.dialects import get_dialect
from pywr_editor.dialects.next.model import NextNodeConfig, humanise_type
from pywr_editor.model import EdgeRecord, ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"


def open_model(file: str) -> ModelConfig:
    model = ModelConfig(str(NEXT_MODELS / file))
    assert model.is_valid(), model.load_error
    return model


@pytest.fixture
def model() -> ModelConfig:
    """
    Catchment -> Reservoir -> Demand, with a metric set.
    """
    return open_model("reservoir_with_evaporation1.json")


class TestNodes:
    def test_names_and_config(self, model):
        assert model.dialect.key == "next"
        assert model.nodes.names == ["Catchment", "Reservoir", "Demand"]
        assert model.nodes.count == 3
        node = model.nodes.config("Reservoir", as_dict=False)
        assert isinstance(node, NextNodeConfig)
        assert node.name == "Reservoir"
        assert node.type == "reservoir"
        assert node.humanised_type == "Reservoir"
        assert node.is_virtual is False
        assert node.position is None
        assert model.nodes.config("Missing") is None

    def test_positions(self, model):
        """
        Tests that the positions are stored in the node's meta.position.
        """
        model.nodes.set_position([10.5, 20], node_name="Demand")
        model.nodes.set_geographic_position([-1.5, 51.2], node_name="Demand")
        meta = model.nodes.config("Demand")["meta"]
        assert meta["position"] == {"schematic": [10.5, 20], "geographic": [-1.5, 51.2]}
        node = model.nodes.config("Demand", as_dict=False)
        assert node.position == [10.5, 20]
        assert node.geographic_position == [-1.5, 51.2]
        assert model.has_changes is True

        model.nodes.set_geographic_position(None, node_name="Demand")
        assert meta["position"] == {"schematic": [10.5, 20]}

    def test_node_style(self, model):
        """
        Tests that the editor style is kept with the position and removed when unset.
        """
        model.nodes.set_node_style("Catchment", color="red", size=1.5)
        node = model.nodes.config("Catchment", as_dict=False)
        assert node.node_color == "red"
        assert node.node_size == 1.5
        model.nodes.set_node_style("Catchment", color=None, size=None)
        assert "position" not in model.nodes.config("Catchment")["meta"]

    def test_add_and_delete(self, model):
        new = NextNodeConfig.create("New link", "Link", [1.23456, 2])
        assert new == {
            "meta": {"name": "New link", "position": {"schematic": [1.2346, 2]}},
            "type": "Link",
        }
        model.nodes.add(new)
        assert model.nodes.names[-1] == "New link"
        with pytest.raises(KeyError):
            model.nodes.add({"type": "Link"})

        model.nodes.delete("Reservoir")
        assert "Reservoir" not in model.nodes.names
        # the edges of the node are deleted
        assert model.edges.records() == []

    def test_rename(self, model):
        """
        Tests that renaming a node renames its edges and the references to it.
        """
        model.nodes.rename("Reservoir", "Lake")
        assert model.nodes.names == ["Catchment", "Lake", "Demand"]
        assert model.edges.targets("Catchment") == ["Lake"]
        assert model.edges.targets("Lake") == ["Demand"]
        metric_names = [
            metric["name"]
            for metric in model.json["network"]["metric_sets"][0]["metrics"]
        ]
        assert metric_names == ["Lake", "Lake", "Demand"]

    def test_update_keeps_position(self, model):
        model.nodes.set_position([1, 2], node_name="Demand")
        model.nodes.update(
            {"meta": {"name": "Demand"}, "type": "Output", "max_flow": None}
        )
        node = model.nodes.config("Demand")
        assert node["meta"]["position"] == {"schematic": [1, 2]}
        assert "cost" not in node

    def test_orphans(self, model):
        assert model.nodes.orphans() is None
        model.nodes.add(NextNodeConfig.create("Alone", "Link", [0, 0]))
        assert model.nodes.orphans() == ["Alone"]

    @pytest.mark.parametrize(
        "node_type, expected",
        [
            ("RiverSplitWithGauge", "River split with gauge"),
            ("WaterTreatmentWorks", "Water treatment works"),
            ("Link", "Link"),
            (None, "Unknown"),
        ],
    )
    def test_humanise_type(self, node_type, expected):
        assert humanise_type(node_type) == expected


class TestEdges:
    def test_records(self, model):
        assert model.edges.records() == [
            EdgeRecord("Catchment", "Reservoir"),
            EdgeRecord("Reservoir", "Demand"),
        ]
        assert model.edges.count == 2
        assert model.edges.get_sources("Demand") == ["Reservoir"]
        assert model.edges.targets("Demand") is None
        assert model.edges.find_record("Catchment", "Demand") is None

    def test_add_delete_and_slots(self, model):
        assert model.edges.add(
            "Catchment", "Demand", None, {"type": "User", "name": "a"}
        )
        assert model.edges.find("Catchment", "Demand")[0] == {
            "from_node": "Catchment",
            "to_node": "Demand",
            "to_slot": {"type": "User", "name": "a"},
        }
        assert model.edges.add("Catchment", "Missing") is False

        model.edges.set_slot("Catchment", "Demand", 1, {"type": "River"})
        assert model.edges.slot("Catchment", "Demand", 1) == {"type": "River"}
        model.edges.set_slot("Catchment", "Demand", 2, None)
        assert model.edges.find_record("Catchment", "Demand") == EdgeRecord(
            "Catchment", "Demand", {"type": "River"}, None
        )

        model.edges.delete("Catchment", "Demand")
        assert model.edges.find_record("Catchment", "Demand") is None
        assert model.edges.count == 2
        model.edges.delete(source_node_name="Reservoir")
        assert model.edges.records() == [EdgeRecord("Catchment", "Reservoir")]

    def test_add_record(self, model):
        record = EdgeRecord("Demand", "Catchment", {"type": "River"})
        assert model.edges.add_record(record)
        assert model.edges.find_record("Demand", "Catchment") == record

    def test_edge_color(self, model):
        model.nodes.set_node_style("Catchment", color="red")
        assert model.edges.color("Catchment") is None
        model.nodes.config("Catchment", as_dict=False).position_dict(create=True)[
            "edge_color"
        ] = "blue"
        assert model.edges.color("Catchment") == "blue"


class TestModel:
    def test_no_op_round_trip(self, model):
        """
        Tests that a model is unchanged when it is loaded and saved without changes.
        """
        original = json.loads(
            (NEXT_MODELS / "reservoir_with_evaporation1.json").read_text()
        )
        assert model.clean_json == original

    def test_virtual_nodes(self):
        model = open_model("agg-storage1.json")
        assert model.virtual_nodes.names == ["total-storage"]
        assert "total-storage" not in model.nodes.names

    def test_time(self, model):
        assert model.title == "Reservoir node with evaporation"
        assert model.start_date == "2015-01-01"
        assert model.end_date == "2015-01-06"
        assert model.time_delta == 1
        model.time_delta = 7
        model.end_date = "2015-02-01"
        assert model.json["time"] == {
            "start": "2015-01-01",
            "end": "2015-02-01",
            "timestep": {"type": "Days", "days": 7},
        }
        model.json["time"]["timestep"] = {"type": "Hours", "hours": 3}
        assert model.time_delta == 1

    def test_empty_model(self):
        """
        Tests that the empty pywr-next model can be loaded.
        """
        dialect = get_dialect("next")
        model = ModelConfig()
        model.json = dialect.empty_model()
        model.dialect = dialect
        dialect.setup_model(model)
        assert model.is_valid()
        assert model.nodes.names == []


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda m: m["network"]["nodes"][0].pop("meta"), "position 1 has no name"),
        (lambda m: m["network"]["nodes"][1].pop("type"), '"Reservoir" has no type'),
        (lambda m: m["network"].update(edges={}), '"network.edges" value must be'),
        (lambda m: m["network"]["edges"].append({"from_node": "A"}), "position 3"),
    ],
)
def test_structure_errors(tmp_path, change, message):
    """
    Tests that a model the editor cannot work with is not loaded.
    """
    data = json.loads((NEXT_MODELS / "reservoir_with_evaporation1.json").read_text())
    change(data)
    file = tmp_path / "model.json"
    file.write_text(json.dumps(data))
    model = ModelConfig(str(file))
    assert model.is_valid() is False
    assert message in model.load_error


@pytest.mark.parametrize(
    "file, message",
    [("multi1/model.json", "several networks"), ("multi1/network1.json", "Open")],
)
def test_multi_network_not_loaded(file, message):
    model = ModelConfig(str(NEXT_MODELS / file))
    assert model.dialect.key == "next"
    assert message in model.load_error
