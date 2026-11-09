import shutil
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

from pywr_editor.dialects.next import python_code
from pywr_editor.dialogs.next_components.components_dialog import NextParametersDialog
from pywr_editor.dialogs.next_components.python_panel import (
    DryRunDialog,
    PythonHighlighter,
)
from pywr_editor.model import ModelConfig
from tests.utils import model_path

NEXT_MODELS = model_path() / "pywr_next"
DIALOG_MODULE = "pywr_editor.dialogs.next_components.components_dialog"
PANEL_MODULE = "pywr_editor.dialogs.next_components.python_panel"

OTHER_CODE = '''\
import math


def helper(x):
    return math.sqrt(x)


def scale(info, factor):
    return helper(info.get_metric("flow")) * factor
'''


@pytest.fixture(autouse=True)
def no_modal_boxes(monkeypatch):
    monkeypatch.setattr(
        "pywr_editor.form.form.QMessageBox.critical", staticmethod(lambda *args: None)
    )
    monkeypatch.setattr(
        f"{DIALOG_MODULE}.QMessageBox.question",
        staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(
        f"{PANEL_MODULE}.pc.dry_run_python", lambda: sys.executable
    )


@pytest.fixture
def model(tmp_path) -> ModelConfig:
    """A model with a "scale" Python parameter, calling a function of a file."""
    model_file = tmp_path / "model.json"
    shutil.copy(NEXT_MODELS / "time-series.json", model_file)
    model = ModelConfig(str(model_file))
    (tmp_path / "helpers.py").write_text(OTHER_CODE)
    model.parameters.add(
        {
            "type": "Python",
            "meta": {"name": "scaled"},
            "source": {"type": "Path", "path": "helpers.py"},
            "object": {"type": "Function", "function": "scale"},
            "args": [2],
            "metrics": {"flow": {"type": "Literal", "value": 4}},
        }
    )
    return model


def make_dialog(qtbot, model, name=None) -> NextParametersDialog:
    dialog = NextParametersDialog(model=model, selected_name=name)
    qtbot.addWidget(dialog)
    return dialog


def test_panel_shows_the_function_from_the_file(qtbot, model):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    assert panel is not None
    assert panel.editor.toPlainText() == (
        'def scale(info, factor):\n    return helper(info.get_metric("flow")) * factor\n'
    )
    assert not panel.dirty and not dialog.save_button.isEnabled()
    assert panel.file.name == "helpers.py"
    assert panel.check() == []
    assert panel.summary.text() == "No problems found"


def test_other_parameters_have_no_panel(qtbot, model):
    dialog = make_dialog(qtbot, model, "demand")
    assert dialog.panel is None


def test_editing_the_code_saves_only_that_function(qtbot, model, tmp_path):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    panel.editor.setPlainText(
        'def scale(info, factor):\n    return info.get_metric("flow") + factor\n'
    )
    assert dialog.save_button.isEnabled()
    assert dialog.save() is not False
    text = (tmp_path / "helpers.py").read_text()
    assert text.startswith("import math\n\n\ndef helper(x):")
    assert 'return info.get_metric("flow") + factor' in text
    assert "helper(info.get_metric" not in text
    # the editor shows the saved code
    assert dialog.panel.editor.toPlainText().startswith("def scale(info, factor):")
    assert not dialog.save_button.isEnabled()


def test_problems_are_listed_and_marked(qtbot, model):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    panel.editor.setPlainText(
        'def scale(info, factor):\n    return info.get_metric("flwo") * factor\n'
    )
    problems = panel.check()
    assert [p.line for p in problems if p.severity == "error"] == [2]
    assert panel.problems.count() == len(problems)
    texts = [panel.problems.item(i).text() for i in range(panel.problems.count())]
    assert any('Line 2: No metric "flwo"' in text for text in texts)
    assert panel.editor.extraSelections()

    panel.editor.setPlainText("def scale(info, factor:\n    pass\n")
    problems = panel.check()
    assert "Syntax error" in problems[0].message
    assert panel.has_errors()


def test_form_changes_recheck_the_code(qtbot, model):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    args = dialog.form.find_field("args").widget
    args.text.setPlainText("[1, 2, 3]")
    messages = [d.message for d in panel.check()]
    assert any("too many positional arguments" in m for m in messages)


def test_new_python_parameter_gets_starter_code(qtbot, model, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, model, "demand")
    monkeypatch.setattr(dialog, "ask_type", lambda: "Python")
    dialog.on_add()
    name = dialog.current
    assert name == "New python"
    config = model.parameters.config(name)
    file = python_code.module_file(model.json_file)
    assert config["source"] == {"type": "Path", "path": file.name}
    assert config["object"] == {"type": "Function", "function": "new_python"}
    assert "def new_python(info):" in file.read_text()
    panel = dialog.panel
    assert panel.editor.toPlainText() == python_code.starter_code(
        "Function", "new_python"
    )
    assert not panel.dirty
    assert panel.check() == []

    # a second parameter adds its function to the same file
    dialog.on_add()
    assert dialog.current == "New python 2"
    text = file.read_text()
    assert text.count("def new_python(info):") == 1
    assert "def new_python_2(info):" in text


def test_class_object_and_unknown_function(qtbot, model):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    form_object = dialog.form.find_field("object").widget
    assert form_object is not None
    # an object that the file does not define: the editor offers a new function
    model.parameters.update(
        "scaled",
        {
            **model.parameters.config("scaled"),
            "object": {"type": "Function", "function": "other"},
        },
    )
    dialog.reload_list("scaled")
    panel = dialog.panel
    assert panel.editor.toPlainText() == python_code.starter_code("Function", "other")
    assert panel.dirty and dialog.save_button.isEnabled()


def test_module_source_is_not_edited(qtbot, model):
    model.parameters.update(
        "scaled",
        {
            **model.parameters.config("scaled"),
            "source": {"type": "Module", "module": "my_package.params"},
        },
    )
    dialog = make_dialog(qtbot, model, "scaled")
    assert not dialog.panel.editor.isEnabled()
    assert "my_package.params" in dialog.panel.file_label.text()


def test_unsaved_model_asks_to_save(qtbot):
    model = ModelConfig(None, new_dialect="next")
    model.parameters.add(
        {
            "type": "Python",
            "meta": {"name": "p"},
            "source": {"type": "Path", "path": "p.py"},
            "object": {"type": "Function", "function": "f"},
        }
    )
    dialog = make_dialog(qtbot, model, "p")
    assert not dialog.panel.editor.isEnabled()
    assert "Save the model" in dialog.panel.file_label.text()


def test_test_run(qtbot, model):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    run = panel.test_run()
    assert isinstance(run, DryRunDialog)
    qtbot.addWidget(run)
    assert run.inputs.rowCount() == 1
    run.inputs.item(0, 1).setText("16")
    run.steps.setValue(3)
    run.run()
    qtbot.waitUntil(lambda: run.run_button.isEnabled(), timeout=20000)
    assert run.results.rowCount() == 3
    # helper(16) * 2
    assert float(run.results.item(0, 1).text()) == 8.0
    assert run.status.text() == "Ran 3 timesteps"


def test_test_run_shows_errors(qtbot, model, tmp_path):
    (tmp_path / "helpers.py").write_text(
        "def scale(info, factor):\n    print('hello')\n    return 1 / 0\n"
    )
    dialog = make_dialog(qtbot, model, "scaled")
    run = dialog.panel.test_run()
    qtbot.addWidget(run)
    run.run()
    qtbot.waitUntil(lambda: run.run_button.isEnabled(), timeout=20000)
    text = run.output.toPlainText()
    assert "hello" in text and "ZeroDivisionError" in text
    assert run.results.rowCount() == 0


def test_test_run_needs_code_without_errors(qtbot, model):
    dialog = make_dialog(qtbot, model, "scaled")
    panel = dialog.panel
    panel.editor.setPlainText("def scale(info, factor:\n    pass\n")
    panel.check()
    assert panel.test_run() is None
    assert "Fix the errors" in panel.summary.text()


def test_highlighter_marks_code(qtbot):
    from pywr_editor.dialogs.next_components.python_panel import CodeEdit

    editor = CodeEdit()
    qtbot.addWidget(editor)
    editor.setPlainText('def f(x):\n    """doc\n    more"""\n    return 1  # note\n')
    block = editor.document().findBlockByNumber(2)
    assert block.userState() == 0
    # the second line is inside the docstring
    assert editor.document().findBlockByNumber(1).userState() == 2
    formats = editor.document().findBlockByNumber(3).layout().formats()
    assert formats  # return, 1 and the comment are coloured
    assert isinstance(editor.highlighter, PythonHighlighter)
