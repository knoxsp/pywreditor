import shutil

import pytest

from pywr_editor import MainWindow
from pywr_editor.dialects.next import (
    NODE_GROUPS,
    NODE_SHAPES,
    NextDialect,
    node_group,
    node_group_order,
)
from pywr_editor.dialects.next.model import NextNodeConfig
from pywr_editor.dialects.next.schema import bundled_schema
from pywr_editor.dialects.v1 import V1Dialect
from pywr_editor.node_shapes import CustomNode
from pywr_editor.node_shapes.utils import get_node_icon
from pywr_editor.toolbar.node_library.schematic_items_library import (
    SchematicItemsLibrary,
)
from tests.utils import model_path

SCHEMA_TYPES = [t for t in bundled_schema().types("Node") if t != "Placeholder"]


def test_every_type_of_the_schema_is_in_a_group():
    grouped = [t for _, types in NODE_GROUPS for t in types]
    assert sorted(grouped) == sorted(SCHEMA_TYPES)
    assert len(grouped) == len(set(grouped))


def test_node_types_are_grouped_and_without_placeholder():
    types = list(NextDialect().node_types())
    assert "Placeholder" not in types
    assert sorted(types) == sorted(SCHEMA_TYPES)
    groups = [node_group(t) for t in types]
    # the groups follow each other, in the order of NODE_GROUPS
    assert groups == sorted(groups, key=[g for g, _ in NODE_GROUPS].index)
    assert types[:3] == ["Input", "Link", "Output"]
    assert NextDialect().node_types()["PiecewiseStorage"] == "Piecewise storage"


def test_a_type_from_a_later_version_comes_last():
    assert node_group("Future") == "Other"
    assert node_group_order("Future") > max(node_group_order(t) for t in SCHEMA_TYPES)


@pytest.mark.parametrize("node_type", SCHEMA_TYPES)
def test_every_type_has_its_own_shape(qtbot, node_type):
    config = NextNodeConfig(
        NextNodeConfig.create(name="n", node_type=node_type, position=(0, 0))
    )
    assert get_node_icon(config) is not CustomNode


def test_shapes_of_other_names():
    assert NextDialect().node_shape_name("Delay") == "DelayNode"
    assert NextDialect().node_shape_name("WaterTreatmentWorks") == "Works"
    assert NextDialect().node_shape_name("Turbine") == "Turbine"
    assert set(NODE_SHAPES) == {"Delay", "WaterTreatmentWorks"}
    assert V1Dialect().node_shape_name("Delay") == "Delay"


def test_an_unknown_type_gets_the_generic_shape(qtbot):
    config = NextNodeConfig(
        NextNodeConfig.create(name="n", node_type="Future", position=(0, 0))
    )
    assert get_node_icon(config) is CustomNode


def test_the_library_lists_the_types_in_order(qtbot, tmp_path):
    model_file = tmp_path / "model.json"
    shutil.copy(model_path() / "pywr_next" / "time-series.json", model_file)
    window = MainWindow(str(model_file))
    window.hide()
    library = window.findChild(SchematicItemsLibrary)
    assert list(library.panel.node_dict) == list(NextDialect().node_types())
    window.model_config.reset_change_flag()
    window.close()
