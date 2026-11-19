from importlib.metadata import PackageNotFoundError, version


def installed_pywr_version() -> str | None:
    """
    Returns the version of the pywr package installed in the editor's environment,
    without importing it. pywr v1 and pywr-next both install a package called "pywr",
    so this is either a 1.x or a 2.x version.
    :return: The version or None if pywr is not installed.
    """
    try:
        return version("pywr")
    except PackageNotFoundError:
        return None


def is_pywr_v1_installed() -> bool:
    """
    Checks whether pywr v1 is installed in the editor's environment.
    :return: True if pywr 1.x is installed, False otherwise.
    """
    installed = installed_pywr_version()
    return installed is not None and installed.split(".")[0] in ("0", "1")
