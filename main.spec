# -*- mode: python ; coding: utf-8 -*-
import re
import shutil
import sys
from pathlib import Path

import pyproj
import pywr
import tables
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# the version in pywr_editor/__init__.py
pywr_editor_version = re.search(
    r'__version__ = "(.+?)"', Path("pywr_editor/__init__.py").read_text()
).group(1)

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
APP_NAME = "Pywr Editor"
ICONS = Path("pywr_editor/assets/ico")

pywr_dist = list(Path(pywr.__file__).parent.parent.glob("pywr-*"))[0]

# Windows-only files: the jump list relies on pywin32 and PyInstaller does not
# collect these files on its own
binaries = []
if IS_WINDOWS:
    from win32com.propsys import propsys

    win32_module_path = Path(propsys.__file__).parent
    binaries = [
        (win32_module_path / "propsys.pyd", "win32com/propsys"),
        (win32_module_path / "pscon.py", "win32com/propsys"),
        (Path(tables.__file__).parent / "libblosc2.dll", "tables"),
    ]

# PyInstaller does not copy the pywr dist info folder when it is in the data
# attribute. On Windows this is copied after the build (see below). Elsewhere, use the
# PyInstaller hook so the folder ends up in the build (and in the macOS app bundle)
metadata = [] if IS_WINDOWS else copy_metadata("pywr")

a = Analysis(
    ["main.py"],
    binaries=binaries,
    datas=[
        ("LEGAL NOTICES.md", "."),
        (str(ICONS / "Pywr Editor.ico"), "."),
        # Pywr hidden imports are not copied. Copy the full package content
        (Path(pywr.__file__).parent, "pywr"),
        # pywr __init__.py relies on the dist info folder to set __version__.
        # This must be manually copied
        # (pywr_dist.as_posix(), pywr_dist.name),
        # pyproj's PROJ datum/grid data is not picked up automatically
        (pyproj.datadir.get_data_dir(), "pyproj/proj_dir/share/proj"),
    ]
    + metadata,
    hiddenimports=[
        "json",
        "pandas",
        "logging",
        "logging.config",
        "pyqtgraph",
        "tables",
        "pywr",
        "pkg_resources",
        "platformdirs",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "inspector_dialog",
        "matplotlib",
        "numpy",
        "pyproj",
        "shapefile",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "jedi", "IPython", "sqlite3"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    # the icon is only used by Windows. The macOS icon is set in the bundle
    icon=str(ICONS / "Pywr Editor.ico") if IS_WINDOWS else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="main",
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ICONS / "Pywr Editor.icns"),
        bundle_identifier="io.github.pywr-editor",
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": pywr_editor_version,
            "NSHighResolutionCapable": True,
            # let the app open JSON files from the Finder
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "JSON file",
                    "CFBundleTypeRole": "Editor",
                    "LSItemContentTypes": ["public.json"],
                    "LSHandlerRank": "Alternate",
                }
            ],
        },
    )

# PyInstaller does not want to copy the following files/folder in the data attr
if IS_WINDOWS:
    shutil.copytree(pywr_dist.as_posix(), f"./dist/main/{pywr_dist.name}")
