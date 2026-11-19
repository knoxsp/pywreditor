---
name: headless-tests
description: Run the pywreditor test suite headlessly. Use whenever running pytest (or launching the app/any Qt code) in this repo, so no windows open on the user's machine.
---

# Running tests headlessly

The tests create real `MainWindow`s and dialogs. Run normally, they open many
windows and take over the user's machine. Always force Qt's offscreen platform
(CI does the same, see `.github/workflows/test.yaml`).

## Commands

PowerShell (primary shell):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"; uv run pytest tests/schematic/test_auto_layout.py -q
```

Bash:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/schematic/test_auto_layout.py -q
```

Run the full suite by dropping the path. Prefer targeted files while iterating.

## Rules

- Never run `pytest` or any script that builds a `MainWindow`/`QApplication`
  without `QT_QPA_PLATFORM=offscreen` set first.
- Do not launch the real GUI (`main.py`) to check a change; use a test, or
  offscreen with a timeout.
- A few tests are skipped under offscreen (e.g. window placement in
  `tests/utils/test_class_settings.py`); that is expected, not a failure.
- Offscreen cannot show you the UI. If a change needs visual confirmation, say
  so and ask the user to check it rather than opening windows.
