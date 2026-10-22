<h1 align="center">
  Pywr editor
  <br>
</h1>
<h4 align="center">A graphical user interface to edit Pywr models</h4>

<p align="center">
  <a href="https://www.gnu.org/licenses/gpl-3.0.en.html">
    <img src="https://img.shields.io/badge/license-GPL-blue"
         alt="GPL" />
  </a>
  <a href="https://paypal.me/ssimoncelli87">
    <img src="https://img.shields.io/badge/%C2%A3-donate-red" alt="Donate" />
  </a>
  <a href="https://github.com/pywr-editor/editor/actions/workflows/build.yaml">
    <img src="https://github.com/pywr-editor/editor/actions/workflows/build.yaml/badge.svg" alt="Build" />
  </a>
  <a href="https://github.com/pywr-editor/editor/actions/workflows/test.yaml">
    <img src="https://github.com/pywr-editor/editor/actions/workflows/test.yaml/badge.svg" alt="Unit tests" />
  </a>
  <a href="https://github.com/pywr-editor/editor/actions/workflows/flake8.yaml">
    <img src="https://github.com/pywr-editor/editor/actions/workflows/flake8.yaml/badge.svg" alt="Syntax check" />
  </a>
  
  <br/>
  <br/>
  <img src="screenshots/main_window.png" style="width:700px" alt="Main window"/>
  
</p>



Pywr editor is a user-friendly, free and open‑source graphical user interface (UI) to build and customise [pywr](https://github.com/pywr/pywr) 
models written in [JSON-based document](https://pywr.github.io/pywr/json.html) format. 

Pywr editor provides the following features:

- Full and easy customisation of model parameters, nodes, recorders, metadata, tables, imports and slots directly from the UI
- Dynamic validation of model configuration
- Easily run and debug your model using the toolbar actions
- Support of custom model components
- Interactive model schematic
  - pan, zoom, resize, screenshotting
  - drag, drop or delete multiple nodes at the same time
  - connect or disconnect nodes
  - change colour and shape of nodes
- External data support
  - Automatic parsing of external files to offer suggestions of DataFrame index and column names, and values (from CSV, Excel or HDF files)
  - Data visualisation with charts
  - Import/export value to Excel (export requires a spreadsheet application to view the file)
- Windows integration
  - Open JSON files directly in the editor
  - Browse recent files
  - Pin most used models in the taskbar

> Note: the editor runs on Windows, Linux and macOS. The Windows-only features
> are the taskbar jump list (recent files and tasks) and the installer. Linux and macOS
> support is new and has had less testing than Windows: please
> [report any issue](https://github.com/pywr-editor/editor/issues).

# Screenshot gallery
- [Main window](screenshots/main_window.png)
- [Schematic nodes](screenshots/schematic_nodes.png)
- [Parameter dialog](screenshots/parameter_dialog.png)
- [Scenarios](screenshots/scenarios.png)
- [Model metadata](screenshots/metadata.png)
- [Pandas parsing options with external data](screenshots/tables.png)
- [Available parameters](screenshots/available_parameters.png)
- [Custom component import](screenshots/custom_imports.png)
- [Model run](screenshots/model_run.png)

# Getting started
You can get started with Pywr editor by installing a binary for your platform or running the
repository source code.

## Install the executable
The binaries already bundle Python and all the necessary dependencies. Download them from the
[Release](https://github.com/pywr-editor/editor/releases) page of this project.

### Windows
Download and run [**Pywr_editor_installer.exe**](https://github.com/pywr-editor/editor/releases), or
download and unpack [**Windows_binary.zip**](https://github.com/pywr-editor/editor/releases) and run
the _Pywr Editor.exe_ file.

### Linux
Download [**Pywr_editor_linux.tar.gz**](https://github.com/pywr-editor/editor/releases), unpack it and run
the _Pywr Editor_ file in the `pywr_editor` folder:

  ```bash
    tar -xzf Pywr_editor_linux.tar.gz
    ./pywr_editor/"Pywr Editor"
  ```
The binary is built on Ubuntu and may not work on older distributions. The Qt platform plugin
requires some system libraries (for instance `libegl1`, `libxkbcommon0` and `libfontconfig1` on
Debian-based systems). If the editor does not start, run it from the terminal to see which library
is missing, or run it from the source code.

### macOS
Download [**Pywr_editor_macos.dmg**](https://github.com/pywr-editor/editor/releases) (Apple Silicon only), open it
and drag _Pywr Editor_ to the Applications folder. The app is not signed or notarised: the first time
you run it, right-click the app and choose _Open_ (or allow it in _System Settings > Privacy & Security_).

## Run the Repository source code
You can run Pywr editor using the Python virtual environment on your machine. From your command line:

  ```bash
    # clone the repository first
    git clone https://github.com/pywr-editor/editor.git
    cd editor

    # create a new Python virtual environment
    python -m venv venv
    # Linux and macOS
    source venv/bin/activate
    # Windows
    venv\Scripts\activate

    # install the necessary dependency first:
    pip install -r requirements.txt
    
    # run the editor using
    python main.py
  ```
this requires Python >= 3.10. The pinned dependencies are tested with Python 3.11.

On Linux, Qt may need some system libraries. On Debian-based systems install them with
`sudo apt install libegl1 libxkbcommon0 libfontconfig1`.

# License
This software is licensed under the GNU General Public License, version 3.0+. See the [LICENSE](LICENSE.txt) file
