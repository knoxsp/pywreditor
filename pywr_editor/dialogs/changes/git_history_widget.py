from typing import Callable

import qtawesome as qta
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pywr_editor.dialogs.changes.change_item import change_item
from pywr_editor.model.git_history import Commit, GitError, GitHistory, Stash

ROLE = Qt.ItemDataRole.UserRole
WORKING_TREE = "working"
LOADING = "loading"


class GitTabBase(QWidget):
    def __init__(
        self,
        history: GitHistory,
        prepare: Callable[[], bool],
        reopen: Callable[[], None],
        parent: QWidget | None = None,
    ):
        """
        Base class of the tabs working with git.
        :param history: The GitHistory instance.
        :param prepare: Function called before the model files are changed. It must
        make sure the editor has no unsaved changes, and return False to cancel.
        :param reopen: Function called after the model files were changed to load them
        in the editor.
        :param parent: The parent widget.
        """
        super().__init__(parent)
        self.history = history
        self.prepare = prepare
        self.reopen = reopen
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setAlternatingRowColors(True)
        self.buttons = QHBoxLayout()

        layout = QVBoxLayout(self)
        layout.addWidget(self.info_label)
        layout.addWidget(self.tree)
        layout.addLayout(self.buttons)

    def add_button(self, text: str, icon: str, tooltip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setIcon(qta.icon(icon))
        button.setToolTip(tooltip)
        # noinspection PyUnresolvedReferences
        button.clicked.connect(slot)
        self.buttons.addWidget(button)
        return button

    def error(self, title: str, error: Exception) -> None:
        QMessageBox.critical(self, title, str(error))

    def confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def refresh(self) -> None:
        raise NotImplementedError


class GitHistoryTab(GitTabBase):
    def __init__(self, *args, **kwargs):
        """
        Initialises the tab listing the git commits of the model, which can be
        expanded to see what each commit changed, and can be restored.
        """
        super().__init__(*args, **kwargs)
        self.tree.setHeaderLabels(["Commit", "Date", "Author", "Message"])
        self.tree.setColumnWidth(0, 130)
        self.tree.setColumnWidth(1, 130)
        self.tree.setColumnWidth(2, 110)

        self.restore_button = self.add_button(
            "Restore this version…",
            "msc.discard",
            "Replace the model with the version in the selected commit",
            self.restore,
        )
        self.stash_button = self.add_button(
            "Stash changes…",
            "msc.archive",
            "Put the uncommitted changes aside and return to the last commit",
            self.stash,
        )
        self.buttons.addStretch()
        self.add_button("Refresh", "msc.refresh", "Reload the history", self.refresh)

        self.tree.itemExpanded.connect(self.on_expanded)
        self.tree.itemSelectionChanged.connect(self.update_buttons)
        self.has_uncommitted = False
        self.update_buttons()

    @Slot()
    def refresh(self) -> None:
        """
        Reads the commits again.
        :return: None
        """
        self.tree.clear()
        try:
            commits = self.history.commits()
            self.has_uncommitted = self.history.has_uncommitted_files()
        except GitError as error:
            self.info_label.setText(f"The history cannot be read: {error}")
            return

        self.info_label.setText(
            f"The latest {len(commits)} commit{'s' if len(commits) != 1 else ''} "
            "changing the model. Expand a commit to see what changed in the model."
            if commits
            else "The model has no commits yet."
        )
        if self.has_uncommitted:
            self.tree.addTopLevelItem(
                self._item(
                    ["Uncommitted", "", "", "Saved changes since the last commit"],
                    (WORKING_TREE, None),
                )
            )
        for commit in commits:
            self.tree.addTopLevelItem(
                self._item(
                    [
                        commit.short_hash,
                        commit.date.strftime("%Y-%m-%d %H:%M"),
                        commit.author,
                        commit.subject,
                    ],
                    ("commit", commit),
                )
            )
        self.update_buttons()

    @staticmethod
    def _item(texts: list[str], data: tuple) -> QTreeWidgetItem:
        item = QTreeWidgetItem(texts)
        item.setData(0, ROLE, data)
        # placeholder so that the item can be expanded. The changes are read when it is
        item.addChild(QTreeWidgetItem([LOADING]))
        item.child(0).setData(0, ROLE, (LOADING, None))
        return item

    @Slot(QTreeWidgetItem)
    def on_expanded(self, item: QTreeWidgetItem) -> None:
        """
        Reads what the commit changed when the item is expanded for the first time.
        :param item: The expanded item.
        :return: None
        """
        if item.childCount() != 1 or item.child(0).data(0, ROLE)[0] != LOADING:
            return
        kind, commit = item.data(0, ROLE)
        item.takeChild(0)
        try:
            changes = (
                self.history.uncommitted_changes()
                if kind == WORKING_TREE
                else self.history.commit_changes(commit)
            )
        except GitError as error:
            item.addChild(QTreeWidgetItem(["", "", "", f"Cannot be read: {error}"]))
            return
        if not changes:
            item.addChild(QTreeWidgetItem(["", "", "", "No change in the model"]))
        for change in changes:
            item.addChild(change_item(change, description_column=3))

    def selected_commit(self) -> Commit | None:
        """Returns the commit of the selected item, or of the parent of the change."""
        items = self.tree.selectedItems()
        if not items:
            return None
        item = items[0]
        if item.parent() is not None:
            item = item.parent()
        kind, commit = item.data(0, ROLE) or (None, None)
        return commit if kind == "commit" else None

    @Slot()
    def update_buttons(self) -> None:
        self.restore_button.setEnabled(self.selected_commit() is not None)
        self.stash_button.setEnabled(self.has_uncommitted)

    @Slot()
    def restore(self) -> None:
        """
        Replaces the model with the version of the selected commit.
        :return: None
        """
        commit = self.selected_commit()
        if commit is None:
            return
        if not self.confirm(
            "Restore this version",
            f"Replace the model with the version in commit {commit.short_hash} "
            f"({commit.subject})?\n\nGit is not changed: the restored version is "
            "shown as an uncommitted change, so you can still return to the last "
            "commit.",
        ):
            return
        if not self.prepare():
            return
        try:
            if self.history.has_uncommitted_files():
                if not self.confirm(
                    "Stash the changes",
                    "The model has changes that are not committed. They must be "
                    "stashed before the version is restored. You can apply them again "
                    "from the Stashes tab.\n\nStash the changes and restore the "
                    "version?",
                ):
                    return
                self.history.stash(f"before restoring {commit.short_hash}")
            self.history.restore(commit.hash)
        except GitError as error:
            self.error("The version cannot be restored", error)
            self.refresh()
            return
        self.reopen()

    @Slot()
    def stash(self) -> None:
        """
        Stashes the changes of the model.
        :return: None
        """
        note, ok = QInputDialog.getText(
            self,
            "Stash the changes",
            "The saved changes are put aside and the model returns to its last "
            "commit.\nThey can be applied again from the Stashes tab.\n\nNote:",
        )
        if not ok or not self.prepare():
            return
        try:
            self.history.stash(note)
        except GitError as error:
            self.error("The changes cannot be stashed", error)
            self.refresh()
            return
        self.reopen()


class StashesTab(GitTabBase):
    def __init__(self, *args, **kwargs):
        """
        Initialises the tab listing the stashes created by the editor for the model.
        """
        super().__init__(*args, **kwargs)
        self.tree.setHeaderLabels(["Date", "Note"])
        self.tree.setColumnWidth(0, 140)
        self.apply_button = self.add_button(
            "Apply",
            "msc.history",
            "Put the stashed changes back in the model. The stash is kept",
            self.apply,
        )
        self.delete_button = self.add_button(
            "Delete", "msc.trash", "Delete the stash", self.delete
        )
        self.buttons.addStretch()
        self.add_button("Refresh", "msc.refresh", "Reload the list", self.refresh)
        self.tree.itemSelectionChanged.connect(self.update_buttons)
        self.update_buttons()

    @Slot()
    def refresh(self) -> None:
        self.tree.clear()
        try:
            stashes = self.history.stashes()
        except GitError as error:
            self.info_label.setText(f"The stashes cannot be read: {error}")
            return
        self.info_label.setText(
            "Changes put aside from the Git history tab."
            if stashes
            else "There are no stashed changes of this model."
        )
        for stash in stashes:
            item = QTreeWidgetItem(
                [stash.date.strftime("%Y-%m-%d %H:%M"), stash.message]
            )
            item.setData(0, ROLE, stash)
            self.tree.addTopLevelItem(item)
        self.update_buttons()

    def selected_stash(self) -> Stash | None:
        items = self.tree.selectedItems()
        return items[0].data(0, ROLE) if items else None

    @Slot()
    def update_buttons(self) -> None:
        enabled = self.selected_stash() is not None
        self.apply_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    @Slot()
    def apply(self) -> None:
        stash = self.selected_stash()
        if stash is None:
            return
        if not self.prepare():
            return
        try:
            self.history.apply_stash(stash)
        except GitError as error:
            self.error("The stash cannot be applied", error)
            self.refresh()
            return
        self.reopen()

    @Slot()
    def delete(self) -> None:
        stash = self.selected_stash()
        if stash is None or not self.confirm(
            "Delete the stash",
            f"Delete the stash '{stash.message}'? The changes in it are lost.",
        ):
            return
        try:
            self.history.drop_stash(stash)
        except GitError as error:
            self.error("The stash cannot be deleted", error)
        self.refresh()
