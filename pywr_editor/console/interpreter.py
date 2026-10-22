import subprocess
import sys


def resolve_interpreter(configured: str | None) -> str:
    """
    Returns the Python interpreter running the console kernel.
    :param configured: The interpreter set by the user. Empty for the editor's own.
    :return: The path to the interpreter.
    """
    return configured.strip() if configured and configured.strip() else sys.executable


def check_interpreter(python: str) -> str | None:
    """
    Checks that an interpreter can run the console kernel and load Pywr models.
    :param python: The path to the interpreter.
    :return: The error message or None if the interpreter is suitable.
    """
    try:
        result = subprocess.run(
            [python, "-c", "import ipykernel, pywr, pandas"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"Cannot run '{python}': {e}"
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1:] or ["unknown error"]
        return (
            f"'{python}' needs the ipykernel, pywr and pandas packages "
            f"installed ({detail[0]})."
        )
    return None
