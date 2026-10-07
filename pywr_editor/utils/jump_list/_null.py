from pathlib import Path


class JumpList:
    """
    No-op jump list used on platforms that do not provide one. It exposes the same
    interface as the Windows implementation.
    """

    def add_task(
        self,
        title: str,
        app_argument: list[str] | None = None,
        icon: str | None = None,
    ) -> None:
        """
        Adds a task. This does nothing.
        :param title: The task title.
        :param app_argument: The application argument needed to run the task.
        :param icon: The link icon name.
        :return: None
        """

    def add_recent_file(self, title: str, file: Path) -> None:
        """
        Adds a recent file. This does nothing.
        :param title: The model title.
        :param file: The path to the file.
        :return: None
        """

    def update(self) -> None:
        """
        Updates the jump list. This does nothing.
        :return: None
        """

    def erase(self) -> None:
        """
        Erases the jump list. This does nothing.
        :return: None
        """
