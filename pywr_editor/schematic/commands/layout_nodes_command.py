from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from pywr_editor.schematic import Schematic


class LayoutNodesCommand(QUndoCommand):
    """
    Undo command used to undo/redo the automatic layout of the nodes, which changes
    the schematic position of many nodes at once.
    """

    def __init__(
        self,
        schematic: "Schematic",
        new_positions: dict[str, list[float]],
        geographic: bool = False,
    ):
        """
        Initialise the command.
        :param schematic: The Schematic instance.
        :param new_positions: The new position of each node, by name.
        :param geographic: Whether the positions are the geographic positions (in
        the model's CRS) instead of the schematic positions.
        """
        super().__init__()
        self.schematic = schematic
        self.model_config = schematic.model_config
        self.new_positions = new_positions
        self.geographic = geographic
        self.prev_positions = {}
        for name in new_positions:
            node = self.model_config.nodes.node(self.model_config.nodes.config(name))
            self.prev_positions[name] = (
                node.geographic_position if geographic else node.position
            )
        verb = "estimated the position of" if geographic else "laid out"
        self.setText(f"{verb} {len(new_positions)} nodes")

    def apply(self, positions: dict[str, list[float] | None]) -> None:
        """
        Sets the schematic position of the nodes and draws the schematic again.
        :param positions: The positions by node name.
        :return: None
        """
        for name, position in positions.items():
            if self.geographic:
                self.model_config.nodes.set_geographic_position(
                    node_name=name, position=position
                )
            else:
                self.model_config.nodes.set_position(node_name=name, position=position)
        self.model_config.has_changed()
        self.schematic.reload()

    def redo(self) -> None:
        self.apply(self.new_positions)
        if not self.geographic:
            self.schematic.fit_view()

    def undo(self) -> None:
        self.apply(self.prev_positions)
