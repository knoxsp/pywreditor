import copy
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialects.next import scenarios as sc
from pywr_editor.widgets import PushIconButton

if TYPE_CHECKING:
    from pywr_editor.model import ModelConfig

"""
 The dialog to edit the scenario domain of a pywr-next model: the groups of scenarios
 with their size, labels and subset, and the combinations of the groups to simulate
 (see dialects/next/scenarios.py). The groups are edited on a copy that is written to
 the model when the user saves.
"""

SUBSET_LABELS = {
    None: "All the scenarios",
    "Slice": "A range",
    "Indices": "Some of them, by number",
    "Labels": "Some of them, by label",
}


def split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def cell_value(text: str) -> int | str:
    """
    Reads a cell of the combinations: a number is the index of a scenario, any other
    text is its label.
    """
    text = text.strip()
    return int(text) if text.isdigit() else text


class NextScenariosDialog(QDialog):
    def __init__(
        self,
        model: "ModelConfig",
        selected_name: str | None = None,
        parent: QWidget | None = None,
    ):
        """
        Initialises the dialog.
        :param model: The model configuration.
        :param selected_name: The name of the group to show. Optional.
        :param parent: The parent widget. Optional.
        """
        super().__init__(parent)
        self.app = parent
        self.model = model
        self.setWindowTitle("Scenarios")
        self.setMinimumSize(900, 600)
        current = model.json.get("scenarios")
        self.domain: dict[str, Any] = (
            copy.deepcopy(current) if isinstance(current, dict) else {"groups": []}
        )
        if not isinstance(self.domain.get("groups"), list):
            self.domain["groups"] = []
        self.original_names = [
            group.get("name") if isinstance(group, dict) else None
            for group in self.domain["groups"]
        ]
        """ The name each group had in the model, to rename its references """
        self.loading = False

        # groups
        self.list = QListWidget()
        self.list.setObjectName("groups_list")
        self.add_button = PushIconButton(icon="msc.add", label="Add")
        self.delete_button = PushIconButton(icon="msc.trash", label="Delete")
        self.up_button = PushIconButton(icon="msc.arrow-up", label="", small=True)
        self.down_button = PushIconButton(icon="msc.arrow-down", label="", small=True)
        self.up_button.setToolTip("Move the group up")
        self.down_button.setToolTip("Move the group down")
        for button, slot in (
            (self.add_button, self.on_add),
            (self.delete_button, self.on_delete),
            (self.up_button, lambda: self.on_move(-1)),
            (self.down_button, lambda: self.on_move(1)),
        ):
            # noinspection PyUnresolvedReferences
            button.clicked.connect(slot)
        buttons = QHBoxLayout()
        for button in (self.add_button, self.delete_button, self.up_button, self.down_button):
            buttons.addWidget(button)
        left = QVBoxLayout()
        left.addWidget(QLabel("Groups of scenarios"))
        left.addWidget(self.list)
        left.addLayout(buttons)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(280)

        # the group
        self.name = QLineEdit()
        self.name.setObjectName("group_name")
        self.size = QSpinBox()
        self.size.setObjectName("group_size")
        self.size.setRange(1, 1_000_000)
        self.labels = QPlainTextEdit()
        self.labels.setObjectName("group_labels")
        self.labels.setPlaceholderText("One label per line. Leave empty to number the scenarios")
        self.labels.setMaximumHeight(110)
        self.subset_type = QComboBox()
        self.subset_type.setObjectName("subset_type")
        for kind, label in SUBSET_LABELS.items():
            self.subset_type.addItem(label, kind)
        self.slice_start = QSpinBox()
        self.slice_start.setObjectName("slice_start")
        self.slice_end = QSpinBox()
        self.slice_end.setObjectName("slice_end")
        for spin in (self.slice_start, self.slice_end):
            spin.setRange(0, 1_000_000)
        slice_page = QWidget()
        slice_layout = QHBoxLayout(slice_page)
        slice_layout.setContentsMargins(0, 0, 0, 0)
        for text, spin in (("From", self.slice_start), ("up to, not including,", self.slice_end)):
            slice_layout.addWidget(QLabel(text))
            slice_layout.addWidget(spin)
        slice_layout.addStretch()
        self.indices = QLineEdit()
        self.indices.setObjectName("subset_indices")
        self.indices.setPlaceholderText("0, 2, 3")
        self.subset_labels = QPlainTextEdit()
        self.subset_labels.setObjectName("subset_labels")
        self.subset_labels.setPlaceholderText("One of the labels of the group per line")
        self.subset_labels.setMaximumHeight(80)
        indices_page = QWidget()
        indices_layout = QVBoxLayout(indices_page)
        indices_layout.setContentsMargins(0, 0, 0, 0)
        indices_layout.addWidget(self.indices)
        indices_layout.addStretch()
        self.subset_pages = QStackedWidget()
        for page in (QWidget(), slice_page, indices_page, self.subset_labels):
            self.subset_pages.addWidget(page)
        self.subset_pages.setMaximumHeight(90)

        group_form = QFormLayout()
        group_form.addRow("Name", self.name)
        group_form.addRow("Number of scenarios", self.size)
        group_form.addRow("Labels", self.labels)
        group_form.addRow("Simulate", self.subset_type)
        group_form.addRow("", self.subset_pages)
        group_widget = QWidget()
        group_widget.setLayout(group_form)

        # combinations
        self.use_combinations = QCheckBox("Only simulate these combinations of scenarios")
        self.use_combinations.setObjectName("use_combinations")
        self.combinations = QTableWidget(0, 0)
        self.combinations.setObjectName("combinations_table")
        self.add_combination_button = PushIconButton(icon="msc.add", label="Add a row")
        self.remove_combination_button = PushIconButton(icon="msc.trash", label="Delete the row")
        self.fill_button = PushIconButton(icon="msc.layers", label="All combinations")
        self.fill_button.setToolTip("Replace the rows with every combination of the groups")
        for button, slot in (
            (self.add_combination_button, self.on_add_combination),
            (self.remove_combination_button, self.on_remove_combination),
            (self.fill_button, self.on_fill_combinations),
        ):
            # noinspection PyUnresolvedReferences
            button.clicked.connect(slot)
        combination_buttons = QHBoxLayout()
        for button in (self.add_combination_button, self.remove_combination_button, self.fill_button):
            combination_buttons.addWidget(button)
        combination_buttons.addStretch()
        hint = QLabel(
            "Each row is a scenario to simulate, with a label or the number (from 0) "
            "of a scenario of each group."
        )
        hint.setWordWrap(True)
        combinations_widget = QWidget()
        combinations_layout = QVBoxLayout(combinations_widget)
        combinations_layout.addWidget(self.use_combinations)
        combinations_layout.addWidget(hint)
        combinations_layout.addWidget(self.combinations, 1)
        combinations_layout.addLayout(combination_buttons)

        self.tabs = QTabWidget()
        self.tabs.addTab(group_widget, "Group")
        self.tabs.addTab(combinations_widget, "Combinations")

        self.summary = QLabel()
        self.summary.setObjectName("scenarios_summary")
        self.problems = QLabel()
        self.problems.setObjectName("scenarios_problems")
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #d13438")
        self.save_button = PushIconButton(icon="msc.save", label="Save", accent=True)
        self.save_button.setObjectName("save_button")
        self.save_button.setEnabled(False)
        close_button = PushIconButton(icon="msc.close", label="Close")
        # noinspection PyUnresolvedReferences
        self.save_button.clicked.connect(self.save)
        # noinspection PyUnresolvedReferences
        close_button.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.save_button)
        bottom.addWidget(close_button)

        right = QVBoxLayout()
        right.addWidget(self.tabs, 1)
        right.addWidget(self.summary)
        right.addWidget(self.problems)
        right.addLayout(bottom)
        layout = QHBoxLayout(self)
        layout.addWidget(left_widget)
        layout.addLayout(right, 1)

        for signal in (
            self.name.textChanged,
            self.size.valueChanged,
            self.labels.textChanged,
            self.subset_type.currentIndexChanged,
            self.slice_start.valueChanged,
            self.slice_end.valueChanged,
            self.indices.textChanged,
            self.subset_labels.textChanged,
        ):
            # noinspection PyUnresolvedReferences
            signal.connect(self.on_group_edited)
        # noinspection PyUnresolvedReferences
        self.list.currentRowChanged.connect(self.show_group)
        # noinspection PyUnresolvedReferences
        self.use_combinations.toggled.connect(self.on_combinations_toggled)
        # noinspection PyUnresolvedReferences
        self.combinations.itemChanged.connect(self.on_combination_edited)

        self.reload_list(selected_name)

    # --- the list of groups --------------------------------------------------

    @property
    def groups(self) -> list[dict]:
        return self.domain["groups"]

    def group_name(self, group: dict) -> str:
        return group.get("name") or "(no name)"

    def reload_list(self, selected: str | int | None = None) -> None:
        """
        Fills the list of groups.
        :param selected: The name or row of the group to select. Optional.
        :return: None
        """
        self.loading = True
        self.list.clear()
        for group in self.groups:
            self.list.addItem(
                QListWidgetItem(f"{self.group_name(group)} ({group.get('size', '?')})")
            )
        row = selected if isinstance(selected, int) else None
        if isinstance(selected, str):
            names = [g.get("name") for g in self.groups]
            row = names.index(selected) if selected in names else None
        if row is None and self.groups:
            row = 0
        self.loading = False
        if row is not None:
            self.list.setCurrentRow(row)
        self.show_group(row if row is not None else -1)
        self.fill_combinations_table()
        self.update_state()

    def current_group(self) -> dict | None:
        row = self.list.currentRow()
        return self.groups[row] if 0 <= row < len(self.groups) else None

    @Slot(int)
    def show_group(self, row: int) -> None:
        """
        Shows the group in the form.
        :param row: The row of the group in the list. -1 clears the form.
        :return: None
        """
        group = self.groups[row] if 0 <= row < len(self.groups) else None
        self.loading = True
        for widget in (
            self.name,
            self.size,
            self.labels,
            self.subset_type,
            self.slice_start,
            self.slice_end,
            self.indices,
            self.subset_labels,
        ):
            widget.setEnabled(group is not None)
        self.delete_button.setEnabled(group is not None)
        self.up_button.setEnabled(group is not None and row > 0)
        self.down_button.setEnabled(group is not None and row < len(self.groups) - 1)
        if group is None:
            self.name.clear()
            self.labels.clear()
            self.indices.clear()
            self.subset_labels.clear()
        else:
            self.name.setText(group.get("name") or "")
            size = group.get("size")
            self.size.setValue(size if isinstance(size, int) and size >= 1 else 1)
            self.labels.setPlainText("\n".join(group.get("labels") or []))
            subset = group.get("subset") or {}
            kind = subset.get("type") if isinstance(subset, dict) else None
            self.subset_type.setCurrentIndex(max(self.subset_type.findData(kind), 0))
            self.slice_start.setValue(subset.get("start", 0) if kind == "Slice" else 0)
            self.slice_end.setValue(
                subset.get("end", self.size.value()) if kind == "Slice" else self.size.value()
            )
            self.indices.setText(
                ", ".join(str(i) for i in subset.get("indices", [])) if kind == "Indices" else ""
            )
            self.subset_labels.setPlainText(
                "\n".join(subset.get("labels", [])) if kind == "Labels" else ""
            )
        self.subset_pages.setCurrentIndex(self.subset_type.currentIndex())
        self.loading = False

    @Slot()
    def on_group_edited(self) -> None:
        """
        Copies the form to the group.
        :return: None
        """
        self.subset_pages.setCurrentIndex(self.subset_type.currentIndex())
        group = self.current_group()
        if self.loading or group is None:
            return
        group["name"] = self.name.text().strip()
        group["size"] = self.size.value()
        labels = split_lines(self.labels.toPlainText())
        if labels:
            group["labels"] = labels
        else:
            group.pop("labels", None)
        kind = self.subset_type.currentData()
        if kind == "Slice":
            group["subset"] = {
                "type": "Slice",
                "start": self.slice_start.value(),
                "end": self.slice_end.value(),
            }
        elif kind == "Indices":
            indices = []
            for part in self.indices.text().split(","):
                part = part.strip()
                if part.isdigit():
                    indices.append(int(part))
                elif part:
                    indices.append(-1)  # not valid: the check reports it
            group["subset"] = {"type": "Indices", "indices": indices}
        elif kind == "Labels":
            group["subset"] = {
                "type": "Labels",
                "labels": split_lines(self.subset_labels.toPlainText()),
            }
        else:
            group.pop("subset", None)
        item = self.list.item(self.list.currentRow())
        if item is not None:
            item.setText(f"{self.group_name(group)} ({group['size']})")
        self.fill_combinations_table(keep_rows=True)
        self.update_state()

    def unique_name(self) -> str:
        names = {g.get("name") for g in self.groups}
        number = len(names) + 1
        while f"Scenario {number}" in names:
            number += 1
        return f"Scenario {number}"

    @Slot()
    def on_add(self) -> None:
        self.groups.append({"name": self.unique_name(), "size": 1})
        self.original_names.append(None)
        for combination in self.domain.get("combinations") or []:
            combination.append(0)
        self.reload_list(len(self.groups) - 1)
        self.save_button.setEnabled(True)

    @Slot()
    def on_delete(self) -> None:
        row = self.list.currentRow()
        group = self.current_group()
        if group is None:
            return
        name = self.original_names[row]
        message = f'Delete the group "{self.group_name(group)}"?'
        used = sc.count_group_references(self.model.json, name) if name else 0
        if used:
            message += (
                f"\n\nIt is used by {used} component"
                f"{'s' if used != 1 else ''} of the model, which will be left "
                "pointing to a group that does not exist."
            )
        answer = QMessageBox.question(
            self,
            "Delete group",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self.groups[row]
        del self.original_names[row]
        for combination in self.domain.get("combinations") or []:
            if row < len(combination):
                del combination[row]
        self.reload_list(min(row, len(self.groups) - 1) if self.groups else None)
        self.save_button.setEnabled(True)

    def on_move(self, step: int) -> None:
        row = self.list.currentRow()
        target = row + step
        if not (0 <= row < len(self.groups) and 0 <= target < len(self.groups)):
            return
        for items in (self.groups, self.original_names):
            items[row], items[target] = items[target], items[row]
        for combination in self.domain.get("combinations") or []:
            if max(row, target) < len(combination):
                combination[row], combination[target] = combination[target], combination[row]
        self.reload_list(target)
        self.save_button.setEnabled(True)

    # --- combinations ----------------------------------------------------------

    def fill_combinations_table(self, keep_rows: bool = False) -> None:
        """
        Shows the combinations in the table.
        :param keep_rows: Only update the headers.
        :return: None
        """
        combinations = self.domain.get("combinations") or []
        self.loading = True
        self.combinations.setColumnCount(len(self.groups))
        self.combinations.setHorizontalHeaderLabels([self.group_name(g) for g in self.groups])
        if not keep_rows:
            self.combinations.setRowCount(len(combinations))
            for row, combination in enumerate(combinations):
                for column, value in enumerate(combination[: len(self.groups)]):
                    self.combinations.setItem(row, column, QTableWidgetItem(str(value)))
        self.use_combinations.setChecked(bool(combinations))
        self.set_combinations_enabled(bool(combinations))
        self.loading = False

    def set_combinations_enabled(self, enabled: bool) -> None:
        for widget in (
            self.combinations,
            self.add_combination_button,
            self.remove_combination_button,
            self.fill_button,
        ):
            widget.setEnabled(enabled)

    @Slot(bool)
    def on_combinations_toggled(self, checked: bool) -> None:
        if self.loading:
            return
        self.set_combinations_enabled(checked)
        if checked:
            if not self.domain.get("combinations"):
                self.on_fill_combinations()
                return
        else:
            self.domain.pop("combinations", None)
            self.combinations.setRowCount(0)
        self.save_button.setEnabled(True)
        self.update_state()

    def read_combinations(self) -> list[list]:
        rows = []
        for row in range(self.combinations.rowCount()):
            values = []
            for column in range(self.combinations.columnCount()):
                item = self.combinations.item(row, column)
                values.append(cell_value(item.text()) if item else "")
            rows.append(values)
        return rows

    @Slot(QTableWidgetItem)
    def on_combination_edited(self, item: QTableWidgetItem) -> None:
        if self.loading:
            return
        self.domain["combinations"] = self.read_combinations()
        self.save_button.setEnabled(True)
        self.update_state()

    @Slot()
    def on_add_combination(self) -> None:
        row = self.combinations.rowCount()
        self.combinations.setRowCount(row + 1)
        self.loading = True
        for column in range(self.combinations.columnCount()):
            self.combinations.setItem(row, column, QTableWidgetItem("0"))
        self.loading = False
        self.domain["combinations"] = self.read_combinations()
        self.save_button.setEnabled(True)
        self.update_state()

    @Slot()
    def on_remove_combination(self) -> None:
        row = self.combinations.currentRow()
        if row < 0:
            return
        self.combinations.removeRow(row)
        self.domain["combinations"] = self.read_combinations()
        self.save_button.setEnabled(True)
        self.update_state()

    @Slot()
    def on_fill_combinations(self) -> None:
        """
        Replaces the combinations with every combination of the scenarios of the
        groups that are simulated.
        :return: None
        """
        import itertools

        choices = []
        for group in self.groups:
            indices = sc.subset_indices(group) or []
            labels = group.get("labels") or []
            choices.append([labels[i] if i < len(labels) else i for i in indices])
        self.domain["combinations"] = [list(c) for c in itertools.product(*choices)]
        self.fill_combinations_table()
        self.save_button.setEnabled(True)
        self.update_state()

    # --- checks and saving -----------------------------------------------------

    def update_state(self) -> list[str]:
        """
        Checks the domain and shows the number of scenarios.
        :return: The problems found.
        """
        domain = self.cleaned_domain()
        problems = sc.validate_domain(domain) if domain else []
        self.problems.setText("\n".join(problems))
        total = sc.total_scenarios(domain) if domain and not problems else None
        if not self.groups:
            self.summary.setText("No scenarios: the model runs once")
        elif total is not None:
            self.summary.setText(
                f"{total:,} scenario{'s' if total != 1 else ''} simulated"
            )
        else:
            self.summary.setText("")
        return problems

    def cleaned_domain(self) -> dict | None:
        """
        Returns the domain as it is written to the model.
        :return: The dictionary, None if there are no groups.
        """
        if not self.groups:
            return None
        domain = copy.deepcopy(self.domain)
        if not domain.get("combinations"):
            domain.pop("combinations", None)
        return domain

    @Slot()
    def save(self) -> bool:
        """
        Saves the scenarios in the model and renames the groups in the components that
        use them.
        :return: True if the scenarios were saved, False if they are not valid.
        """
        if self.update_state():
            return False
        domain = self.cleaned_domain()
        renamed = 0
        for original, group in zip(self.original_names, self.groups):
            if original and group["name"] != original:
                renamed += sc.rename_group_references(self.model.json, original, group["name"])
        if domain is None:
            self.model.json.pop("scenarios", None)
        else:
            self.model.json["scenarios"] = domain
        self.original_names = [g["name"] for g in self.groups]
        self.model.has_changed()
        self.save_button.setEnabled(False)
        app = self.app
        if app is not None:
            if hasattr(app, "components_tree"):
                app.components_tree.reload()
            if hasattr(app, "statusBar"):
                text = "Updated the model scenarios"
                if renamed:
                    text += f" and {renamed} reference{'s' if renamed != 1 else ''}"
                app.statusBar().showMessage(text)
        return True

    def has_unsaved_changes(self) -> bool:
        return self.save_button.isEnabled()

    def closeEvent(self, event) -> None:
        if self.has_unsaved_changes():
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                "Discard the changes to the scenarios?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        super().closeEvent(event)
