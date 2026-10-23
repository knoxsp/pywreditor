from typing import TYPE_CHECKING, Any, Literal, Sequence, TypedDict, Union

import PySide6
import qtawesome as qta
from PySide6.QtCore import QPointF, QRectF, QSize, QUuid, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsTextItem,
    QMenu,
)

from pywr_editor.node_shapes import GrayCircle, get_node_icon, get_pixmap_from_type
from pywr_editor.style import Color
from pywr_editor.utils import ModelComponentTooltip
from pywr_editor.widgets import ContextualMenu

from ..model import NodeConfig
from .abstract_schematic_item import AbstractSchematicItem
from .commands.add_node_command import AddNodeCommand
from .commands.disconnect_node_command import DisconnectNodeCommand
from .edge import Edge

if TYPE_CHECKING:
    from pywr_editor.node_shapes import BaseNode
    from pywr_editor.schematic import Schematic


class ConnectedNodeProps(TypedDict):
    source_nodes: list["SchematicNode"]
    """ the list of SchematicItem instances connected to the node """
    target_nodes: list["SchematicNode"]
    """ the list of SchematicItem instances connected from the node """
    count: int
    """ the total number of connected nodes """


class SchematicNode(AbstractSchematicItem, QGraphicsItemGroup):
    padding_y: int = 5
    """ The bounding rectangle x padding """
    padding_x: int = 5
    """ The bounding rectangle y padding """
    outline_width: int = 2
    """ The outline width of the bounding rectangle """
    disabled_node_opacity: float = 0.3
    """ The opacity of the nodes when they are disabled """
    color_ring_radius: float = 17
    """ The radius of the ring drawn around a node with a colour """
    color_choices: list[str] = [
        "red",
        "orange",
        "amber",
        "green",
        "teal",
        "blue",
        "violet",
        "pink",
    ]
    """ The colours offered in the context menu """

    def __init__(
        self,
        node_props: dict,
        view: "Schematic",
        position_override: Sequence[float] | None = None,
    ):
        """
        Initialise the class.
        :param node_props: The node properties from the model dictionary.
        :param view: The view where to draw the item.
        :param position_override: The [x, y] scene position to use instead of the
        node's stored schematic position. Used by the geographic view, which plots
        nodes by their geographic position without touching their stored
        schematic position. Optional.
        :return None
        """
        AbstractSchematicItem.__init__(self, view)
        QGraphicsItemGroup.__init__(self)

        self.model_node = view.model_config.nodes.node(node_props)
        self.name = self.model_node.name
        self.x, self.y = (
            position_override
            if position_override is not None
            else self.model_node.position
        )
        self.edges: list[Edge] = []
        self.view = view
        # the stored geographic position (None if the node does not have one), used
        # to restore it when a move in the geographic view is undone
        self.prev_geographic = (
            list(self.model_node.geographic_position)
            if self.model_node.geographic_position is not None
            else None
        )
        self.tooltip_text = ModelComponentTooltip(
            model_config=view.model_config, comp_obj=self.model_node
        ).render()
        self.setToolTip(self.tooltip_text)

        # allow interaction
        self.setFlag(
            QGraphicsItem.ItemIsMovable,
            self.view.editor_settings.is_schematic_locked is False,
        )
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        # enable notifications for position and transformation changes
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        # speed up rendering performance
        self.setCacheMode(QGraphicsItem.ItemCoordinateCache)
        # enable hover event
        self.setAcceptHoverEvents(True)
        # ensure that node is always stacked on top of its edges
        self.setZValue(0)
        # set position - parent/scene coordinates
        self.setPos(self.x, self.y)

        # node
        node_class = get_node_icon(self.model_node)
        if node_class is not None:
            self.node = node_class(parent=self)
        else:
            self.node = GrayCircle(parent=self)

        # colour ring
        self.color_ring: QGraphicsEllipseItem | None = None

        # label
        self.label = SchematicLabel(
            parent=self,
            name=self.name,
            color=self.node.label,
            hide_label=self.view.editor_settings.are_labels_hidden,
        )

        # add elements to the group
        self.addToGroup(self.node)
        self.addToGroup(self.label)

        self.apply_style()

        # store the position after drawing the item
        self.prev_position = self.scenePos().toTuple()

    @property
    def style_color(self) -> str | None:
        """
        The colour name of the node: its own, otherwise the one of its type.
        :return: The colour name, None if there is not one.
        """
        if self.model_node.node_color is not None:
            return self.model_node.node_color
        return self.view.model_config.node_type_style(self.model_node.type)["color"]

    @property
    def style_size(self) -> float:
        """
        The scale factor of the node symbol: its own, otherwise the one of its type.
        :return: The factor. This is 1 by default.
        """
        if self.model_node.node_size is not None:
            return self.model_node.node_size
        type_size = self.view.model_config.node_type_style(self.model_node.type)["size"]
        return type_size if type_size is not None else 1.0

    def apply_style(self) -> None:
        """
        Applies the colour and size of the node (or of its type). The colour is a
        ring drawn around the node, behind its symbol, which works for any node
        shape. The size scales the symbol.
        :return: None
        """
        self.prepareGeometryChange()
        size = self.style_size
        self.node.setScale(size)
        self.label.setY(self.label.node_bottom_edge * size / 2)

        if self.color_ring is not None:
            self.removeFromGroup(self.color_ring)
            self.color_ring.setParentItem(None)
            if self.color_ring.scene() is not None:
                self.color_ring.scene().removeItem(self.color_ring)
            self.color_ring = None

        color = self.style_color
        if color is not None and color in Color.colors:
            r = self.color_ring_radius * size
            # the parent must be set first, otherwise addToGroup() maps the ring
            # from the scene origin and it is drawn away from the node
            ring = QGraphicsEllipseItem(QRectF(-r, -r, 2 * r, 2 * r), self)
            ring.setPen(QPen(Color(color, 500).qcolor, 3))
            fill = QColor(Color(color, 200).qcolor)
            fill.setAlpha(150)
            ring.setBrush(QBrush(fill))
            ring.setZValue(-1)
            self.color_ring = ring
            self.addToGroup(ring)
        self.update()
        # edges and the footprint polygon follow the style (not available yet
        # while the schematic is being drawn)
        if self.name in self.view.node_items:
            for edge in self.edges:
                edge.adjust()
            footprints = getattr(self.view, "node_footprints", None)
            if footprints is not None:
                footprints.update(self.name)

    def boundingRect(self) -> PySide6.QtCore.QRectF:
        """
        Defined the node bounding rectangle. The label is only included when it is
        visible, otherwise a hidden label would still enlarge the clickable/selection
        area around the node symbol.
        :return: The rectangle.
        """
        rect = self.node.mapRectToParent(self.node.boundingRect())
        if self.color_ring is not None:
            rect = rect.united(
                self.color_ring.mapRectToParent(self.color_ring.boundingRect())
            )
        if self.label.isVisible():
            rect = rect.united(self.label.mapRectToParent(self.label.boundingRect()))

        # add x padding
        rect.setX(rect.x() - self.padding_x)
        # add y padding
        rect.setY(rect.y() - self.padding_y)

        rect.setWidth(rect.width() + self.padding_x)
        rect.setHeight(rect.height() + self.padding_y)
        return rect

    def shape(self) -> PySide6.QtGui.QPainterPath:
        """
        Draws the shape used for hit-testing (clicks, selection, dragging). This is
        always just the node symbol: the label never contributes to it, regardless
        of whether it is shown, so that it is never clickable/draggable itself and
        clicks or drags over it fall through to the schematic underneath instead
        (see Schematic.mousePressEvent).
        :return: The path.
        """
        path = QPainterPath()
        path.addRect(self.node.mapRectToParent(self.node.boundingRect()))
        return path

    def paint(
        self,
        painter: PySide6.QtGui.QPainter,
        option: PySide6.QtWidgets.QStyleOptionGraphicsItem,
        widget: PySide6.QtWidgets.QWidget | None = ...,
    ) -> None:
        """
        Paints the node. Prevents the bounding box from being display when the group
        is selected.
        :param painter: The painter instance.
        :param option: The style options.
        :param widget: The widget.
        :return: None
        """
        if self.isSelected() or (
            self.view.connecting_node_props.enabled and self.node.hover
        ):
            self.draw_outline(painter, option)
        super().paint(painter, option, widget)

    def hoverEnterEvent(
        self, event: PySide6.QtWidgets.QGraphicsSceneHoverEvent
    ) -> None:
        """
        Sets the hover status to True for the shape.
        :param event: The event being triggered.
        :return: None
        """
        self.node.hover = True
        self.node.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(
        self, event: PySide6.QtWidgets.QGraphicsSceneHoverEvent
    ) -> None:
        """
        Sets the hover status to False for the shape.
        :param event: The event being triggered.
        :return: None
        """
        self.node.hover = False
        self.node.update()
        super().hoverLeaveEvent(event)

    def itemChange(
        self,
        change: PySide6.QtWidgets.QGraphicsItem.GraphicsItemChange,
        value: Any,
    ) -> Any:
        """
        Tracks changes.This adjusts the node edges.
        :param change: The change.
        :param value: The value.
        :return: The itemChange event.
        """
        if change == QGraphicsItemGroup.ItemPositionChange:
            if self.view.editor_settings.is_snap_to_grid_enabled:
                grid_size = max(self.view.editor_settings.grid_size, 1)
                value = QPointF(
                    round(value.x() / grid_size) * grid_size,
                    round(value.y() / grid_size) * grid_size,
                )
        elif change == QGraphicsItemGroup.ItemPositionHasChanged:
            for edge in self.edges:
                edge.adjust()
        elif change == QGraphicsItemGroup.ItemSelectedHasChanged:
            # bring the node (and its label) above any overlapping node/edge, and
            # highlight the label, so that it is not obscured when selected
            self.setZValue(1 if value else 0)
            self.label.set_highlighted(bool(value))

        return super().itemChange(change, value)

    def save_position_if_moved(self) -> None:
        """
        Saves the new node position in the configuration file. In the geographic
        view, the position is converted to the model's geographic CRS and saved as
        the node's geographic position, and the schematic position is not changed.
        :return: None
        """
        if not self.has_position_changed():
            return

        if self.view.editor_settings.is_geo_view_enabled:
            geographic = self.view.from_geo_px(*self.position)
            if geographic is None:
                # the new position is outside the map: put the node back
                self.setPos(*self.prev_position)
                return
            self.view.app.model_config.nodes.set_geographic_position(
                node_name=self.name, position=geographic
            )
            self.prev_geographic = geographic
            self.view.node_footprints.update(self.name)
            self.view.update_geo_view_banner()
        else:
            self.view.app.model_config.nodes.set_position(
                node_name=self.name, position=self.position
            )
        self.prev_position = self.position

    def draw_edge(self, edge: Edge) -> None:
        """
        Draws the node edge.
        :param edge: The Edge instance.
        :return: None
        """
        self.edges.append(edge)
        edge.adjust()

    def is_connectable(
        self, connected_node: Union["SchematicNode", None] = None
    ) -> bool:
        """
        Checks that the node can be connected to another one.
        :param connected_node: If provided, the function also checks that this node is
        not connected to the provided node.
        :return: True if the node is connectable, False otherwise.
        """
        if connected_node is not None:
            return (
                not self.model_node.is_virtual
                and not connected_node.model_node.is_virtual
                and self not in connected_node.connected_nodes["source_nodes"]
                and self not in connected_node.connected_nodes["target_nodes"]
            )
        else:
            return not self.model_node.is_virtual

    def delete_edge(
        self, node_name: str, edge_type: Literal["source", "target"]
    ) -> Edge | None:
        """
        Deletes an Edge instance from the list of stores edges for the node.
        :param node_name: The node name to delete.
        :param edge_type: The edge to delete ("source" or "target").
        :return: None
        """
        if edge_type not in ["source", "target"]:
            raise ValueError("edge_type can only be 'source' or 'target'")

        for ei, edge_item in enumerate(self.edges):
            if getattr(edge_item, edge_type).name == node_name:
                del self.edges[ei]
                return edge_item

    @property
    def connected_nodes(self) -> ConnectedNodeProps:
        """
        Returns the connected nodes.
        :return: A dictionary with the following keys:
            - "source_nodes" with a list of the source nodes
            - "target_nodes" with a list of the target nodes
            - "count": the total connected nodes.
        """
        target_nodes = [
            edge.target for edge in self.edges if edge.source.name == self.name
        ]
        source_nodes = [
            edge.source for edge in self.edges if edge.target.name == self.name
        ]

        return ConnectedNodeProps(
            target_nodes=target_nodes,
            source_nodes=source_nodes,
            count=len(target_nodes) + len(source_nodes),
        )

    def add_delete_edge_actions(self, menu: QMenu) -> bool:
        """
        Adds the actions to the menu to remove the edge for the node. The actions can
        be added to a menu or sub-menu. If there are no edges to delete, the actions
        are not added.
        :return: True if the actions are added, False otherwise.
        """
        # always clear the menu first
        menu.clear()

        if self.connected_nodes["count"] == 0:
            return False
        icon_size = QSize(24, 24)
        has_targets = len(self.connected_nodes["target_nodes"]) > 0
        has_sources = len(self.connected_nodes["source_nodes"]) > 0

        if has_targets:
            menu.addAction(ContextualMenu.get_title_action("Target nodes", menu))
        for target_node in self.connected_nodes["target_nodes"]:
            node_type = target_node.model_node.humanised_type
            icon, _ = get_pixmap_from_type(
                icon_size,
                get_node_icon(model_node_obj=target_node.model_node),
            )
            action = menu.addAction(icon, f"{target_node.name} ({node_type})")
            action.setData({"source_node": self, "target_node": target_node})

        if has_targets and has_sources:
            menu.addSeparator()

        if has_sources:
            menu.addAction(ContextualMenu.get_title_action("Source nodes", menu))
        for source_node in self.connected_nodes["source_nodes"]:
            node_type = source_node.model_node.humanised_type
            icon, _ = get_pixmap_from_type(
                icon_size,
                get_node_icon(model_node_obj=source_node.model_node),
            )
            action = menu.addAction(icon, f"{source_node.name} ({node_type})")
            action.setData({"source_node": source_node, "target_node": self})

        # noinspection PyUnresolvedReferences
        menu.triggered.connect(self.on_disconnect_edge)

        return True

    def mouseDoubleClickEvent(self, event) -> None:
        """
        Shows the node data in the dockable node data panel on double-click.
        :param event: The event that triggered this.
        :return: None.
        """
        self.on_show_node_data()

    def contextMenuEvent(
        self, event: PySide6.QtWidgets.QGraphicsSceneContextMenuEvent
    ) -> None:
        """
        Opens the context menu.
        :param event: The event being triggered.
        :return: None
        """
        if self.view.app.is_model_running or self.view.connecting_node_props.enabled:
            return

        # keep a multiple selection when right-clicking one of its nodes
        selected = self.view.selected_nodes
        if self not in selected or len(selected) < 2:
            self.view.de_select_all_items()
            self.setSelected(True)
            selected = [self]
        self.create_context_menu(selected).exec(event.screenPos())

    def create_context_menu(
        self, targets: list["SchematicNode"] | None = None
    ) -> ContextualMenu:
        """
        Creates the node context menu. The same menu is used on the schematic and
        in the components tree.
        :param targets: The nodes the menu acts on, when several nodes are selected.
        Only the actions that make sense for many nodes (colour and hide/show) are
        available then. Defaults to this node only.
        :return: The menu.
        """
        if targets is None or self not in targets:
            targets = [self]
        context_menu = ContextualMenu()
        # menu title
        label = self.name if len(targets) == 1 else f"{len(targets)} nodes"
        max_size = 20
        if len(label) > max_size:
            label = f"{label[0:max_size]}..."
        context_menu.set_title(label)
        icon_color = Color("gray", 500).qcolor

        if len(targets) > 1:
            names = [node.name for node in targets]
            # show the nodes if all of them are hidden, hide them otherwise
            hide = not all(name in self.view.hidden_nodes for name in names)
            hide_action = context_menu.addAction(
                qta.icon("msc.eye-closed" if hide else "msc.eye", color=icon_color),
                "Hide nodes" if hide else "Show nodes on schematic",
            )
            # noinspection PyUnresolvedReferences
            hide_action.triggered.connect(
                lambda *args: self.view.set_nodes_hidden(names, hide)
            )
            self.add_style_action(context_menu, names)
            return context_menu

        # edit node action
        edit_node_action = context_menu.addAction(
            qta.icon("msc.edit", color=icon_color), "Edit node"
        )
        edit_node_action.triggered.connect(self.on_edit_node)
        self.view.addAction(edit_node_action)

        # clone node action
        clone_node_action = context_menu.addAction(
            qta.icon("msc.copy", color=icon_color), "Clone node"
        )
        clone_node_action.triggered.connect(self.on_clone_node)
        self.view.addAction(clone_node_action)

        # delete node action
        delete_node_action = context_menu.addAction(
            qta.icon("msc.trash", color=icon_color), "Delete node"
        )
        delete_node_action.triggered.connect(self.on_delete_item)
        self.view.addAction(delete_node_action)

        # hide/show action
        hidden = self.name in self.view.hidden_nodes
        hide_action = context_menu.addAction(
            qta.icon("msc.eye" if hidden else "msc.eye-closed", color=icon_color),
            "Show node on schematic" if hidden else "Hide node",
        )
        # noinspection PyUnresolvedReferences
        hide_action.triggered.connect(
            lambda *args, name=self.name, hide=not hidden: self.view.set_node_hidden(
                name, hide
            )
        )

        self.add_style_action(context_menu, [self.name])

        # locate action
        locate_action = context_menu.addAction(
            qta.icon("msc.list-tree", color=icon_color),
            "Locate in components tree",
        )
        locate_action.setData(self.name)
        # noinspection PyUnresolvedReferences
        locate_action.triggered.connect(
            lambda *args, name=self.name: self.view.app.components_tree.on_locate_in_tree(  # noqa: E501
                name
            )
        )

        # connect/disconnect edges - skip virtual nodes and hidden nodes
        if not self.model_node.is_virtual and self.isVisible():
            context_menu.addSeparator()
            connect_action = context_menu.addAction(
                qta.icon("msc.arrow-both", color=icon_color), "Connect to..."
            )
            # noinspection PyUnresolvedReferences
            connect_action.triggered.connect(
                lambda *args, node=self: self.view.on_connect_node_start(node)
            )

            # add actions
            if self.connected_nodes["count"] > 0:
                edge_disconnect_submenu = context_menu.addMenu("Disconnect from")
                self.add_delete_edge_actions(edge_disconnect_submenu)

        return context_menu

    def add_style_action(self, menu: ContextualMenu, names: list[str]) -> None:
        """
        Adds the action to open the dialog to change the colour and size of nodes.
        :param menu: The menu.
        :param names: The names of the nodes to style.
        :return: None
        """
        action = menu.addAction(
            qta.icon("msc.symbol-color", color=Color("gray", 500).qcolor),
            "Colour and size...",
        )
        # noinspection PyUnresolvedReferences
        action.triggered.connect(lambda *args: self.view.show_node_style_dialog(names))

    @Slot()
    def on_clone_node(self) -> None:
        """
        Clone the schematic node.
        :return: None
        """
        # add new name and shift the coordinates
        new_node_props = NodeConfig(self.model_node.props, deepcopy=True)
        new_node_props.change_name(f"Node {QUuid().createUuid().toString()[1:7]}")
        new_node_props.change_position([self.x + 100, self.y])

        # register the action in the undo stack
        command = AddNodeCommand(
            schematic=self.view, added_node_dict=new_node_props.props
        )
        self.view.app.undo_stack.push(command)

    @Slot(QAction)
    def on_disconnect_edge(self, action: QAction) -> None:
        """
        Disconnects an edge from two nodes. This will remove the edge from the model
        dictionary, schematic and the edge list.
        :param action: The action containing the source and target nodes to disconnect.
        :return: None
        """
        action_data = action.data()
        source_node = action_data["source_node"]
        target_node = action_data["target_node"]

        command = DisconnectNodeCommand(
            schematic=self.view,
            source_node_name=source_node.name,
            target_node_name=target_node.name,
        )
        self.view.app.undo_stack.push(command)
        self.setSelected(False)

        # update status bar
        self.view.app.status_message.emit(
            f'Deleted edge from "{source_node.name}" to "{target_node.name}"'
        )

    @Slot()
    def on_edit_node(self) -> None:
        """
        Edits a node configuration.
        :return: None
        """
        from pywr_editor.dialogs import NodeDialog

        dialog = NodeDialog(
            node_name=self.name,
            model_config=self.view.model_config,
            parent=self.view.app,
        )
        dialog.show()

    @Slot()
    def on_show_node_data(self) -> None:
        """
        Shows the node configuration in the dockable node data panel.
        :return: None
        """
        self.view.app.node_data_panel.show_node(self.name)


class SchematicLabel(QGraphicsTextItem):
    padding_y: str = 2
    """ Boundary box vertical padding """

    def __init__(
        self,
        parent: "SchematicNode",
        name: str,
        color: Color,
        hide_label: bool = False,
    ):
        """
        Initialises the label.
        :param parent: The parent graphic item.
        :param name: The node name.
        :param color: The node label color.
        """
        super().__init__(parent)
        self.parent = parent
        self.label = name
        self.color = color
        # noinspection PyTypeChecker
        self.symbol: "BaseNode" = parent.node
        self.hide_label = hide_label
        self.node_bottom_edge = self.symbol.boundingRect().height()

        self.setFont(self.font)
        self.render_html()

        self.setAcceptHoverEvents(False)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        # label coordinate system origin is the node location from the group.
        # Shift the box to the symbol edge
        self.setX(-self.boundingRect().width() / 2)
        self.setY(self.node_bottom_edge / 2)

        if self.hide_label:
            self.hide()

    def render_html(self) -> None:
        """
        Sets the label HTML using the colours of the active theme.
        :return: None
        """
        # the colour is resolved again to follow the theme
        color = Color(self.color.name, self.color.shade, self.color.themed)
        background = Color("gray", 50)
        background = f"rgba{str(background.rgba(.4))}"
        self.setHtml(
            f"<div style='color: {color.hex};background-color: {background}; "
            + f"border-radius:4px'>{self.label}</div>"
        )

    def apply_theme(self) -> None:
        """
        Renders the label again after the theme changed.
        :return: None
        """
        self.render_html()
        self.update()

    def shape(self) -> PySide6.QtGui.QPainterPath:
        """
        Returns an empty shape so that the label is never hit-tested on its own.
        The label is still fully painted (shape() does not affect rendering), but
        a QGraphicsItemGroup forwards any event received by a child to the whole
        group regardless of the group's own shape(), so the label itself must be
        made click-through for it to behave as non-interactive (see
        SchematicNode.shape, which already excludes the label from the node's
        own hit area).
        :return: An empty path.
        """
        return QPainterPath()

    @property
    def font(self) -> PySide6.QtGui.QFont:
        """
        Returns the font.
        :return: None
        """
        font = QFont()
        font.setPixelSize(14)
        return font

    def toggle_label(self) -> None:
        """
        Shows or hides the label.
        :return: None
        """
        if self.hide_label:
            self.show()
            self.hide_label = False
        else:
            self.hide()
            self.hide_label = True

    def set_highlighted(self, highlighted: bool) -> None:
        """
        Highlights the label with a bold font when its node is selected. The node
        itself is also brought to the front (see SchematicNode.itemChange) so that
        the label is not left obscured behind overlapping nodes/edges.
        :param highlighted: Whether the node is selected.
        :return: None
        """
        font = self.font
        font.setBold(highlighted)
        self.setFont(font)
