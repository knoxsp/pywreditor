"""
Refreshes the bundled pywr-next JSON Schema.

pywr-next generates its schema from its Rust types. Run this with the Python
interpreter of an environment where the pywr-next version to target is installed:

    path/to/pywr-next-env/bin/python scripts/update_pywr_next_schema.py
"""

import json
import tempfile
from importlib.metadata import version
from pathlib import Path

import pywr

SCHEMA_DIR = Path(__file__).parents[1] / "pywr_editor" / "model" / "schemas"
SCHEMA_FILE = "pywr-next-model.schema.json"


def main() -> None:
    pywr_version = version("pywr")
    if pywr_version.startswith("1."):
        raise SystemExit(f"pywr {pywr_version} is pywr v1, not pywr-next")

    with tempfile.TemporaryDirectory() as folder:
        exported = Path(folder) / SCHEMA_FILE
        pywr.export_schema(str(exported))
        schema = json.loads(exported.read_text())

    (SCHEMA_DIR / SCHEMA_FILE).write_text(json.dumps(schema, indent=2) + "\n")
    source = {
        "generator": "pywr.export_schema()",
        "pywr_version": pywr_version,
        "dialect": schema.get("$schema"),
        "files": {SCHEMA_FILE: "ModelSchema (single network)"},
    }
    (SCHEMA_DIR / "SOURCE-pywr-next.json").write_text(
        json.dumps(source, indent=2) + "\n"
    )
    print(f"Updated {SCHEMA_FILE} from pywr {pywr_version}")


if __name__ == "__main__":
    main()
