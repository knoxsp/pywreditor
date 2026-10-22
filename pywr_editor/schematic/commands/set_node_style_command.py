from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

from pywr_editor.model.constants import UNCHANGED

if TYPE_CHECKING:
    from pywr_editor.schematic import Schematic


class SetNodeStyleCommand(QUndoCommand):
    """
    Undo command used to undo/redo the colour and size of one or more nodes.
    """

    def __init__(
        self,
        schematic: "Schematic",
        node_names: list[str],
        color: str | None | object = UNCHANGED,
        size: float | None | object = UNCHANGED,
    ):
        """
        Initialise the command.
        :param schematic: The Schematic instance.
        :param node_names: The names of the nodes to style.
        :param color: The colour name. None removes the colour, UNCHANGED keeps it.
        :param size: The size factor. None removes the size, UNCHANGED keeps it.
        """
        super().__init__()
        self.schematic = schematic
        self.model_config = schematic.model_config
        self.color = color
        self.size = size
        self.prev: dict[str, tuple] = {}
        for name in node_names:
            node = self.model_config.nodes.node(self.model_config.nodes.config(name))
            self.prev[name] = (node.node_color, node.node_size)

        count = len(node_names)
        target = f"{count} nodes" if count > 1 else f'"{node_names[0]}"'
        self.setText(f"changed the style of {target}")

    def apply(self, styles: dict[str, tuple]) -> None:
        """
        Sets the node styles in the model and redraws the nodes.
        :param styles: The (colour, size) by node name.
        :return: None
        """
        for name, (color, size) in styles.items():
            self.model_config.nodes.set_node_style(name, color=color, size=size)
            item = self.schematic.node_items.get(name)
            if item is not None:
                item.apply_style()
        self.model_config.has_changed()

    def redo(self) -> None:
        self.apply({name: (self.color, self.size) for name in self.prev})

    def undo(self) -> None:
        self.apply(self.prev)


class SetNodeTypeStyleCommand(QUndoCommand):
    """
    Undo command used to undo/redo the colour and size of a node type.
    """

    def __init__(
        self,
        schematic: "Schematic",
        node_type: str,
        color: str | None | object = UNCHANGED,
        size: float | None | object = UNCHANGED,
    ):
        """
        Initialise the command.
        :param schematic: The Schematic instance.
        :param node_type: The node type.
        :param color: The colour name. None removes the colour, UNCHANGED keeps it.
        :param size: The size factor. None removes the size, UNCHANGED keeps it.
        """
        super().__init__()
        self.schematic = schematic
        self.model_config = schematic.model_config
        self.node_type = node_type
        self.color = color
        self.size = size
        prev = self.model_config.node_type_style(node_type)
        self.prev_color, self.prev_size = prev["color"], prev["size"]
        self.setText(f'changed the style of "{node_type}" nodes')

    def apply(self, color, size) -> None:
        self.model_config.set_node_type_style(self.node_type, color=color, size=size)
        for item in self.schematic.node_items.values():
            if item.model_node.type == self.node_type:
                item.apply_style()

    def redo(self) -> None:
        self.apply(self.color, self.size)

    def undo(self) -> None:
        self.apply(self.prev_color, self.prev_size)
