import json

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTreeWidgetItem

from pywr_editor import MainWindow
from pywr_editor.tree import ComponentsPanel
from tests.utils import close_message_box

MODEL = {
    "metadata": {"title": "Search model", "minimum_version": "0.1"},
    "timestepper": {"start": "2020-01-01", "end": "2020-01-05", "timestep": 1},
    "scenarios": [{"name": "Drought scenario", "size": 2}],
    "nodes": [
        {"name": "Reservoir North", "type": "storage", "max_volume": 10},
        {"name": "Reservoir South", "type": "storage", "max_volume": 20},
        {"name": "Demand", "type": "output", "max_flow": "demand_profile"},
    ],
    "edges": [["Reservoir North", "Demand"]],
    "parameters": {"demand_profile": {"type": "constant", "value": 3}},
    "recorders": {"demand_flow": {"type": "numpyarraynode", "node": "Demand"}},
}


@pytest.fixture
def window(qtbot, tmp_path):
    path = tmp_path / "model.json"
    path.write_text(json.dumps(MODEL))
    QTimer.singleShot(100, close_message_box)
    window = MainWindow(str(path))
    window.hide()
    yield window
    window.editor_settings.instance.clear()


def visible_texts(tree):
    """Texts of the items which are shown, i.e. that no parent hides."""
    found = []

    def visit(item: QTreeWidgetItem):
        for i in range(item.childCount()):
            child = item.child(i)
            if not child.isHidden():
                found.append(child.text(0))
                if child.isExpanded():
                    visit(child)

    visit(tree.invisibleRootItem())
    return found


def test_search_entry_is_above_the_tree(window):
    panel = window.findChild(ComponentsPanel)
    assert panel is window.components_panel
    assert panel.tree is window.components_tree
    # the entry is the first widget, over the tree
    assert panel.layout().itemAt(0).widget() is panel.search
    assert panel.search.y() < panel.tree.y() or not panel.isVisible()


class TestFilter:
    def test_filters_nodes_by_name(self, window):
        tree = window.components_tree
        assert tree.filter_items("reservoir") == 2
        shown = visible_texts(tree)
        assert "Reservoir North" in shown and "Reservoir South" in shown
        assert "Demand" not in shown
        # the groups without matches are hidden
        assert "Parameters" not in shown

    def test_filters_parameters_recorders_and_scenarios(self, window):
        tree = window.components_tree
        assert tree.filter_items("demand_profile") == 1
        assert "demand_profile" in visible_texts(tree)
        assert tree.filter_items("demand_flow") == 1
        assert "demand_flow" in visible_texts(tree)
        assert tree.filter_items("drought") == 1
        assert "Drought scenario" in visible_texts(tree)

    def test_is_case_insensitive_and_reports_no_match(self, window):
        tree = window.components_tree
        assert tree.filter_items("RESERVOIR NORTH") == 1
        assert tree.filter_items("nothing like this") == 0
        assert visible_texts(tree) == []

    def test_matching_a_group_shows_everything_in_it(self, window):
        tree = window.components_tree
        tree.filter_items("parameters")
        assert "demand_profile" in visible_texts(tree)

    def test_properties_of_components_are_not_searched(self, window):
        tree = window.components_tree
        # every storage node has a max_volume row, but only matching components
        # are shown
        tree.filter_items("max_volume")
        assert "Reservoir North" not in visible_texts(tree)

    def test_clearing_restores_the_tree_and_the_expanded_state(self, window):
        tree = window.components_tree

        def snapshot():
            items = tree.findItems("", Qt.MatchContains | Qt.MatchRecursive, 0)
            return {i.text(0): (i.isExpanded(), i.isHidden()) for i in items}

        before = snapshot()
        tree.filter_items("reservoir")
        assert snapshot() != before
        tree.filter_items("")
        assert snapshot() == before

    def test_filtering_does_not_change_the_stored_expanded_state(self, window):
        tree = window.components_tree
        stored = list(tree.expanded_state.get_all())
        tree.filter_items("reservoir")
        assert list(tree.expanded_state.get_all()) == stored

    def test_filter_is_kept_when_the_tree_is_reloaded(self, window):
        tree = window.components_tree
        tree.filter_items("demand_profile")
        tree.reload()
        assert visible_texts(tree) == ["Parameters", "demand_profile"]


def test_typing_in_the_entry_filters_and_shows_the_count(qtbot, window):
    panel = window.components_panel
    panel.search.setText("reservoir")
    qtbot.waitUntil(lambda: not panel.status.isHidden(), timeout=2000)
    assert panel.status.text() == "2 matches"
    panel.search.setText("zzz")
    qtbot.waitUntil(lambda: panel.status.text() == "No matches", timeout=2000)
    panel.search.clear()
    qtbot.waitUntil(lambda: panel.status.isHidden(), timeout=2000)
    demand = window.components_tree.findItems(
        "Demand", Qt.MatchExactly | Qt.MatchRecursive, 0
    )
    assert demand and not demand[0].isHidden()


def test_multi_select_filtered_nodes_and_colour(window) -> None:
    """Filter nodes, select them all in the tree and colour them in one go."""
    tree = window.components_tree
    tree.filter_items("reservoir")
    tree.expandAll()
    from pywr_editor.tree.tree_widget_node import TreeWidgetNode

    nodes = [
        item
        for item in tree.findItems("", Qt.MatchContains | Qt.MatchRecursive, 0)
        if isinstance(item, TreeWidgetNode) and not item.isHidden()
    ]
    assert len(nodes) == 2
    for item in nodes:
        item.setSelected(True)
    tree.on_item_click(nodes[0])
    assert {n.name for n in window.schematic.selected_nodes} == {
        "Reservoir North",
        "Reservoir South",
    }

    schematic = window.schematic
    schematic.set_nodes_color([n.name for n in nodes], "blue")
    assert schematic.node_items["Reservoir North"].color_ring is not None
    assert schematic.node_items["Demand"].color_ring is None
