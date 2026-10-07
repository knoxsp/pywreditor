from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QCheckBox, QWidget

from pywr_editor.style import Color, Theme, stylesheet_dict_to_str

"""
 This is a QCheckBox but acts as a
 toggle switch with a defined style.
"""


class ToggleSwitchWidget(QCheckBox):
    def __init__(self, parent: QWidget = None):
        """
        Initialize the widget.
        :param parent: The parent. Default to None.
        """
        super().__init__(parent)
        self.setStyleSheet(self.stylesheet)

        # Set label at init and when state changes
        self._set_label(
            Qt.CheckState.Checked.value
            if self.isChecked()
            else Qt.CheckState.Unchecked.value
        )
        # noinspection PyUnresolvedReferences
        self.stateChanged.connect(self._set_label)

    @Slot(int)
    def _set_label(self, state: int) -> None:
        """
        Change the label based on the checkbox state.
        :param state: The state.
        :return: None
        """
        self.setText("Yes" if Qt.CheckState(state) == Qt.CheckState.Checked else "No")

    @property
    def stylesheet(self) -> str:
        """
        Returns the stylesheet.
        :return: The stylesheet.
        """
        size = "16px"
        pressed_size = "20px"
        selected_color = Color("blue", 400).hex

        return stylesheet_dict_to_str(
            {
                "ToggleSwitchWidget": {
                    ":disabled": {"color": Theme.overlay(110)},
                    "::indicator": {
                        "background-color": Theme.overlay(15),
                        "border-radius": "9px",
                        "border": f"1px solid {Theme.color('border')}",
                        "height": size,
                        "image": "url(':/form/toggle-switch-off')",
                        "margin-right": "5px",
                        "padding-right": "20px",
                        "padding-left": 0,
                        "width": size,
                        ":hover": {
                            "background-color": Theme.overlay(25),
                            "image": "url(:/form/toggle-switch-off-hover)",
                        },
                        ":pressed": {
                            "background-color": Theme.overlay(24),
                            "image": "url(':/form/toggle-switch-off-pressed')",
                            "padding-right": "16px",
                            "width": pressed_size,
                        },
                        ":checked": {
                            "background-color": selected_color,
                            "border": f"1px solid {selected_color}",
                            "color": "rgb(255, 255, 255)",
                            "image": "url(':/form/toggle-switch-on')",
                            "padding-left": "20px",
                            "padding-right": 0,
                        },
                        ":checked:hover": {
                            "background-color": selected_color,
                            "image": "url(':/form/toggle-switch-on-hover')",
                        },
                        ":checked:pressed": {
                            "background-color": selected_color,
                            "image": "url(':/form/toggle-switch-on-pressed')",
                            "padding-left": "16px",
                            "width": pressed_size,
                        },
                        ":disabled": {
                            "border": f"1px solid {Theme.color('border-strong')}",
                            "image": "url(':/form/toggle-switch-disabled')",
                        },
                    },
                },
            }
        )
