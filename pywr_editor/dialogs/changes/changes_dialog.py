import json
from typing import Callable

import qtawesome as qta
from PySide6.QtCore import Slot
from PySide6.QtGui import QFont, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialogs.changes.change_item import change_item
from pywr_editor.dialogs.changes.git_history_widget import GitHistoryTab, StashesTab
from pywr_editor.model import ModelConfig
from pywr_editor.model.git_history import GitHistory


class ChangesDialog(QDialog):
    def __init__(
        self,
        model_config: ModelConfig,
        parent: QWidget | None = None,
        prepare: Callable[[], bool] | None = None,
        reopen: Callable[[], None] | None = None,
    ):
        """
        Initialises the dialog showing the changes applied to the model, one diff for
        each edit. The list is updated while the dialog is open. If the model is in a
        git repository, the dialog also shows the git history and stashes.
        :param model_config: The ModelConfig instance.
        :param parent: The parent widget.
        :param prepare: Function called before git changes the model files. It must
        make sure the editor has no unsaved changes, and return False to cancel.
        Default to a function allowing the change.
        :param reopen: Function called after git changed the model files, to load them
        in the editor.
        """
        super().__init__(parent)
        self.model_config = model_config
        self.setWindowTitle("What has changed")
        self.resize(820, 540)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._session_tab(), "This session")
        self.tabs.addTab(self._summary_tab(), "Summary")

        self.git_tabs: list[QWidget] = []
        history = GitHistory.find(model_config.json_file)
        if history is not None:
            for tab_class, title in (
                (GitHistoryTab, "Git history"),
                (StashesTab, "Stashes"),
            ):
                tab = tab_class(
                    history,
                    prepare or (lambda: True),
                    reopen or (lambda: None),
                )
                self.git_tabs.append(tab)
                self.tabs.addTab(tab, title)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # noinspection PyUnresolvedReferences
        button_box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(button_box)

        self.populate()
        # keep the list up to date while the dialog is open
        self.model_config.model_changed.connect(self.on_model_changed)

    def _session_tab(self) -> QWidget:
        """
        Creates the tab listing the changes made since the model was opened.
        :return: The widget.
        """
        self.info_label = QLabel()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["#", "Time", "Change"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 60)
        self.tree.setColumnWidth(1, 80)

        export_button = QPushButton("Export…")
        export_button.setIcon(qta.icon("msc.export"))
        export_button.setToolTip("Save the changes as a JSON file")
        # noinspection PyUnresolvedReferences
        export_button.clicked.connect(self.export)
        footer = QHBoxLayout()
        footer.addWidget(export_button)
        footer.addStretch()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.info_label)
        layout.addWidget(self.tree)
        layout.addLayout(footer)
        return widget

    def _summary_tab(self) -> QWidget:
        """
        Creates the tab showing the overall difference between the model and its
        saved or original version, grouped by model section.
        :return: The widget.
        """
        self.summary_compare = QComboBox()
        self.summary_compare.addItem("the last saved version", True)
        self.summary_compare.addItem("the model as it was opened", False)
        # noinspection PyUnresolvedReferences
        self.summary_compare.currentIndexChanged.connect(self.populate_summary)
        self.summary_label = QLabel()
        self.summary_tree = QTreeWidget()
        self.summary_tree.setHeaderLabels(["Section", "Changes", "Detail"])
        self.summary_tree.setRootIsDecorated(True)
        self.summary_tree.setAlternatingRowColors(True)
        self.summary_tree.setColumnWidth(0, 180)
        self.summary_tree.setColumnWidth(1, 90)

        header = QHBoxLayout()
        header.addWidget(QLabel("Compare the model with"))
        header.addWidget(self.summary_compare)
        header.addStretch()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addLayout(header)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.summary_tree)
        return widget

    @Slot()
    def populate_summary(self) -> None:
        """
        Fills the summary with the overall changes, grouped by model section. A value
        edited several times is shown once, and edits that were undone are not shown.
        :return: None
        """
        since_saved = bool(self.summary_compare.currentData())
        changes = self.model_config.change_log.net_changes(
            self.model_config.json, since_saved=since_saved
        )
        self.summary_tree.clear()
        if not changes:
            self.summary_label.setText(
                "The model is the same as "
                + ("the last saved version." if since_saved else "when it was opened.")
            )
            return

        sections: dict[str, list] = {}
        for change in changes:
            sections.setdefault(change.section, []).append(change)
        self.summary_label.setText(
            f"{len(changes)} change{'s' if len(changes) != 1 else ''} in "
            f"{len(sections)} section{'s' if len(sections) != 1 else ''}."
        )
        for name, section_changes in sections.items():
            counts = {}
            for change in section_changes:
                counts[change.kind] = counts.get(change.kind, 0) + 1
            top = QTreeWidgetItem(
                [
                    name,
                    str(len(section_changes)),
                    ", ".join(f"{n} {kind}" for kind, n in counts.items()),
                ]
            )
            for change in section_changes:
                top.addChild(change_item(change))
            self.summary_tree.addTopLevelItem(top)
        if len(sections) == 1:
            self.summary_tree.topLevelItem(0).setExpanded(True)

    def showEvent(self, event: QShowEvent) -> None:
        """
        Refreshes the lists when the dialog is shown, as they are not updated while
        hidden.
        :param event: The event.
        :return: None
        """
        self.populate()
        self.on_tab_changed(self.tabs.currentIndex())
        super().showEvent(event)

    @Slot(int)
    def on_tab_changed(self, index: int) -> None:
        """
        Reads the git data when its tab is opened, as git is not run for the tabs the
        user does not use.
        :param index: The index of the tab.
        :return: None
        """
        widget = self.tabs.widget(index)
        if widget in self.git_tabs:
            widget.refresh()

    @Slot()
    def on_model_changed(self) -> None:
        """
        Updates the list when the model changes and the dialog is visible.
        :return: None
        """
        if self.isVisible():
            self.populate()

    @Slot()
    def populate(self) -> None:
        """
        Fills the tree with the change sets, from the newest to the oldest.
        :return: None
        """
        log = self.model_config.change_log
        self.populate_summary()
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        unsaved = len(log.unsaved)
        self.info_label.setText(
            f"{len(log)} change{'s' if len(log) != 1 else ''} since the model was "
            f"opened, {unsaved} not saved yet."
            if len(log)
            else "The model has not been changed since it was opened."
        )

        for change_set in reversed(log.change_sets):
            saved = log.is_saved(change_set)
            top = QTreeWidgetItem(
                [
                    str(change_set.number),
                    change_set.time.strftime("%H:%M:%S"),
                    change_set.summary + ("" if saved else "  (not saved)"),
                ]
            )
            if not saved:
                top.setFont(2, bold)
            for change in change_set.changes:
                top.addChild(change_item(change))
            self.tree.addTopLevelItem(top)
        if self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setExpanded(True)

    @Slot()
    def export(self) -> None:
        """
        Saves the changes in a JSON file.
        :return: None
        """
        file, _ = QFileDialog.getSaveFileName(
            self, "Export the changes", "changes.json", "JSON file (*.json)"
        )
        if not file:
            return
        with open(file, "w") as outfile:
            json.dump(self.model_config.change_log.to_list(), outfile, indent=2)
