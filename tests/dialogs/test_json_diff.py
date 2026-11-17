from pywr_editor import MainWindow
from pywr_editor.dialogs import JsonCodeViewer
from pywr_editor.dialogs.json_viewer.json_diff import json_diff
from tests.utils import resolve_model_path


class TestJsonDiff:
    def test_diff_lines(self):
        old = {"a": 1, "b": [1, 2], "c": {"d": "x"}}
        new = {"a": 1, "b": [1, 2, 3], "c": {"d": "y"}}
        diff = json_diff(old, new, "before", "after")
        lines = diff.splitlines()
        assert lines[:2] == ["--- before", "+++ after"]
        assert '-    "d": "x"' in lines
        assert '+    "d": "y"' in lines
        # formatting differences are not changes
        assert json_diff('{"a":1}', {"a": 1}, "x", "y") == ""

    def test_viewer_diff_tab(self, qtbot):
        window = MainWindow(resolve_model_path("model_1.json"))
        window.prompt_unsaved_changes = False
        qtbot.addWidget(window)
        window.hide()

        # nothing to compare: no diff tab
        viewer = JsonCodeViewer(window, {"a": 1})
        qtbot.addWidget(viewer)
        assert not hasattr(viewer, "tabs")

        model = window.model_config
        model.start_date = "2001-01-01"
        viewer = JsonCodeViewer(
            window,
            model.clean_json,
            compare_with={
                "saved": model.change_log.baseline(since_saved=True) or {},
            },
        )
        qtbot.addWidget(viewer)
        assert [viewer.tabs.tabText(i) for i in range(2)] == ["JSON", "Diff"]
        assert viewer.diff_editor.has_differences
        text = viewer.diff_editor.toPlainText()
        assert text.startswith("--- saved\n+++ current model")
        assert '+    "start": "2001-01-01"' in text

    def test_main_window_viewer_compares_with_saved_and_opened(
        self, qtbot, monkeypatch
    ):
        window = MainWindow(resolve_model_path("model_1.json"))
        window.prompt_unsaved_changes = False
        qtbot.addWidget(window)
        window.hide()
        window.model_config.start_date = "2001-01-01"

        shown = []
        monkeypatch.setattr(
            JsonCodeViewer, "exec", lambda self: shown.append(self) or 0
        )
        window.show_json()
        viewer = shown[0]
        assert list(viewer.compare_with) == [
            "the last saved version",
            "the model as it was opened",
        ]
        assert viewer.diff_editor.has_differences
        # the editor data is not part of the file shown or compared
        assert "pywr_editor" not in viewer.diff_editor.toPlainText()
