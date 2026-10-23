import json

import pytest
from PySide6.QtCore import QTimer

from pywr_editor import MainWindow
from pywr_editor.schematic.layout import force_directed_layout, snap_to_grid
from tests.utils import close_message_box, resolve_model_path


def test_layout_pushes_stacked_nodes_apart():
    names = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("b", "c"), ("c", "d")]
    initial = {n: (400.0, 300.0) for n in names}
    result = force_directed_layout(names, edges, initial, iterations=100)

    assert len({tuple(p) for p in result.values()}) == 4
    # connected nodes are closer than the ends of the chain

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(result[a], result[b]))

    assert dist("a", "b") < dist("a", "d")
    # centred on the initial centre
    assert sum(p[0] for p in result.values()) / 4 == pytest.approx(400, abs=0.1)


def test_snap_to_grid_is_on_grid_and_unique():
    # all the nodes round to the same point: they must still get distinct points
    positions = {f"n{i}": [101.0 + i, 99.0 - i] for i in range(10)}
    snapped = snap_to_grid(positions, 25)
    assert len({tuple(p) for p in snapped.values()}) == 10
    assert all(x % 25 == 0 and y % 25 == 0 for x, y in snapped.values())
    # a lone node goes to its nearest point
    assert snap_to_grid({"a": [112.0, 37.0]}, 25) == {"a": [100.0, 25.0]}


class TestAutoLayout:
    def test_layout_and_undo(self, qtbot, tmp_path):
        with open(resolve_model_path("model_geographic_positions.json")) as fp:
            model = json.load(fp)
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model))
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(str(path))
        window.hide()
        schematic = window.schematic
        before = {n: i.pos().toTuple() for n, i in schematic.node_items.items()}

        window.app_actions.get("auto-layout").trigger()
        after = {n: i.pos().toTuple() for n, i in schematic.node_items.items()}
        assert after != before
        assert window.model_config.has_changes

        window.undo_stack.undo()
        restored = {n: i.pos().toTuple() for n, i in schematic.node_items.items()}
        assert restored == before


def test_infer_positions_from_neighbours():
    from pywr_editor.schematic.layout import infer_positions

    known = {"a": (0.0, 0.0), "d": (30.0, 0.0)}
    edges = [("a", "b"), ("b", "c"), ("c", "d"), ("x", "y")]
    result = infer_positions(known, ["a", "b", "c", "d", "x", "y"], edges)

    # a chain between located nodes is spread between them
    assert result["b"][0] == pytest.approx(10, abs=0.01)
    assert result["c"][0] == pytest.approx(20, abs=0.01)
    # a group not connected to a located node cannot be placed
    assert "x" not in result and "y" not in result


class TestSelectionBox:
    def test_shift_drag_on_empty_canvas_selects_nodes(self, qtbot, tmp_path):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest

        with open(resolve_model_path("model_geographic_positions.json")) as fp:
            model = json.load(fp)
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model))
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(str(path))
        window.resize(1000, 800)
        window.show()
        schematic = window.schematic
        window.editor_settings.save_geo_view(False)
        schematic.reload()
        schematic.fit_view()
        qtbot.wait(50)

        viewport = schematic.viewport()
        end = QPoint(viewport.width() - 2, viewport.height() - 2)
        QTest.mousePress(viewport, Qt.LeftButton, Qt.ShiftModifier, QPoint(1, 1))
        QTest.mouseMove(viewport, QPoint(50, 50))
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.ShiftModifier, end)
        assert len(schematic.scene.selectedItems()) > 1

    def test_layout_snaps_to_grid(self, qtbot, tmp_path):
        with open(resolve_model_path("model_geographic_positions.json")) as fp:
            model = json.load(fp)
        path = tmp_path / "model.json"
        path.write_text(json.dumps(model))
        QTimer.singleShot(100, close_message_box)
        window = MainWindow(str(path))
        window.hide()
        window.editor_settings.save_snap_to_grid(True)
        window.editor_settings.save_grid_size(25)

        window.app_actions.get("auto-layout").trigger()
        points = [i.pos().toTuple() for i in window.schematic.node_items.values()]
        assert all(x % 25 == 0 and y % 25 == 0 for x, y in points)
        assert len(set(points)) == len(points)
