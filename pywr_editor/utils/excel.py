import re
import tempfile
from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook

from pywr_editor.utils.qt import open_external


def export_to_excel(
    header: Sequence[Any],
    rows: Sequence[Sequence[Any]],
    sheet_name: str | None = None,
) -> Path:
    """
    Writes the data to a new temporary Excel file and opens it with the default
    application of the operating system.
    :param header: The column labels.
    :param rows: The table rows.
    :param sheet_name: The name of the sheet. Default to None.
    :return: The path to the Excel file.
    :raises OSError: When the file cannot be opened.
    """
    workbook = Workbook()
    sheet = workbook.active
    if sheet_name:
        # Excel sheet names are max 31 characters and cannot contain []:*?/\
        sheet.title = re.sub(r"[\[\]:*?/\\]", "_", str(sheet_name))[:31]

    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))

    with tempfile.NamedTemporaryFile(
        prefix="pywr_editor_", suffix=".xlsx", delete=False
    ) as file:
        path = Path(file.name)
    workbook.save(path)

    open_external(path)
    return path
