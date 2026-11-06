from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QDialog, QWidget

    from pywr_editor.model import ModelConfig

"""
 A dialect handles one model file format: pywr v1 or pywr-next. The editor detects
 the dialect when a model is opened and asks it for everything that depends on the
 format. The schematic, the map, the sidecar, the shapes, the styles and the undo
 history are shared by all dialects.

 The interface grows as each part of the editor is moved behind it.
"""


@dataclass(frozen=True)
class ComponentKind:
    """
    A kind of model component that is edited in its own dialog, such as the
    parameters or the tables. The main window adds a ribbon button for each kind of
    the model's dialect, and the components tree and the search show only these kinds.
    """

    key: str
    """ The identifier, such as "parameter" """
    label: str
    """ The plural name shown on the ribbon button, such as "Parameters" """
    action_key: str
    """ The key of the ribbon action, such as "edit-parameters" """
    icon: str
    """ The resource path of the ribbon icon """
    tooltip: str
    """ The tooltip of the ribbon button """
    dialog_class: Callable[[], type["QDialog"]]
    """ Returns the class of the dialog. The dialog is imported only when needed """
    shortcut: str | None = None
    """ The keyboard shortcut of the ribbon button, such as "Ctrl+P" """
    large_button: bool = True
    """ Whether the ribbon button is large or a small button in a column """

    def open_dialog(
        self,
        model: "ModelConfig",
        selected_name: str | None = None,
        parent: "QWidget | None" = None,
    ) -> "QDialog":
        """
        Opens the dialog of the components.
        :param model: The model configuration.
        :param selected_name: The name of the component to select. Optional.
        :param parent: The parent widget. Optional.
        :return: The dialog.
        """
        dialog = self.dialog_class()(
            model=model, selected_name=selected_name, parent=parent
        )
        dialog.show()
        return dialog


class ModelDialect(ABC):
    key: str
    """ A short identifier, such as "v1" """
    label: str
    """ The name shown to the user, such as "pywr v1" """
    can_open: bool = True
    """ Whether the editor can open models in this dialect yet """

    @classmethod
    @abstractmethod
    def detect(cls, model_json: Any) -> bool:
        """
        Checks whether a model dictionary is written in this dialect.
        :param model_json: The content of the model file.
        :return: True if the model is in this dialect, False otherwise.
        """

    @abstractmethod
    def empty_model(self) -> dict:
        """
        Returns the dictionary of a new empty model.
        :return: The model dictionary.
        """

    def component_kinds(self) -> list[ComponentKind]:
        """
        Returns the kinds of components edited in their own dialog, in the order
        their ribbon buttons are shown.
        :return: The list of component kinds.
        """
        return []

    def component_kind(self, key: str) -> ComponentKind | None:
        """
        Returns a component kind from its key.
        :param key: The key, such as "parameter".
        :return: The component kind or None if the dialect does not have it.
        """
        for kind in self.component_kinds():
            if kind.key == key:
                return kind
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.key!r}>"
