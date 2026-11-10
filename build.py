import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__
import typer

from pywr_editor.assets import get_nodes, get_parameters, get_recorders

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from bundle_uv import UV_VERSION, bundle_uv  # noqa: E402

UV_FOLDER = Path(__file__).parent / "build" / "uv"

app = typer.Typer(pretty_exceptions_enable=False)


@app.command()
def uv():
    """
    Downloads uv, which the editor uses to install pywr-next, to build/uv. The
    executable is added to the bundle by main.spec.
    """
    typer.secho(
        f">> Downloading uv {UV_VERSION} (checksum verified)",
        fg=typer.colors.GREEN,
        bold=True,
    )
    path = bundle_uv(UV_FOLDER)
    typer.secho(f">> Saved {path}", fg=typer.colors.GREEN, bold=True)


@app.command()
def freeze():
    """
    Creates the executable. Run the "uv" command first to bundle uv; without it the
    editor looks for uv on the PATH.
    """
    if not any(UV_FOLDER.glob("uv*")):
        typer.secho(
            ">> uv is not bundled (run `python build.py uv` first)",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    typer.secho(
        ">> Building executable with PyInstaller",
        fg=typer.colors.GREEN,
        bold=True,
    )
    PyInstaller.__main__.run(["main.spec", "--noconfirm"])
    typer.secho(">> Done :)", fg=typer.colors.GREEN, bold=True)


@app.command()
def editor_assets():
    """
    Generates the editor assets.
    """
    assets_path = Path(__file__).parent / "pywr_editor" / "assets"
    qrc_file = assets_path / "assets.qrc"
    py_file = assets_path.parent / "style" / "assets.py"
    subprocess.run(["pyside6-rcc", str(qrc_file), "-o", str(py_file)], check=True)

    typer.secho(f">> Generated {py_file}", fg=typer.colors.GREEN, bold=True)


@app.command()
def pywr_assets():
    """
    Generates the pywr assets.
    """
    typer.secho(
        ">> Creating parameter names dictionary",
        fg=typer.colors.GREEN,
        bold=True,
    )
    get_parameters()
    typer.secho(">> Creating node names dictionary", fg=typer.colors.GREEN, bold=True)
    get_nodes()
    typer.secho(
        ">> Creating recorder names dictionary",
        fg=typer.colors.GREEN,
        bold=True,
    )
    get_recorders()

    qrc_file = Path(__file__).parent / "pywr_editor" / "assets" / "pywr_resources.qrc"
    py_file = Path(__file__).parent / "pywr_editor" / "model" / "pywr_resources.py"
    subprocess.run(["pyside6-rcc", str(qrc_file), "-o", str(py_file)], check=True)

    typer.secho(f">> Generated {py_file}", fg=typer.colors.GREEN, bold=True)


if __name__ == "__main__":
    app()
