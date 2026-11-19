The models in this folder are copied from the tests of pywr-next
(https://github.com/pywr/pywr-next, `pywr-schema/tests/`, commit b1657e21),
released under the MIT licence in `LICENSE-MIT` (pywr-next is also available under
the Apache-2.0 licence). Only the JSON files are copied, not the data files they read.

- `invalid/`: models that pywr-next refuses to load.
- `multi1/`, `multi2/`: multi-network models and the network files they reference.
- `v1/`: pywr v1 models used by pywr-next's conversion tests, and the pywr-next models
  they convert to (`*-converted.json`).
