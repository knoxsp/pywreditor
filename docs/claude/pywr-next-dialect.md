# pywr-next dialect work: context for Claude

This is the working record of the work Claude has done in this repository to make the
pywr v1 editor edit pywr-next (pywr 2.x) models. **Read it before starting work, so the
codebase does not have to be re-read.** Update it in every commit (see "Rules for every
commit"). Last updated for the watchdog commit (see the end of section 9). Nothing is pending
unless section 8 says so.

## 1. Goal and approach

One editor, two model formats, switched by a **dialect** (`v1`, `next`). A model is a
pywr-next model when it has a `network` object (or a `networks` list). The v1 code is
unchanged; pywr-next support is added behind `ModelDialect` and a `features` set that
gates the UI. The user chose a dialect switch over a fork.

- Repository: `knoxsp/pywreditor` (PySide6). GitHub milestone "pywr-next dialect
  support", issues #15-#47. Draft PR **#42**: `pywr-next-dialect` into `main`.
- Issues stay open until the PR merges ("Closes #N" in commits). #46 was closed by hand.
- `gh issue view` fails (classic Projects GraphQL error): use `gh api repos/knoxsp/pywreditor/issues/N`.

## 2. Branches and worktrees

| Path | Branch | Whose | Notes |
|---|---|---|---|
| `/home/stephen/git/pywr/editor-next` | `pywr-next-dialect` | Claude's work | Based on `main`; includes dark mode (merged at `0ee05c6`). All pywr-next work happens here. |
| `/home/stephen/git/pywr/editor` | `dark-mode` | The user's | Has uncommitted changes (`main_window.py`, `model_config.py`, tests). **Do not touch.** |
| `/home/stephen/git/pywr/dmbase` | detached `867ea7c` | Not from this work | Leave alone. |

`pywr-next-dialect` is the only branch Claude created for this work. Other local branches
(`add-geographic-view`, `editor-sidecar`, `dark-mode`, `fix-ci`, ...) belong to the user's
own work. The geographic view feature has its own memory note.
`main` includes dark mode and the sidecar (`#11`, `#12`).

## 3. Decisions (and who made them)

| Decision | Made | Where it shows |
|---|---|---|
| One editor with a dialect switch, not a fork | User, 2026-11-06 | `pywr_editor/dialects/` |
| Positions live in `meta.position` (`schematic`, `geographic`). Put as much as possible in the pywr-next schema; only application data (shapes, map, GIS layers, GeoJSON footprint) stays in the sidecar (#21) | User | `dialects/next/model.py`, `model/sidecar.py` |
| Multi-network models are refused for now (#24) | User | `dialects/next/__init__.py` load error |
| The editor installs pywr-next into its own environment after a consent prompt that shows the location (#36) | User | `environments.py`, `dialogs/environments/` |
| Python parameter code goes in an editor-managed `.py` file next to the model (`<model>_parameters.py`); inline code is to be proposed upstream (#39) | User | `dialects/next/python_code.py` |
| Node colour, size and style go in `meta.tags` as `editor:*` keys (#44) | User | `model/editor_tags.py` |
| Running is via the stepping runner service, and the editor must be able to step (#37) | User | `dialects/next/runner.py` |
| Priorities order: #39, #32, "#53", #38, #31, #40. "#53" does not exist; Claude took it as #35 and said so | User, 2026-11-09 | commits below |
| Results of pywr-next runs are converted to the v1 results folder format so the existing viewer reads them | Claude | `dialects/next/results.py` |
| The runner service ends with the editor on every platform through a stdin watchdog (the editor keeps the pipe open) plus `PR_SET_PDEATHSIG` on Linux | Claude, with the user's go-ahead 2026-11-10 | `runner_protocol.SERVER_SNIPPET` |
| Prevent invalid input using the schemas, in both versions: **block** only what is certain to break the schema or can never work; **warn** in the validation step on what is merely likely to cause trouble. Stricter than pywr v1 where needed; **dead links are not allowed**. Order: connections (#48), pywr-next forms (#49), v1 forms (#50) | User, 2026-11-10 | issues #48-#50 |
| Branches for that work: the parts that do not need the dialect classes are built on a branch off `dark-mode` (which equals `main`, has no `dialects/`), then `dark-mode` is merged into `pywr-next-dialect` and the pywr-next parts are built there | User, 2026-11-10 | issues #48-#50 |
| Unplaced nodes use their geographic position, projected like the geographic view | Claude (issue #46 proposal) | `schematic/schematic.py` `draw()` |

Still open: #24 (read-only multi-network), #43 (crash root cause), #45 (bundle uv),
#47 (service lifetime on Windows/macOS), style profiles and model kinds from #44.

## 4. Architecture map

Dialects (`pywr_editor/dialects/`)
- `base.py`: `ModelDialect` (abstract) with `key`, `features` (frozenset), `node_types()`,
  `node_shape_name()`, `create_node()`, `create_run_worker()`, `simple_time()`,
  `setup_model()`, and `ComponentKind` (`key`, ribbon button, dialog, optional `panel`).
- `registry.py`: `detect_dialect()`, `get_dialect()`. `v1/__init__.py`, `next/__init__.py`.
- Features used in `next`: `node-dialog`, `run`, `run-results`, `metric-sets`.
  `v1` also has `convert-to-next`, `node-data-panel`, imports, slots, etc.
- `next/` modules: `model.py` (NextNodes, NextNodeConfig, NextEdges, VirtualNodes),
  `schema.py` (reads the bundled JSON Schema), `validation.py`, `references.py`
  (typed find/rename), `time_domain.py`, `scenarios.py`, `metric_sets.py`,
  `python_code.py`, `runner_protocol.py`, `runner.py`, `results.py`, `conversion.py`.

Models: `model/model_config.py` (asks the dialect to `setup_model`),
`model/schemas/pywr-next-model.schema.json` + `SOURCE-pywr-next.json` (bundled from pywr
2.0.0rc1; refresh with `scripts/update_pywr_next_schema.py`), `model/sidecar.py`
(`split_model`, `merge_editor_data`, `write_sidecar`), `model/editor_tags.py`.

UI: `form/schema_form.py` (forms from the schema), `form/widgets/metric_widget.py`,
`dialogs/next_components/` (components dialog for parameters, tables, time series, metric
sets, outputs; Python panel; add-to-metric-set), `dialogs/next_domain/` (time, scenarios),
`dialogs/node/next_node_dialog.py`, `dialogs/convert/convert_dialog.py`,
`dialogs/environments/install_dialog.py`, `node_shapes/pywr/next_nodes.py`,
`toolbar/run_controls/` (`run_widget.py`, `timestepper.py`), `schematic/schematic.py`.

Environments (`pywr_editor/environments.py`): pywr-next installs the same `pywr` package
as v1, so it gets its own environment (uv, extras `pandas,excel`). Helper programs (the
Python parameter dry run, Arrow-to-CSV conversion, v1-to-next conversion) run in that
environment's Python in subprocesses; the editor never imports pywr-next.

## 5. pywr-next 2.0.0rc1 facts (verified against the real package)

- Python parameter: function called as `func(info, *args, **kwargs)`; class built as
  `Class(*args, **kwargs)` and needs `before(info)` or `after(info)`, optional
  `after_hook(info)` (not with `after`). `info` has `timestep`, `scenario_index`,
  `get_metric(name)`, `get_index(name)`.
- Metric literal: `{"type": "Literal", "value": ...}`. Time: `time` with a `timestep` of
  Days, Hours or Frequency (jiff friendly format: "7d", "1 month", "P7D"; no "and").
- CSV output rounds to 2 decimals (`decimal_places` ignored for Wide); ArrowStream is
  exact (needs `batch_size`) and carries `PYWR_SCENARIOS`/`PYWR_SCENARIO_GROUPS`.
  A cancelled run flushes the partial batch.
- Scenarios: groups of `name`, `size`, `labels`, `subset`; `combinations`.
- Converter: `pywr.convert_model_from_v1_json_string` returns `(ModelSchema, errors)`.
- Edges (tested 2026-11-10): neither JSON Schema constrains connections (edges are names
  only). pywr-next refuses, when it builds the network, an edge into an `Input`, out of an
  `Output`, a self-loop and a duplicate (`Duplicate edge found`); its Python error only says
  "Network schema validation failed. The network has 1 problem(s)". It accepts Link->Link,
  Storage->Output, Input->Storage. pywr v1 1.23.0 accepts all of these without error at
  `connect()`, `setup()` and `run()` (the edges are dead); its structural errors are
  network-wide: "not part of any routes", "no valid routes". Probe scripts: the
  `next_probe.py`/`next_probe2.py` approach (build a valid Input->Link->Output chain, add
  one edge, `pywr.ModelSchema.from_json_string(...).build(".", None)`).
- Schema constraint counts: pywr-next has 41 `minimum`, 9 `maximum`, 14 `enum`, 177 `const`;
  pywr v1 has 20 `minimum`, 66 `enum` and, in the strict schema only, 41 `pattern`.
  The pywr-next forms use only `required`, enum and `minimum` today; the v1 forms are
  hand-written and do not use the schema.
- Runner service: `pywr._pywr.run_server(name)`; abstract local socket on Linux; frames of
  a 4-byte length plus JSON; commands step, run_until, run_to_end, cancel. It stays
  listening after a run and does not exit when its client disconnects. A stdin watchdog
  thread does stop it, also mid-run (the earlier belief that the GIL prevents this was
  wrong).

## 6. How to test

- Always `QT_QPA_PLATFORM=offscreen` (otherwise GUI tests take over the desktop).
- Real-service tests need `PYWR_NEXT_PYTHON=<python of an env with pywr==2.0.0rc1[pandas,excel]>`.
- Forms that fail validation open a modal `QMessageBox`: patch
  `pywr_editor.form.form.QMessageBox.critical` or the test hangs.
- Do not pipe a full-suite run through `tail` when hunting a crash: the traceback is lost.
  Crashes are kept by systemd: `coredumpctl list`, `coredumpctl dump <pid> -o file`, then
  `pystack core <file> <python>` for Python frames and `gdb -batch -ex "thread 1" -ex bt`.
- Do not `pkill -f` with a pattern that matches your own shell command.
- isort on explicit file paths reorders `__init__.py` and breaks imports: use
  `--filter-files`.
- Real test model: `/home/stephen/git/models/thames-adaptive/v2/` (62 nodes, only
  geographic positions). Use copies; do not commit it.
- Current result: 3171 passed, 14 skipped (full suite, real-service tests on).

## 7. Known issues and open threads

- **#43 crash (unexplained part).** Rare SIGSEGV in `tests/conftest.py`
  `delete_windows_after_test` at `app.topLevelWidgets()` (freed widget still registered;
  the first widget walk after a test is probably where earlier heap damage shows up).
  Seen 2026-11-09 12:01 and 2026-11-10 14:54, both in full runs. Across the 15 full runs
  since the thread fix (6 + 1 crashed + 8 verbose) it happened once; the 8 verbose runs
  (`-v`, so a crash names its test) were all clean. If it happens again, keep the whole
  log (no `tail`) and the dump, and look at the test named on the last line and the one
  before it. The QThread-deletion abort part is fixed (`caba1b8`). Issue #43 stays open.
- Planned (decided 2026-11-10, not started): #48 refuse dead/invalid edges and warn on doubtful
  ones (stage A off `dark-mode`, stage B on `pywr-next-dialect`), #49 pywr-next forms
  constrained by the schema, #50 v1 forms (blocked until the neutral checking code from #49 is
  on `dark-mode`). Severity rule for existing models: dead/invalid edge = error for pywr-next,
  warning for v1. No-route problems are warnings.
- Closing the window during a pywr v1 run only calls `worker.kill()` and does not wait for
  the thread (pywr-next waits in `NextRunWorker.shutdown()`).
- Left undone on purpose: Python aggregation functions in outputs are not editable;
  virtual nodes cannot be added from the node library; live node values are not shown
  while stepping; recorders are not converted to metric sets; removing a node from a
  metric set has no UI.

## 8. Pending (uncommitted) work

Nothing.

## 9. Commit log with decisions

Every commit on `pywr-next-dialect` is listed in order. Format: hash, issue, what, and
the decisions or facts that are not obvious from the diff.

### Foundations
- `d6bd654` #15: `EdgeRecord`/`Edges.records()` so code outside the model layer does not
  index v1 edge lists. Also fixed `Schematic.delete_edge()` (passed the whole edge list as
  the node name and deleted nothing).
- `cf6772e` #16: pywr v1 imported lazily; the editor starts with neither pywr installed.
  `assets/utils.py` imports remain only for `build.py`.
- `b277cc8` #17: dialects and `detect_dialect()`. Anything without `network`/`networks`
  is read as v1 so v1 validation still explains it. Added one pywr-next example model
  (MIT licence).
- `5052d81`: bug fix: deleting a recorder in the components tree deleted a parameter of the
  same name instead.
- `898c167` #18: `ComponentKind`; ribbon, tree and search follow the dialect's kinds.
  Imports, slots, Python paths stayed fixed buttons for later.
- `eb50e1a` #19: bundled the pywr 2.0.0rc1 JSON Schema; validation adds checks the schema
  cannot express (unique names, edges between existing non-virtual nodes). Other invalid
  models are left to fail when run.
- `dea9f45` #30: typed reference find/rename. Local parameter references are listed but
  not renamed (names unique only within a node).
- `cd8f0c0` #20: pywr-next model layer (`NextNodes`, `NextEdges`, `VirtualNodes`).
  Multi-network models are refused. The "cannot open yet" check moved to the window.
- `aa2ca71`, `9c6c4cc`: test hygiene for #43: close/delete leftover widgets
  (`delete_windows_after_test` autouse fixture). It mitigates the crash, it is not the
  root cause.
- `2995a27` #23: every pywr-next test model round-trips; sidecar moves node style,
  colour, size, geometry out of `meta.position` (pywr-next silently ignores it).
- `e11c2b3` #25: forms generated from the schema; unknown values editable as JSON; forms can
  keep an empty list/dict (`"spill": {}` has meaning).
- `9ac99e8` #26: `MetricWidget` follows the schema, so it follows the pywr-next version.
- `0ee05c6`: merged `main` (dark mode) into the branch; one conflict in the about dialog.

### Opening and editing
- `db7fd79` #22: pywr-next models open on the schematic; each dialect lists features;
  disabled v1-only actions say why; all node dialog entry points use
  `MainWindow.open_node_dialog()`. Positions saved in `meta.position` (#21). Checked on the
  Thames model.
- `d7a221a` #27: node dialog from the schema. The node data panel stays v1 (separate
  feature `node-data-panel`).
- `84c1908` #28: `NamedComponents` and `NextComponentsDialog` for parameters; local
  parameters opened from the node dialog.
- `fd23ac6` #29 #33 #34: tables (tagged by `format`), time series, metric sets (single
  shape, no type picker) and outputs through the same dialog. Metric sets' metrics,
  aggregator and filters are JSON for now.
- `1b69948` #41: "New model" asks for v1 or pywr-next.
- `b1ebf7e` #36: managed environment and consent dialog. Version installed = version of the
  bundled schema. uv from the bundle or the PATH. Bundling uv is #45.
- `d624d9b` #44: appearance in `meta.tags` as `editor:*`; shapes, map, GeoJSON stay in the
  sidecar; older locations are migrated on load.
- `2c45ba2` #37: runner service client (`runner.py`, `runner_protocol.py`), same signals as
  the v1 worker. Service ended with the editor (shutdown, terminate, `PR_SET_PDEATHSIG`
  on Linux). Environment installs the `pandas` and `excel` extras.

### Work ordered on 2026-11-09 (priority order #39, #32, #35, #38, #31, #40)
- `d7d351d` #39: Python parameter editor with checks and a separate-process dry run.
  Calling conventions verified on the real package.
- `72f9f2c` #32: time and scenarios dialogs; own ribbon panel (`ComponentKind.panel`)
  because the settings panel allows only three small buttons. The toolbar date/timestep
  fields are disabled for models they cannot show. Also stopped writing starter code for a
  missing Python function unless the user edits or tests it (it created files next to
  models and one in the test models folder).
- `7bfc329` #35 (read from "#53"): "Add to metric set..." on nodes and parameters; node
  dialog lists the metric sets of the node. Feature `metric-sets`.
- `a0021be` #38: results opened in the v1 results viewer. The service writes an Arrow
  stream (CSV output rounds to 2 decimals); the environment's Python converts it to the v1
  results folder format. A stopped run keeps results up to its last step.
- `ad8c391` #31: grouped node library; shapes for Delay, WaterTreatmentWorks, Turbine,
  Abstraction, PiecewiseStorage (`NODE_SHAPES`, `node_shape_name()`).
- `a36655f` #40: File > "Convert to pywr-next" (feature `convert-to-next`) using pywr-next's
  converter in the environment; dialog lists what could not be converted; shapes, map,
  GIS layers and node appearance carry over. Recorders are not converted.

### After the list
- `eb8d8b7` #46: nodes without a schematic position are placed at their geographic position
  (same projection as the geographic view); nodes with neither are centred as before.
  Applies to v1 models too. Thames: 62 distinct positions, in a thin vertical strip.
- `caba1b8` (#43): `RunWidget` deleted its thread right after `exit()`, and Qt aborts with
  "QThread: Destroyed while thread is still running" if the worker is still in the thread.
  The thread is now deleted from its own `finished` signal. Regression test runs a real
  `RunWidget` with a slow worker in a subprocess.

- `5b1f587` docs: this file and `CLAUDE.md`. Decided with the
  user: the log lives in the repo on the branch (so it travels with the work and is loaded
  through `CLAUDE.md`), with a pointer in Claude's memory; every commit must update it.
  The stdin watchdog (section 8) was deliberately left out of this commit.

- `a446587` #47: the runner service stops when the editor
  dies. `SERVER_SNIPPET` starts a daemon thread that reads stdin and calls `os._exit(0)` on
  end-of-file; QProcess keeps the service's stdin pipe open and the OS closes it when the
  editor ends, so it needs no OS-specific call (Windows and macOS are untested here;
  Linux keeps `PR_SET_PDEATHSIG` as well). Tested on the real service, idle and while it
  runs a long model: a plain `run_server` survives the editor being killed, the snippet
  does not. This corrects the earlier claim in #47 that the GIL prevents a watchdog thread
  (it does not, also mid-run). The old lifetime test let the service inherit pytest's
  stdin (immediate end-of-file), so it could pass without proving anything; the new tests
  hold a real pipe. Stray `run_server` processes found earlier were from probe scripts
  that bypassed the snippet, not from the editor.

- (this commit, hash to be added next time) docs: recorded the decisions for #48-#50
  (blocking vs warning policy, order, branch plan), the tested edge rules of pywr v1 and
  pywr-next, and the schema constraint counts. No code changed.

### Next entries
Add a row here with every new commit: hash, issue, decisions. A commit cannot contain its
own hash, so write the entry as "(this commit)" and fill in the hash in the next commit.

## 10. Rules for every commit

1. One commit per issue where possible; title ends with `(#N)`; body says what and why.
   Trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (use the attribution the
   session gives).
2. Add the commit to section 9 with its decisions, and update sections 3, 7 and 8 if they
   change. This file is part of the same commit.
3. Run the relevant tests, and the full suite before a push that closes an issue.
4. Comment on the issue with what was built and what was not; update PR #42's body.
5. Update the memory note `project_pywr_next_dialect.md` when decisions or status change.
6. Never touch `/home/stephen/git/pywr/editor` (the user's `dark-mode` checkout).
7. Confirm with the user before hard-to-reverse or outward-facing actions.
