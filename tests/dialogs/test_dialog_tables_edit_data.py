import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor.dialogs import TablesDialog
from pywr_editor.dialogs.tables.table_data_dialog import TableDataDialog
from pywr_editor.dialogs.tables.table_page import TablePage
from pywr_editor.model import ModelConfig
from tests.utils import resolve_model_path

FILES = Path(resolve_model_path("model_tables.json")).parent / "files"


@pytest.fixture()
def model_file(tmp_path):
    file = tmp_path / "my_model.json"
    shutil.copy(resolve_model_path("model_tables.json"), file)
    return file


@pytest.fixture()
def messages(monkeypatch):
    shown = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox,
            kind,
            staticmethod(lambda *a, _k=kind, **kw: shown.append((_k, a[2]))),
        )
    return shown


@pytest.fixture()
def opened(monkeypatch):
    """Replaces exec() and records the dialogs; edit them via opened.edit."""

    class Opened:
        dialogs: list[TableDataDialog] = []
        edit = None
        save = True

    state = Opened()
    state.dialogs = []

    def fake_exec(self):
        state.dialogs.append(self)
        if state.edit:
            state.edit(self)
        if state.save:
            self.on_save()
        self.grid.undo_stack.setClean()  # never prompt in the test
        return 0

    monkeypatch.setattr(TableDataDialog, "exec", fake_exec)
    return state


def open_page(qtbot, model, name=None) -> TablePage:
    dialog = TablesDialog(model, selected_name=name)
    qtbot.addWidget(dialog)
    if name is None:
        dialog.add_table()
    page = dialog.pages.currentWidget()
    page.form.load_fields()
    return page


def url_widget(page: TablePage):
    return page.form.find_field("url").widget


def paste(rows, headers=None):
    return lambda d: d.grid.set_block(0, 0, rows, headers=headers)


class TestNewTable:
    def test_creates_csv_in_subfolder_and_sets_url(
        self, qtbot, model_file, opened
    ):
        page = open_page(qtbot, ModelConfig(str(model_file)))
        opened.edit = paste([["a", "b"], ["1", "2"]], headers=["x", "y"])
        page.on_edit_data()

        csv = model_file.parent / "my_model_tables" / f"{page.name}.csv"
        assert csv.read_text() == "x,y\na,b\n1,2\n"
        assert url_widget(page).line_edit.text() == f"my_model_tables/{page.name}.csv"

    def test_url_is_relative_with_forward_slashes(self, qtbot, model_file, opened):
        page = open_page(qtbot, ModelConfig(str(model_file)))
        opened.edit = paste([["1"]], headers=["a"])
        page.on_edit_data()
        text = url_widget(page).line_edit.text()
        assert "\\" not in text and not text.startswith("/")

    def test_saved_table_is_loaded_by_the_url_widget(self, qtbot, model_file, opened):
        page = open_page(qtbot, ModelConfig(str(model_file)))
        opened.edit = paste([["1", "2"]], headers=["x", "y"])
        page.on_edit_data()
        widget = url_widget(page)
        assert widget.full_file is not None
        assert list(widget.table.columns) == ["x", "y"] or "x" in list(
            widget.table.columns
        ) + [widget.table.index.name]

    def test_cancelling_leaves_no_file_and_no_url(self, qtbot, model_file, opened):
        page = open_page(qtbot, ModelConfig(str(model_file)))
        opened.save = False
        page.on_edit_data()
        assert url_widget(page).line_edit.text() == ""
        assert not (model_file.parent / "my_model_tables").exists()

    def test_edit_data_twice_reuses_the_same_file(self, qtbot, model_file, opened):
        page = open_page(qtbot, ModelConfig(str(model_file)))
        opened.edit = paste([["1"]], headers=["a"])
        page.on_edit_data()
        first = opened.dialogs[0].file
        opened.edit = None
        page.on_edit_data()
        assert opened.dialogs[1].file == first
        assert opened.dialogs[1].grid.rows == [["1"]]
        assert len(list((model_file.parent / "my_model_tables").iterdir())) == 1

    def test_unsafe_characters_in_name_make_a_safe_filename(
        self, qtbot, model_file, opened
    ):
        model = ModelConfig(str(model_file))
        model.tables.update('Bad/name: "x"?', {})
        page = open_page(qtbot, model, 'Bad/name: "x"?')
        opened.edit = paste([["1"]], headers=["a"])
        page.on_edit_data()
        folder = model_file.parent / "my_model_tables"
        files = list(folder.iterdir())
        assert len(files) == 1
        assert files[0].parent == folder  # no path traversal through the name
        assert not set(files[0].stem) & set('/\\:"?*<>|')

    def test_dot_dot_in_name_cannot_escape_the_folder(self, qtbot, model_file, opened):
        model = ModelConfig(str(model_file))
        model.tables.update("../../evil", {})
        page = open_page(qtbot, model, "../../evil")
        opened.edit = paste([["1"]], headers=["a"])
        page.on_edit_data()
        written = opened.dialogs[0].file.resolve()
        assert (model_file.parent / "my_model_tables").resolve() in written.parents

    def test_existing_file_with_that_name_is_not_overwritten(
        self, qtbot, model_file, opened, messages
    ):
        page = open_page(qtbot, ModelConfig(str(model_file)))
        folder = model_file.parent / "my_model_tables"
        folder.mkdir()
        existing = folder / f"{page.name}.csv"
        existing.write_text("precious\n1\n")
        page.on_edit_data()
        assert existing.read_text() == "precious\n1\n"
        assert opened.dialogs == []
        assert messages and messages[0][0] == "warning"

    def test_folder_uses_model_file_stem(self, qtbot, tmp_path, opened):
        file = tmp_path / "national_model.json"
        shutil.copy(resolve_model_path("model_tables.json"), file)
        page = open_page(qtbot, ModelConfig(str(file)))
        opened.edit = paste([["1"]], headers=["a"])
        page.on_edit_data()
        assert (tmp_path / "national_model_tables").is_dir()

    def test_unsaved_model_is_refused(self, qtbot, opened, messages):
        page = open_page(qtbot, ModelConfig())
        page.on_edit_data()
        assert opened.dialogs == []
        assert messages and "save the model" in messages[0][1]


class TestExistingTable:
    def test_csv_is_editable_and_text_preserved(self, qtbot, model_file, opened):
        csv = model_file.parent / "t.csv"
        csv.write_text("d,v\n01/02,1.50\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Existing", {"url": "t.csv"})
        page = open_page(qtbot, model, "Existing")
        opened.edit = lambda d: d.grid.set_block(0, 1, [["2.50"]])
        page.on_edit_data()
        assert csv.read_text() == "d,v\n01/02,2.50\n"

    def test_file_outside_subfolder_is_edited_in_place(
        self, qtbot, model_file, opened
    ):
        csv = model_file.parent / "data" / "t.csv"
        csv.parent.mkdir()
        csv.write_text("a\n1\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Existing", {"url": "data/t.csv"})
        page = open_page(qtbot, model, "Existing")
        opened.edit = lambda d: d.grid.set_block(0, 0, [["9"]])
        page.on_edit_data()
        assert csv.read_text() == "a\n9\n"
        assert not (model_file.parent / "my_model_tables").exists()

    def test_custom_separator_is_used_for_reading_and_writing(
        self, qtbot, model_file, opened
    ):
        csv = model_file.parent / "t.csv"
        csv.write_text("a;b\n1;2\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Semi", {"url": "t.csv", "sep": ";"})
        page = open_page(qtbot, model, "Semi")
        opened.edit = lambda d: d.grid.set_block(0, 1, [["3"]])
        page.on_edit_data()
        assert opened.dialogs[0].grid.headers == ["a", "b"]
        assert csv.read_text() == "a;b\n1;3\n"

    def test_cancel_does_not_touch_the_file(self, qtbot, model_file, opened):
        csv = model_file.parent / "t.csv"
        csv.write_text("a\n1\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Existing", {"url": "t.csv"})
        page = open_page(qtbot, model, "Existing")
        opened.edit = lambda d: d.grid.set_block(0, 0, [["9"]])
        opened.save = False
        page.on_edit_data()
        assert csv.read_text() == "a\n1\n"

    def test_url_widget_reloads_after_edit(self, qtbot, model_file, opened):
        csv = model_file.parent / "t.csv"
        csv.write_text("a,b\n1,2\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Existing", {"url": "t.csv"})
        page = open_page(qtbot, model, "Existing")
        opened.edit = lambda d: d.grid.insert_column(2, "c")
        page.on_edit_data()
        assert "c" in list(url_widget(page).table.columns) + list(
            url_widget(page).table.index.names
        )

    def test_txt_extension_is_editable(self, qtbot, model_file, opened):
        txt = model_file.parent / "t.txt"
        txt.write_text("a,b\n1,2\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Txt", {"url": "t.txt"})
        page = open_page(qtbot, model, "Txt")
        page.on_edit_data()
        assert len(opened.dialogs) == 1

    @pytest.mark.parametrize("name", ["table.xlsx", "table.h5"])
    def test_excel_and_h5_are_refused(
        self, qtbot, model_file, opened, messages, name
    ):
        shutil.copy(FILES / name, model_file.parent / name)
        before = (model_file.parent / name).read_bytes()
        model = ModelConfig(str(model_file))
        config = {"url": name}
        if name.endswith("h5"):
            config["key"] = "table"
        model.tables.update("Binary", config)
        page = open_page(qtbot, model, "Binary")
        page.on_edit_data()
        assert opened.dialogs == []
        assert messages and messages[0][0] == "information"
        assert (model_file.parent / name).read_bytes() == before

    def test_missing_file_is_refused_and_not_created(
        self, qtbot, model_file, opened, messages
    ):
        model = ModelConfig(str(model_file))
        model.tables.update("Gone", {"url": "missing.csv"})
        page = open_page(qtbot, model, "Gone")
        page.on_edit_data()
        assert opened.dialogs == []
        assert not (model_file.parent / "missing.csv").exists()
        assert messages

    def test_model_json_is_not_changed_by_editing_data(
        self, qtbot, model_file, opened
    ):
        csv = model_file.parent / "t.csv"
        csv.write_text("a\n1\n")
        model = ModelConfig(str(model_file))
        model.tables.update("Existing", {"url": "t.csv"})
        before = dict(model.tables.config("Existing"))
        page = open_page(qtbot, model, "Existing")
        opened.edit = lambda d: d.grid.set_block(0, 0, [["2"]])
        page.on_edit_data()
        assert model.tables.config("Existing") == before


class TestButton:
    def test_edit_data_button_exists_on_every_table_page(self, qtbot, model_file):
        from PySide6.QtWidgets import QPushButton

        page = open_page(qtbot, ModelConfig(str(model_file)))
        assert page.findChild(QPushButton, "edit_data_button") is not None

    def test_clicking_the_button_opens_the_dialog(
        self, qtbot, model_file, opened
    ):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton

        page = open_page(qtbot, ModelConfig(str(model_file)))
        page.dialog.show()
        qtbot.waitExposed(page.dialog)
        opened.save = False
        qtbot.mouseClick(
            page.findChild(QPushButton, "edit_data_button"), Qt.MouseButton.LeftButton
        )
        assert len(opened.dialogs) == 1
