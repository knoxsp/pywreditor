from pywr_editor import MainWindow
from pywr_editor.dialogs import ChangesDialog
from pywr_editor.model import ModelConfig
from tests.utils import resolve_model_path


class TestChangesDialog:
    def test_lists_and_updates_changes(self, qtbot):
        window = MainWindow(resolve_model_path("model_1.json"))
        qtbot.addWidget(window)
        model = window.model_config

        dialog = ChangesDialog(model_config=model, parent=window)
        qtbot.addWidget(dialog)
        dialog.show()
        assert dialog.tree.topLevelItemCount() == 0

        # the open dialog follows the model
        model.start_date = "2001-01-01"
        assert dialog.tree.topLevelItemCount() == 1
        top = dialog.tree.topLevelItem(0)
        assert "timestepper.start" in top.text(2)
        assert "not saved" in top.text(2)

        model.end_date = "2005-01-01"
        assert dialog.tree.topLevelItemCount() == 2
        # newest first
        assert "timestepper.end" in dialog.tree.topLevelItem(0).text(2)

        dialog.close()
        # not updated while hidden...
        model.start_date = "2002-01-01"
        assert dialog.tree.topLevelItemCount() == 2
        # ... but refreshed when shown again
        dialog.show()
        assert dialog.tree.topLevelItemCount() == 3
        # do not prompt to save the model when the window is closed
        model.reset_change_flag()

    def test_summary_shows_the_net_changes(self, qtbot, tmp_path):
        import shutil

        file = tmp_path / "model.json"
        shutil.copy(resolve_model_path("model_1.json"), file)
        model = ModelConfig(str(file))
        dialog = ChangesDialog(model_config=model)
        qtbot.addWidget(dialog)
        tree = dialog.summary_tree
        assert tree.topLevelItemCount() == 0
        assert "same as the last saved" in dialog.summary_label.text()

        # a value edited twice is one change
        model.start_date = "2001-01-01"
        model.start_date = "2002-01-01"
        model.scenarios.update("new scenario", {"size": 3})
        dialog.populate()
        sections = {
            tree.topLevelItem(i).text(0): tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
        }
        assert set(sections) == {"timestepper", "scenarios"}
        assert sections["timestepper"].childCount() == 1
        assert "2002-01-01" in sections["timestepper"].child(0).text(2)
        assert dialog.summary_label.text() == "2 changes in 2 sections."

        # an edit that is undone is not a change
        model.scenarios.delete("new scenario")
        dialog.populate()
        assert tree.topLevelItemCount() == 1

        # after saving, the model is the same as the saved version, but not the
        # original one
        assert model.save() is True
        dialog.populate()
        assert tree.topLevelItemCount() == 0
        dialog.summary_compare.setCurrentIndex(1)
        assert tree.topLevelItemCount() == 1
        assert tree.topLevelItem(0).text(0) == "timestepper"

    def test_opened_from_window(self, qtbot):
        window = MainWindow(resolve_model_path("model_1.json"))
        qtbot.addWidget(window)
        assert window.app_actions.get("show-changes") is not None


class TestChangesDialogGit:
    @staticmethod
    def make_repo(tmp_path):
        import shutil

        from tests.model.test_git_history import commit, git

        git(tmp_path, "init", "-q")
        file = tmp_path / "model.json"
        shutil.copy(resolve_model_path("model_1.json"), file)
        commit(tmp_path, "first")
        model = ModelConfig(str(file))
        model.start_date = "2001-01-01"
        assert model.save() is True
        commit(tmp_path, "change start date")
        return file

    def test_no_git_tabs_without_a_repository(self, qtbot, tmp_path, monkeypatch):
        import shutil

        file = tmp_path / "model.json"
        shutil.copy(resolve_model_path("model_1.json"), file)
        monkeypatch.setattr(
            "pywr_editor.dialogs.changes.changes_dialog.GitHistory.find",
            lambda *args: None,
        )
        dialog = ChangesDialog(model_config=ModelConfig(str(file)))
        qtbot.addWidget(dialog)
        assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
            "This session",
            "Summary",
        ]

    def test_history_restore_and_stash(self, qtbot, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        file = self.make_repo(tmp_path)
        model = ModelConfig(str(file))
        reopened = []
        dialog = ChangesDialog(
            model_config=model, prepare=lambda: True, reopen=lambda: reopened.append(1)
        )
        qtbot.addWidget(dialog)
        assert [dialog.tabs.tabText(i) for i in range(4)] == [
            "This session",
            "Summary",
            "Git history",
            "Stashes",
        ]

        history_tab, stashes_tab = dialog.git_tabs
        dialog.tabs.setCurrentIndex(2)  # reads git
        assert history_tab.tree.topLevelItemCount() == 2
        assert history_tab.tree.topLevelItem(0).text(3) == "change start date"

        # what a commit changed is read when the item is expanded
        newest = history_tab.tree.topLevelItem(0)
        newest.setExpanded(True)
        assert "timestepper.start" in newest.child(0).text(3)

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        # nothing selected, nothing to restore
        assert not history_tab.restore_button.isEnabled()
        history_tab.tree.setCurrentItem(history_tab.tree.topLevelItem(1))
        assert history_tab.restore_button.isEnabled()
        history_tab.restore()
        assert reopened == [1]
        restored = ModelConfig(str(file))
        assert restored.start_date != "2001-01-01"

        # the restored version is not committed: stash it and apply it again
        history_tab.refresh()
        assert history_tab.stash_button.isEnabled()
        assert history_tab.tree.topLevelItem(0).text(0) == "Uncommitted"
        monkeypatch.setattr(
            QInputDialog, "getText", lambda *a, **k: ("old version", True)
        )
        history_tab.stash()
        assert reopened == [1, 1]
        assert ModelConfig(str(file)).start_date == "2001-01-01"

        stashes_tab.refresh()
        assert stashes_tab.tree.topLevelItem(0).text(1) == "old version"
        stashes_tab.tree.setCurrentItem(stashes_tab.tree.topLevelItem(0))
        stashes_tab.apply()
        assert reopened == [1, 1, 1]
        assert ModelConfig(str(file)).start_date != "2001-01-01"

        stashes_tab.delete()
        assert stashes_tab.tree.topLevelItemCount() == 0

    def test_cancelled_by_prepare(self, qtbot, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        file = self.make_repo(tmp_path)
        reopened = []
        dialog = ChangesDialog(
            model_config=ModelConfig(str(file)),
            prepare=lambda: False,
            reopen=lambda: reopened.append(1),
        )
        qtbot.addWidget(dialog)
        history_tab = dialog.git_tabs[0]
        history_tab.refresh()
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        history_tab.tree.setCurrentItem(history_tab.tree.topLevelItem(1))
        history_tab.restore()
        assert reopened == []
        assert ModelConfig(str(file)).start_date == "2001-01-01"


class TestSaveBeforeChangingFiles:
    def test_save_or_cancel(self, qtbot, tmp_path, monkeypatch):
        import shutil

        from PySide6.QtWidgets import QMessageBox

        file = tmp_path / "model.json"
        shutil.copy(resolve_model_path("model_1.json"), file)
        window = MainWindow(str(file))
        qtbot.addWidget(window)
        # nothing to save
        assert window.save_before_changing_files() is True

        window.model_config.start_date = "2001-01-01"
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
        )
        assert window.save_before_changing_files() is False
        assert ModelConfig(str(file)).start_date != "2001-01-01"

        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save
        )
        assert window.save_before_changing_files() is True
        assert ModelConfig(str(file)).start_date == "2001-01-01"
        assert not window.model_config.has_changes
